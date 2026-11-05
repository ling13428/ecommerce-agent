from __future__ import annotations

import logging
import threading
from typing import Any

from core.config import get_settings

logger = logging.getLogger("ecommerce_agent.cache")

_client: Any = None
_failed = False
_lock = threading.Lock()


def cache_backend() -> str:
    return (get_settings().cache_backend or "memory").strip().lower()


def redis_enabled() -> bool:
    return cache_backend() == "redis"


def get_redis() -> Any | None:
    global _client, _failed
    if not redis_enabled():
        return None
    with _lock:
        if _client is not None:
            return _client
        if _failed:
            return None
        try:
            import redis

            client = redis.Redis.from_url(
                get_settings().redis_url,
                decode_responses=True,
                socket_timeout=1.0,
                socket_connect_timeout=1.0,
            )
            client.ping()
        except Exception as exc:
            _failed = True
            logger.warning("Redis 不可用，回退到进程内存：%s", exc)
            return None
        _client = client
        logger.info("Redis 已连接")
        return client


def set_redis_client(client: Any | None) -> None:
    global _client, _failed
    with _lock:
        _client = client
        _failed = False


def reset_cache() -> None:
    global _client, _failed
    with _lock:
        _client = None
        _failed = False
