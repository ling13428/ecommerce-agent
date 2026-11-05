from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any, Callable

from psycopg.types.json import Jsonb

from core.db import get_pool
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

_schema_ready = False
_schema_lock = threading.Lock()
_sink: Callable[[dict[str, Any]], None] | None = None


def set_audit_sink(sink: Callable[[dict[str, Any]], None] | None) -> None:
    global _sink
    _sink = sink


def reset_audit() -> None:
    global _schema_ready, _sink
    _schema_ready = False
    _sink = None


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


def _safe_args(args: dict[str, Any]) -> dict[str, str]:
    return {
        key: redact(str(value))[:120]
        for key, value in args.items()
        if key in _SAFE_ARG_KEYS and value is not None
    }


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
    row = {
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

    if _sink is not None:
        _sink(row)
        return

    try:
        with get_pool().connection() as connection:
            _ensure_schema(connection)
            connection.execute(
                "INSERT INTO audit_log "
                "(created_at, actor, session_id, tool, action, target, "
                " args_digest, args, ok, detail, transport) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
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
                ),
            )
    except Exception as exc:
        logger.warning("审计日志写入失败：%s", exc)


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
