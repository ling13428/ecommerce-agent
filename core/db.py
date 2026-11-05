from __future__ import annotations

import logging
import threading

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from core.config import get_settings

logger = logging.getLogger("ecommerce_agent.db")

_pool: ConnectionPool | None = None
_lock = threading.Lock()


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


def reset_pool() -> None:
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close()
        _pool = None
