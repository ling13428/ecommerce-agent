from __future__ import annotations

import copy
import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

from core.cache import get_redis

logger = logging.getLogger("ecommerce_agent.mcp.idempotency")

_DEFAULT_TTL_SECONDS = 24 * 60 * 60
_LOCK_TTL_SECONDS = 60
_MAX_ENTRIES = 1000

_cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
_lock = threading.Lock()


def _memory_get(key: str, ttl: int) -> dict[str, Any] | None:
    now = time.monotonic()
    with _lock:
        cached = _cache.get(key)
        if cached is None:
            return None
        created_at, value = cached
        if now - created_at > ttl:
            _cache.pop(key, None)
            return None
        _cache.move_to_end(key)
        return copy.deepcopy(value)


def _memory_set(key: str, value: dict[str, Any]) -> None:
    with _lock:
        _cache[key] = (time.monotonic(), copy.deepcopy(value))
        _cache.move_to_end(key)
        while len(_cache) > _MAX_ENTRIES:
            _cache.popitem(last=False)


def run_once(
    key: str,
    func: Callable[[], dict[str, Any]],
    *,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    client = get_redis()
    if client is not None:
        lock_key = f"mcp:idempotency:lock:{key}"
        result_key = f"mcp:idempotency:result:{key}"
        try:
            cached = client.get(result_key)
            if cached:
                return copy.deepcopy(json.loads(cached))
            acquired = client.set(lock_key, "1", nx=True, ex=_LOCK_TTL_SECONDS)
        except Exception as exc:
            logger.warning("Redis 幂等不可用，回退进程内存：%s", exc)
        else:
            if not acquired:
                cached = client.get(result_key)
                if cached:
                    return copy.deepcopy(json.loads(cached))
                return {
                    "found": False,
                    "status": "processing",
                    "message": "该操作正在处理中，请稍后重试",
                }
            try:
                result = func()
                client.set(
                    result_key,
                    json.dumps(result, ensure_ascii=False),
                    ex=ttl_seconds,
                )
                return result
            finally:
                try:
                    client.delete(lock_key)
                except Exception as exc:
                    logger.warning("释放幂等锁失败：%s", exc)

    cached = _memory_get(key, ttl_seconds)
    if cached is not None:
        return cached
    result = func()
    _memory_set(key, result)
    return result
