from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from core.config import get_settings

logger = logging.getLogger("ecommerce_agent.cache")

_client: Any = None
_failed = False
_lock = threading.Lock()

_async_clients: dict[int, Any] = {}
_async_locks: dict[int, asyncio.Lock] = {}
_async_failures: dict[int, float] = {}
_async_override: Any = None
_ASYNC_RETRY_COOLDOWN = 5.0


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

            settings = get_settings()
            client = redis.Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_timeout=1.0,
                socket_connect_timeout=1.0,
                max_connections=settings.redis_max_connections,
            )
            client.ping()
        except Exception as exc:
            _failed = True
            logger.warning("Redis 不可用，回退到进程内存：%s", exc)
            return None
        _client = client
        logger.info("Redis 已连接")
        return client


async def get_async_redis() -> Any | None:
    """Return a per-event-loop ``redis.asyncio`` client.

    The async client is the hot path for chat/session/lock/rate-limit code.
    The sync client above stays for scripts and sync endpoints.
    """
    if not redis_enabled():
        return None
    if _async_override is not None:
        return _async_override
    loop = asyncio.get_running_loop()
    key = id(loop)
    client = _async_clients.get(key)
    if client is not None:
        return client
    failed_at = _async_failures.get(key)
    if failed_at is not None and time.monotonic() - failed_at < _ASYNC_RETRY_COOLDOWN:
        return None

    lock = _async_locks.setdefault(key, asyncio.Lock())
    async with lock:
        client = _async_clients.get(key)
        if client is not None:
            return client
        try:
            from redis.asyncio import Redis as AsyncRedis

            settings = get_settings()
            client = AsyncRedis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_timeout=1.0,
                socket_connect_timeout=1.0,
                max_connections=settings.redis_max_connections,
            )
            await client.ping()
        except Exception as exc:
            _async_failures[key] = time.monotonic()
            logger.warning("异步 Redis 不可用，回退到进程内存：%s", exc)
            return None
        _async_clients[key] = client
        _async_failures.pop(key, None)
        logger.info("异步 Redis 已连接")
        return client


async def close_async_redis() -> None:
    clients = list(_async_clients.values())
    _async_clients.clear()
    _async_locks.clear()
    _async_failures.clear()
    for client in clients:
        try:
            await client.aclose()
        except Exception as exc:
            logger.warning("关闭异步 Redis 失败：%s", exc)


def set_async_redis_client(client: Any | None) -> None:
    """Inject a fake async client in tests (works outside a loop)."""
    global _async_override
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        _async_override = client
        return
    with _lock:
        if client is None:
            _async_clients.pop(id(loop), None)
        else:
            _async_clients[id(loop)] = client


def reset_async_cache() -> None:
    global _async_override
    _async_override = None
    _async_clients.clear()
    _async_locks.clear()
    _async_failures.clear()


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
    reset_async_cache()
