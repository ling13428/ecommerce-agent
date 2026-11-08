from __future__ import annotations

import asyncio
import logging
import sys
import threading
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, ConnectionPool

from core.config import get_settings

logger = logging.getLogger("ecommerce_agent.db")

_pool: ConnectionPool | None = None
_lock = threading.Lock()

_async_pools: dict[int, AsyncConnectionPool] = {}
_async_locks: dict[int, asyncio.Lock] = {}


def get_pool() -> ConnectionPool:
    global _pool
    with _lock:
        if _pool is None:
            settings = get_settings()
            _pool = ConnectionPool(
                conninfo=settings.database_url,
                min_size=1,
                max_size=settings.database_pool_max_size,
                timeout=settings.database_pool_timeout,
                kwargs={"row_factory": dict_row, "autocommit": True},
                open=True,
            )
            logger.info("PostgreSQL 连接池已创建")
        return _pool


async def get_async_pool() -> AsyncConnectionPool | None:
    """Shared async pool for runtime DB work (orders/audit).

    Returns None on Windows ProactorEventLoop where async psycopg cannot run;
    callers should fall back to their dedicated thread pool.
    """
    loop = asyncio.get_running_loop()
    if sys.platform == "win32" and type(loop).__name__ == "ProactorEventLoop":
        return None
    key = id(loop)
    pool = _async_pools.get(key)
    if pool is not None:
        return pool
    lock = _async_locks.setdefault(key, asyncio.Lock())
    async with lock:
        pool = _async_pools.get(key)
        if pool is not None:
            return pool
        settings = get_settings()
        pool = AsyncConnectionPool(
            conninfo=settings.database_url,
            min_size=settings.database_async_pool_min_size,
            max_size=settings.database_async_pool_max_size,
            timeout=settings.database_async_pool_timeout,
            kwargs={"row_factory": dict_row, "autocommit": True},
            open=False,
        )
        await pool.open(wait=True, timeout=settings.database_async_pool_timeout)
        _async_pools[key] = pool
        logger.info(
            "异步 PostgreSQL 连接池已创建 | pool=%d",
            settings.database_async_pool_max_size,
        )
        return pool


async def close_async_pool() -> None:
    pools = list(_async_pools.values())
    _async_pools.clear()
    _async_locks.clear()
    for pool in pools:
        try:
            await pool.close()
        except Exception as exc:
            logger.warning("关闭异步 PostgreSQL 连接池失败：%s", exc)


def reset_async_pool() -> None:
    _async_pools.clear()
    _async_locks.clear()


def reset_pool() -> None:
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close()
        _pool = None
    reset_async_pool()


def pool_stats() -> dict[str, Any]:
    if _pool is None:
        return {"sync": None, "async": len(_async_pools)}
    return {"sync": _pool.get_stats(), "async": len(_async_pools)}
