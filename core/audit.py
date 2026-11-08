from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from psycopg.types.json import Jsonb

from core.config import get_settings
from core.db import get_async_pool, get_pool
from core.security import redact

logger = logging.getLogger("ecommerce_agent.audit")

SENSITIVE_READS = {"get_order", "get_logistics", "get_aftersale"}
_SAFE_ARG_KEYS = {
    "order_id",
    "tracking_no",
    "product_id",
    "aftersale_type",
    "reason",
}

_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id BIGSERIAL PRIMARY KEY,
        created_at DOUBLE PRECISION NOT NULL,
        actor TEXT,
        session_id TEXT,
        tool TEXT NOT NULL,
        action TEXT NOT NULL,
        target TEXT,
        args_digest TEXT,
        args JSONB,
        ok BOOLEAN NOT NULL,
        detail TEXT,
        transport TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_created
        ON audit_log (created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_actor
        ON audit_log (actor, created_at DESC)
    """,
]

_INSERT_SQL = (
    "INSERT INTO audit_log "
    "(created_at, actor, session_id, tool, action, target, "
    " args_digest, args, ok, detail, transport) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)

_schema_ready = False
_schema_lock = threading.Lock()
_sink: Callable[[dict[str, Any]], None] | None = None

_async_schema_ready: set[int] = set()
_async_schema_locks: dict[int, asyncio.Lock] = {}

_audit_executor: ThreadPoolExecutor | None = None
_audit_executor_lock = threading.Lock()


def set_audit_sink(sink: Callable[[dict[str, Any]], None] | None) -> None:
    global _sink
    _sink = sink


def reset_audit() -> None:
    global _schema_ready, _sink
    _schema_ready = False
    _sink = None
    _async_schema_ready.clear()
    _async_schema_locks.clear()


def _executor() -> ThreadPoolExecutor:
    global _audit_executor
    with _audit_executor_lock:
        if _audit_executor is None:
            workers = getattr(get_settings(), "audit_workers", 2)
            _audit_executor = ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="audit-db"
            )
        return _audit_executor


def shutdown_executor() -> None:
    global _audit_executor
    with _audit_executor_lock:
        if _audit_executor is not None:
            _audit_executor.shutdown(wait=False, cancel_futures=True)
            _audit_executor = None


async def _run_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
    loop = asyncio.get_running_loop()
    call = functools.partial(func, *args, **kwargs)
    return await loop.run_in_executor(_executor(), call)


def _ensure_schema(connection: Any) -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        for statement in _SCHEMA:
            connection.execute(statement)
        _schema_ready = True


async def _async_ensure_schema(connection: Any) -> None:
    loop_id = id(asyncio.get_running_loop())
    if loop_id in _async_schema_ready:
        return
    lock = _async_schema_locks.setdefault(loop_id, asyncio.Lock())
    async with lock:
        if loop_id in _async_schema_ready:
            return
        for statement in _SCHEMA:
            await connection.execute(statement)
        _async_schema_ready.add(loop_id)


def _safe_args(args: dict[str, Any]) -> dict[str, str]:
    return {
        key: redact(str(value))[:120]
        for key, value in args.items()
        if key in _SAFE_ARG_KEYS and value is not None
    }


def _build_row(
    *,
    tool: str,
    kind: str,
    args: dict[str, Any],
    result: dict[str, Any],
    context: Any = None,
    transport: str = "local",
) -> dict[str, Any]:
    actor = getattr(context, "buyer_id", None)
    session_id = getattr(context, "session_id", None)
    target = (
        args.get("order_id")
        or args.get("tracking_no")
        or args.get("product_id")
    )
    digest = hashlib.sha256(
        json.dumps(args, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return {
        "created_at": time.time(),
        "actor": actor,
        "session_id": session_id,
        "tool": tool,
        "action": "write" if kind == "write" else "read_sensitive",
        "target": str(target) if target else None,
        "args_digest": digest,
        "args": _safe_args(args),
        "ok": bool(result.get("ok")),
        "detail": str(
            result.get("error")
            or result.get("message")
            or result.get("status")
            or ""
        )[:300],
        "transport": transport,
    }


def _row_params(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["created_at"],
        row["actor"],
        row["session_id"],
        row["tool"],
        row["action"],
        row["target"],
        row["args_digest"],
        Jsonb(row["args"]),
        row["ok"],
        row["detail"],
        row["transport"],
    )


def _insert_sync(row: dict[str, Any]) -> None:
    try:
        with get_pool().connection() as connection:
            _ensure_schema(connection)
            connection.execute(_INSERT_SQL, _row_params(row))
    except Exception as exc:
        logger.warning("审计日志写入失败：%s", exc)


def record_tool_audit(
    *,
    tool: str,
    kind: str,
    args: dict[str, Any],
    result: dict[str, Any],
    context: Any = None,
    transport: str = "local",
) -> None:
    if kind != "write" and tool not in SENSITIVE_READS:
        return

    row = _build_row(
        tool=tool,
        kind=kind,
        args=args,
        result=result,
        context=context,
        transport=transport,
    )

    if _sink is not None:
        _sink(row)
        return

    if not get_settings().audit_enabled:
        return

    _insert_sync(row)


async def record_tool_audit_async(
    *,
    tool: str,
    kind: str,
    args: dict[str, Any],
    result: dict[str, Any],
    context: Any = None,
    transport: str = "local",
) -> None:
    if kind != "write" and tool not in SENSITIVE_READS:
        return

    row = _build_row(
        tool=tool,
        kind=kind,
        args=args,
        result=result,
        context=context,
        transport=transport,
    )

    if _sink is not None:
        _sink(row)
        return

    if not get_settings().audit_enabled:
        return

    pool = await get_async_pool()
    if pool is not None:
        try:
            async with pool.connection() as connection:
                await _async_ensure_schema(connection)
                await connection.execute(_INSERT_SQL, _row_params(row))
            return
        except Exception as exc:
            logger.warning("异步审计写入失败，回退线程池：%s", exc)

    await _run_thread(_insert_sync, row)


def list_audit(limit: int = 50, actor: str | None = None) -> list[dict[str, Any]]:
    try:
        with get_pool().connection() as connection:
            _ensure_schema(connection)
            if actor:
                rows = connection.execute(
                    "SELECT * FROM audit_log WHERE actor = %s "
                    "ORDER BY created_at DESC LIMIT %s",
                    (actor, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM audit_log "
                    "ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                ).fetchall()
    except Exception as exc:
        logger.warning("审计日志查询失败：%s", exc)
        return []
    return [dict(row) for row in rows]


async def list_audit_async(
    limit: int = 50, actor: str | None = None
) -> list[dict[str, Any]]:
    pool = await get_async_pool()
    if pool is None:
        return await _run_thread(list_audit, limit, actor)
    try:
        async with pool.connection() as connection:
            await _async_ensure_schema(connection)
            if actor:
                cursor = await connection.execute(
                    "SELECT * FROM audit_log WHERE actor = %s "
                    "ORDER BY created_at DESC LIMIT %s",
                    (actor, limit),
                )
            else:
                cursor = await connection.execute(
                    "SELECT * FROM audit_log "
                    "ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                )
            rows = await cursor.fetchall()
    except Exception as exc:
        logger.warning("审计日志查询失败：%s", exc)
        return []
    return [dict(row) for row in rows]
