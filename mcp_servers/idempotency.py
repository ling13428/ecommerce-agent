from __future__ import annotations

import copy
import json
import logging
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, Callable

from core.cache import get_redis
from core.config import get_settings

logger = logging.getLogger("ecommerce_agent.mcp.idempotency")

_DEFAULT_TTL_SECONDS = 24 * 60 * 60
_DEFAULT_LOCK_TTL_SECONDS = 60
_DEFAULT_MAX_ENTRIES = 5000

_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) else return 0 end"
)
_RENEW_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('pexpire', KEYS[1], ARGV[2]) else return 0 end"
)

_cache: OrderedDict[str, tuple[float, int, dict[str, Any]]] = OrderedDict()
_lock = threading.Lock()


def _setting(name: str, default: Any) -> Any:
    return getattr(get_settings(), name, default)


def _memory_get(key: str) -> dict[str, Any] | None:
    now = time.monotonic()
    with _lock:
        cached = _cache.get(key)
        if cached is None:
            return None
        created_at, ttl, value = cached
        if now - created_at > ttl:
            _cache.pop(key, None)
            return None
        _cache.move_to_end(key)
        return copy.deepcopy(value)


def _memory_set(key: str, value: dict[str, Any], ttl: int) -> None:
    with _lock:
        _cache[key] = (time.monotonic(), max(1, ttl), copy.deepcopy(value))
        _cache.move_to_end(key)
        limit = max(1, int(_setting("tool_idempotency_max_entries", _DEFAULT_MAX_ENTRIES)))
        while len(_cache) > limit:
            _cache.popitem(last=False)


def _release(client: Any, key: str, owner: str) -> None:
    if not key or not owner:
        return
    try:
        eval_fn = getattr(client, "eval", None)
        if eval_fn is not None:
            eval_fn(_RELEASE_LUA, 1, key, owner)
            return
        if client.get(key) == owner:
            client.delete(key)
    except Exception as exc:
        logger.warning("释放幂等锁失败：%s", exc)


def _renew(client: Any, key: str, owner: str, ttl: int) -> None:
    if not key or not owner:
        return
    ttl_ms = max(1000, int(ttl * 1000))
    try:
        eval_fn = getattr(client, "eval", None)
        if eval_fn is not None:
            eval_fn(_RENEW_LUA, 1, key, owner, ttl_ms)
            return
        pexpire = getattr(client, "pexpire", None)
        if pexpire is not None and client.get(key) == owner:
            pexpire(key, ttl_ms)
            return
        expire = getattr(client, "expire", None)
        if expire is not None and client.get(key) == owner:
            expire(key, int(ttl))
    except Exception as exc:
        logger.warning("续租幂等锁失败：%s", exc)


class _LockHeartbeat:
    def __init__(self, client: Any, key: str, owner: str, ttl: int) -> None:
        self._client = client
        self._key = key
        self._owner = owner
        self._ttl = max(1, int(ttl))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="mcp-idempotency-lock",
        )
        self._thread.start()

    def _run(self) -> None:
        interval = max(0.5, self._ttl / 3.0)
        while not self._stop.wait(interval):
            _renew(self._client, self._key, self._owner, self._ttl)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)


def run_once(
    key: str,
    func: Callable[[], dict[str, Any]],
    *,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    client = get_redis()
    lock_ttl = max(
        1,
        int(
            _setting(
                "tool_idempotency_lock_ttl_seconds",
                _DEFAULT_LOCK_TTL_SECONDS,
            )
        ),
    )
    if client is not None:
        lock_key = f"mcp:idempotency:lock:{key}"
        result_key = f"mcp:idempotency:result:{key}"
        owner = ""
        heartbeat: _LockHeartbeat | None = None
        try:
            cached = client.get(result_key)
            if cached:
                return copy.deepcopy(json.loads(cached))
            fence = 0
            try:
                fence = int(client.incr(f"mcp:idempotency:fence:{key}"))
            except Exception:
                fence = 0
            owner = f"{fence}:{uuid.uuid4().hex}"
            acquired = client.set(lock_key, owner, nx=True, ex=lock_ttl)
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
            heartbeat = _LockHeartbeat(client, lock_key, owner, lock_ttl)
            heartbeat.start()
            try:
                result = func()
                client.set(
                    result_key,
                    json.dumps(result, ensure_ascii=False),
                    ex=ttl_seconds,
                )
                return result
            finally:
                if heartbeat is not None:
                    heartbeat.stop()
                _release(client, lock_key, owner)

    cached = _memory_get(key)
    if cached is not None:
        return cached
    result = func()
    _memory_set(key, result, ttl_seconds)
    return result
