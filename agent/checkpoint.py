from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import aiosqlite
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from psycopg_pool import AsyncConnectionPool

from core.config import get_settings

_memory_saver: MemorySaver | None = None
_sqlite_savers: dict[int, BaseCheckpointSaver] = {}
_postgres_savers: dict[int, BaseCheckpointSaver] = {}
_postgres_pools: dict[int, AsyncConnectionPool] = {}
_lock = asyncio.Lock()


def reset_checkpointers() -> None:
    global _memory_saver
    _memory_saver = None
    _sqlite_savers.clear()
    _postgres_savers.clear()
    _postgres_pools.clear()


async def _get_postgres_saver() -> BaseCheckpointSaver:
    loop_key = id(asyncio.get_running_loop())
    saver = _postgres_savers.get(loop_key)
    if saver is not None:
        return saver

    async with _lock:
        saver = _postgres_savers.get(loop_key)
        if saver is not None:
            return saver
        settings = get_settings()
        pool = AsyncConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=settings.database_pool_max_size,
            open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0},
        )
        await pool.open(wait=True, timeout=settings.database_pool_timeout)
        saver = AsyncPostgresSaver(cast(Any, pool))
        await saver.setup()
        _postgres_pools[loop_key] = pool
        _postgres_savers[loop_key] = saver
    return saver


async def get_checkpointer() -> BaseCheckpointSaver:
    settings = get_settings()
    backend = (settings.agent_checkpoint_backend or "sqlite").strip().lower()

    if backend == "memory":
        global _memory_saver
        if _memory_saver is None:
            _memory_saver = MemorySaver()
        return _memory_saver

    if backend == "postgres":
        return await _get_postgres_saver()

    loop_key = id(asyncio.get_running_loop())
    saver = _sqlite_savers.get(loop_key)
    if saver is not None:
        return saver

    async with _lock:
        saver = _sqlite_savers.get(loop_key)
        if saver is None:
            path = Path(settings.agent_checkpoint_db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = await aiosqlite.connect(str(path))
            saver = AsyncSqliteSaver(conn)
            await saver.setup()
            _sqlite_savers[loop_key] = saver
    return saver


async def delete_thread(thread_id: str) -> None:
    saver = await get_checkpointer()
    await saver.adelete_thread(thread_id)
