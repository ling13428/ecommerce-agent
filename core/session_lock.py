from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from core.cache import get_async_redis
from core.config import get_settings

logger = logging.getLogger("ecommerce_agent.session_lock")

_locks: dict[tuple[int, str], asyncio.Lock] = {}

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""

_EXTEND_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""


class SessionBusy(RuntimeError):
    """Raised when another request holds the same session lock."""


def _local_lock(session_id: str) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    key = (id(loop), session_id)
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


async def _release(client: Any, key: str, owner: str) -> None:
    try:
        if hasattr(client, "eval"):
            await client.eval(_RELEASE_SCRIPT, 1, key, owner)
            return
    except Exception:
        pass
    try:
        if await client.get(key) == owner:
            await client.delete(key)
    except Exception as exc:
        logger.warning("释放会话锁失败 key=%s：%s", key, exc)


async def _extend(client: Any, key: str, owner: str, ttl: int) -> None:
    try:
        if hasattr(client, "eval"):
            await client.eval(_EXTEND_SCRIPT, 1, key, owner, ttl)
            return
    except Exception:
        pass
    try:
        if await client.get(key) == owner:
            await client.expire(key, ttl)
    except Exception as exc:
        logger.warning("续租会话锁失败 key=%s：%s", key, exc)


@asynccontextmanager
async def session_lock(
    session_id: str, *, timeout: float | None = None
) -> AsyncIterator[None]:
    """Serialize writes for one session across threads and workers.

    Lock order: in-process asyncio lock first, then Redis. If Redis is not
    available the in-process lock still protects a single worker.
    """
    settings = get_settings()
    wait_seconds = (
        settings.session_lock_timeout_seconds if timeout is None else timeout
    )
    ttl = settings.session_lock_ttl_seconds

    local = _local_lock(session_id)
    try:
        await asyncio.wait_for(local.acquire(), timeout=wait_seconds)
    except asyncio.TimeoutError as exc:
        raise SessionBusy(f"会话 {session_id} 正在处理中") from exc

    client: Any = None
    owner = uuid.uuid4().hex
    redis_key = f"session:lock:{session_id}"
    redis_acquired = False
    renewal: asyncio.Task[None] | None = None
    stop = asyncio.Event()

    try:
        client = await get_async_redis()
    except Exception as exc:
        logger.warning("获取异步 Redis 失败，降级为进程内锁：%s", exc)
        client = None

    if client is not None:
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                acquired = await client.set(
                    redis_key, owner, nx=True, ex=ttl
                )
            except Exception as exc:
                logger.warning("Redis 会话锁不可用，降级为进程内锁：%s", exc)
                client = None
                break
            if acquired:
                redis_acquired = True
                break
            if time.monotonic() >= deadline:
                local.release()
                raise SessionBusy(f"会话 {session_id} 正在处理中")
            await asyncio.sleep(0.05)

    if redis_acquired and client is not None:

        async def _renew() -> None:
            interval = max(ttl / 3, 1.0)
            while not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=interval)
                    return
                except asyncio.TimeoutError:
                    pass
                await _extend(client, redis_key, owner, ttl)

        renewal = asyncio.create_task(_renew())

    try:
        yield
    finally:
        stop.set()
        if renewal is not None:
            renewal.cancel()
            try:
                await renewal
            except (asyncio.CancelledError, Exception):
                pass
        if redis_acquired and client is not None:
            await _release(client, redis_key, owner)
        local.release()
