from __future__ import annotations

import asyncio
import functools
import json
import logging
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from core.config import BASE_DIR, get_settings
from core.db import get_pool

logger = logging.getLogger("ecommerce_agent.session_repo")

_META_FIELDS = {
    "buyer_id",
    "status",
    "human_mode",
    "assigned_agent",
    "closed_at",
    "close_reason",
    "pending_action",
}

_SQLITE_SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    buyer_id TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    human_mode INTEGER NOT NULL DEFAULT 0,
    assigned_agent TEXT,
    created_at REAL NOT NULL DEFAULT 0,
    last_active_at REAL NOT NULL DEFAULT 0,
    closed_at REAL,
    close_reason TEXT,
    version INTEGER NOT NULL DEFAULT 0,
    pending_action TEXT,
    payload TEXT,
    updated_at REAL NOT NULL DEFAULT 0
)
"""

_SQLITE_ADD_COLUMNS = (
    ("buyer_id", "buyer_id TEXT"),
    ("status", "status TEXT NOT NULL DEFAULT 'active'"),
    ("human_mode", "human_mode INTEGER NOT NULL DEFAULT 0"),
    ("assigned_agent", "assigned_agent TEXT"),
    ("created_at", "created_at REAL NOT NULL DEFAULT 0"),
    ("last_active_at", "last_active_at REAL NOT NULL DEFAULT 0"),
    ("closed_at", "closed_at REAL"),
    ("close_reason", "close_reason TEXT"),
    ("version", "version INTEGER NOT NULL DEFAULT 0"),
    ("pending_action", "pending_action TEXT"),
    ("payload", "payload TEXT"),
    ("updated_at", "updated_at REAL NOT NULL DEFAULT 0"),
)

_SQLITE_MESSAGES_DDL = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    source TEXT,
    content TEXT NOT NULL,
    client_msg_id TEXT,
    created_at REAL NOT NULL
)
"""

_SQLITE_MESSAGES_INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_messages_client "
    "ON chat_messages (session_id, client_msg_id) "
    "WHERE client_msg_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_chat_messages_session "
    "ON chat_messages (session_id, id)",
)

_SQLITE_TRACES_DDL = """
CREATE TABLE IF NOT EXISTS chat_traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    user_message_id INTEGER,
    status TEXT,
    route TEXT,
    first_response_ms REAL,
    payload TEXT,
    created_at REAL NOT NULL
)
"""

_SQLITE_TRACES_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_chat_traces_session "
    "ON chat_traces (session_id, id)",
)

_POSTGRES_SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    buyer_id TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    human_mode BOOLEAN NOT NULL DEFAULT FALSE,
    assigned_agent TEXT,
    created_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    last_active_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    closed_at DOUBLE PRECISION,
    close_reason TEXT,
    version BIGINT NOT NULL DEFAULT 0,
    pending_action JSONB,
    payload JSONB,
    updated_at DOUBLE PRECISION NOT NULL DEFAULT 0
)
"""

_POSTGRES_ADD_COLUMNS = (
    ("buyer_id", "buyer_id TEXT"),
    ("status", "status TEXT NOT NULL DEFAULT 'active'"),
    ("human_mode", "human_mode BOOLEAN NOT NULL DEFAULT FALSE"),
    ("assigned_agent", "assigned_agent TEXT"),
    ("created_at", "created_at DOUBLE PRECISION NOT NULL DEFAULT 0"),
    ("last_active_at", "last_active_at DOUBLE PRECISION NOT NULL DEFAULT 0"),
    ("closed_at", "closed_at DOUBLE PRECISION"),
    ("close_reason", "close_reason TEXT"),
    ("version", "version BIGINT NOT NULL DEFAULT 0"),
    ("pending_action", "pending_action JSONB"),
    ("payload", "payload JSONB"),
    ("updated_at", "updated_at DOUBLE PRECISION NOT NULL DEFAULT 0"),
)

_POSTGRES_MESSAGES_DDL = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    source TEXT,
    content TEXT NOT NULL,
    client_msg_id TEXT,
    created_at DOUBLE PRECISION NOT NULL
)
"""

_POSTGRES_MESSAGES_INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_messages_client "
    "ON chat_messages (session_id, client_msg_id) "
    "WHERE client_msg_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_chat_messages_session "
    "ON chat_messages (session_id, id)",
)

_POSTGRES_TRACES_DDL = """
CREATE TABLE IF NOT EXISTS chat_traces (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_message_id BIGINT,
    status TEXT,
    route TEXT,
    first_response_ms DOUBLE PRECISION,
    payload JSONB,
    created_at DOUBLE PRECISION NOT NULL
)
"""

_POSTGRES_TRACES_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_chat_traces_session "
    "ON chat_traces (session_id, id)",
)


class VersionConflict(RuntimeError):
    """The caller wrote with a stale session version."""


class DuplicateMessage(RuntimeError):
    """A client_msg_id was already stored for this session."""


class SessionNotFound(RuntimeError):
    pass


def _sqlite_path() -> Path:
    path = Path(get_settings().session_db_path)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def _parse_pending(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return None
    return value if isinstance(value, dict) else None


class SqliteSessionRepository:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._ready = False

    def _connect(self) -> sqlite3.Connection:
        if self._connection is not None:
            return self._connection
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
            timeout=10,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        self._connection = connection
        return connection

    def ensure_schema(self) -> None:
        with self._lock:
            if self._ready:
                return
            connection = self._connect()
            connection.execute(_SQLITE_SESSIONS_DDL)
            columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(chat_sessions)"
                )
            }
            for name, ddl in _SQLITE_ADD_COLUMNS:
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE chat_sessions ADD COLUMN {ddl}"
                    )
            connection.execute(_SQLITE_MESSAGES_DDL)
            for statement in _SQLITE_MESSAGES_INDEXES:
                connection.execute(statement)
            connection.execute(_SQLITE_TRACES_DDL)
            for statement in _SQLITE_TRACES_INDEXES:
                connection.execute(statement)
            self._ready = True
            self._migrate_payloads(connection)

    def _migrate_payloads(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT session_id, payload FROM chat_sessions "
            "WHERE payload IS NOT NULL AND payload NOT IN ('', '{}')"
        ).fetchall()
        for row in rows:
            session_id = str(row["session_id"])
            try:
                record = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict):
                continue
            existing = connection.execute(
                "SELECT COUNT(*) AS total FROM chat_messages "
                "WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if existing is not None and int(existing["total"]) > 0:
                connection.execute(
                    "UPDATE chat_sessions SET payload = '{}' "
                    "WHERE session_id = ?",
                    (session_id,),
                )
                continue
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._migrate_record(connection, session_id, record)
                connection.execute(
                    "UPDATE chat_sessions SET payload = '{}' "
                    "WHERE session_id = ?",
                    (session_id,),
                )
                connection.execute("COMMIT")
            except Exception as exc:
                connection.execute("ROLLBACK")
                logger.warning("迁移会话失败 session=%s：%s", session_id, exc)

    def _migrate_record(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        record: dict[str, Any],
    ) -> None:
        updated_at = float(record.get("updated_at") or time.time())
        connection.execute(
            "UPDATE chat_sessions SET buyer_id = ?, human_mode = ?, "
            "created_at = ?, last_active_at = ?, updated_at = ?, "
            "pending_action = ?, version = 0 WHERE session_id = ?",
            (
                record.get("buyer_id"),
                1 if record.get("human_mode") else 0,
                float(record.get("created_at") or updated_at),
                updated_at,
                updated_at,
                json.dumps(record.get("pending_action"), ensure_ascii=False)
                if record.get("pending_action")
                else None,
                session_id,
            ),
        )
        id_map: dict[Any, int] = {}
        for message in record.get("messages") or []:
            if not isinstance(message, dict):
                continue
            cursor = connection.execute(
                "INSERT INTO chat_messages "
                "(session_id, role, source, content, client_msg_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    str(message.get("role") or "user"),
                    message.get("source"),
                    str(message.get("content") or ""),
                    message.get("client_msg_id"),
                    updated_at,
                ),
            )
            id_map[message.get("id")] = int(cursor.lastrowid or 0)
        for trace in record.get("traces") or []:
            if not isinstance(trace, dict):
                continue
            payload = dict(trace)
            old_user_id = payload.get("user_message_id")
            if old_user_id in id_map:
                payload["user_message_id"] = id_map[old_user_id]
            payload.pop("id", None)
            connection.execute(
                "INSERT INTO chat_traces "
                "(session_id, user_message_id, status, route, "
                "first_response_ms, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    payload.get("user_message_id"),
                    payload.get("status"),
                    payload.get("route"),
                    payload.get("first_response_ms"),
                    json.dumps(payload, ensure_ascii=False),
                    float(payload.get("started_at") or updated_at),
                ),
            )

    def create(self, session_id: str, buyer_id: str | None, now: float) -> None:
        with self._lock:
            connection = self._connect()
            connection.execute(
                "INSERT INTO chat_sessions "
                "(session_id, buyer_id, status, human_mode, created_at, "
                "last_active_at, updated_at, version, payload) "
                "VALUES (?, ?, 'active', 0, ?, ?, ?, 0, '{}') "
                "ON CONFLICT(session_id) DO NOTHING",
                (session_id, buyer_id, now, now, now),
            )

    def _row_to_meta(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "session_id": str(row["session_id"]),
            "buyer_id": row["buyer_id"],
            "status": str(row["status"] or "active"),
            "human_mode": bool(row["human_mode"]),
            "assigned_agent": row["assigned_agent"],
            "created_at": float(row["created_at"] or 0),
            "last_active_at": float(row["last_active_at"] or 0),
            "closed_at": row["closed_at"],
            "close_reason": row["close_reason"],
            "version": int(row["version"] or 0),
            "pending_action": _parse_pending(row["pending_action"]),
        }

    def get_meta(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            connection = self._connect()
            row = connection.execute(
                "SELECT * FROM chat_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return self._row_to_meta(row) if row is not None else None

    def _messages(self, connection: sqlite3.Connection, session_id: str):
        return connection.execute(
            "SELECT id, role, source, content, created_at "
            "FROM chat_messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()

    def _traces(self, connection: sqlite3.Connection, session_id: str):
        return connection.execute(
            "SELECT id, payload FROM chat_traces "
            "WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()

    def full_record(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            connection = self._connect()
            meta = self.get_meta(session_id)
            if meta is None:
                return None
            messages: list[dict[str, Any]] = [
                {
                    "id": int(row["id"]),
                    "role": str(row["role"]),
                    "content": str(row["content"]),
                    **(
                        {"source": str(row["source"])}
                        if row["source"]
                        else {}
                    ),
                }
                for row in self._messages(connection, session_id)
            ]
            traces: list[dict[str, Any]] = []
            for row in self._traces(connection, session_id):
                payload = json.loads(row["payload"]) if row["payload"] else {}
                payload["id"] = int(row["id"])
                traces.append(payload)
            record = dict(meta)
            record["messages"] = messages
            record["traces"] = traces
            record["updated_at"] = meta["last_active_at"]
            record["next_message_id"] = (
                int(messages[-1]["id"]) + 1 if messages else 1
            )
            record["next_trace_id"] = (
                int(traces[-1]["id"]) + 1 if traces else 1
            )
            return record

    def list_meta(self) -> list[dict[str, Any]]:
        with self._lock:
            connection = self._connect()
            rows: Any = connection.execute(
                "SELECT * FROM chat_sessions ORDER BY last_active_at ASC"
            ).fetchall()
        return [self._row_to_meta(row) for row in rows]

    def all_records(self) -> list[dict[str, Any]]:
        return [
            record
            for meta in self.list_meta()
            if (record := self.full_record(meta["session_id"])) is not None
        ]

    def append_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        source: str | None,
        client_msg_id: str | None,
        expected_version: int,
        now: float,
    ) -> tuple[int, int]:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "UPDATE chat_sessions SET version = version + 1, "
                    "last_active_at = ?, updated_at = ? "
                    "WHERE session_id = ? AND version = ?",
                    (now, now, session_id, expected_version),
                )
                if cursor.rowcount == 0:
                    connection.execute("ROLLBACK")
                    raise VersionConflict(session_id)
                cursor = connection.execute(
                    "INSERT INTO chat_messages "
                    "(session_id, role, source, content, client_msg_id, "
                    "created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        session_id,
                        role,
                        source,
                        content,
                        client_msg_id,
                        now,
                    ),
                )
                new_id = int(cursor.lastrowid or 0)
                connection.execute("COMMIT")
                return new_id, expected_version + 1
            except sqlite3.IntegrityError as exc:
                connection.execute("ROLLBACK")
                raise DuplicateMessage(str(exc)) from exc
            except VersionConflict:
                raise
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except Exception:
                    pass
                raise

    def append_trace(
        self,
        session_id: str,
        trace: dict[str, Any],
        *,
        expected_version: int,
        now: float,
    ) -> tuple[int, int]:
        payload = dict(trace)
        payload.pop("id", None)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "UPDATE chat_sessions SET version = version + 1, "
                    "last_active_at = ?, updated_at = ? "
                    "WHERE session_id = ? AND version = ?",
                    (now, now, session_id, expected_version),
                )
                if cursor.rowcount == 0:
                    connection.execute("ROLLBACK")
                    raise VersionConflict(session_id)
                cursor = connection.execute(
                    "INSERT INTO chat_traces "
                    "(session_id, user_message_id, status, route, "
                    "first_response_ms, payload, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        session_id,
                        payload.get("user_message_id"),
                        payload.get("status"),
                        payload.get("route"),
                        payload.get("first_response_ms"),
                        json.dumps(payload, ensure_ascii=False),
                        float(payload.get("started_at") or now),
                    ),
                )
                new_id = int(cursor.lastrowid or 0)
                connection.execute("COMMIT")
                return new_id, expected_version + 1
            except VersionConflict:
                raise
            except Exception:
                try:
                    connection.execute("ROLLBACK")
                except Exception:
                    pass
                raise

    def update_meta(
        self,
        session_id: str,
        changes: dict[str, Any],
        *,
        expected_version: int,
        now: float,
    ) -> int:
        sets: list[str] = []
        params: list[Any] = []
        for key, value in changes.items():
            if key not in _META_FIELDS:
                continue
            if key == "pending_action":
                value = (
                    json.dumps(value, ensure_ascii=False)
                    if value is not None
                    else None
                )
            sets.append(f"{key} = ?")
            params.append(value)
        sets.extend(
            ["last_active_at = ?", "updated_at = ?", "version = version + 1"]
        )
        params.extend([now, now, session_id, expected_version])
        sql = (
            f"UPDATE chat_sessions SET {', '.join(sets)} "
            "WHERE session_id = ? AND version = ?"
        )
        with self._lock:
            connection = self._connect()
            cursor: Any = connection.execute(sql, params)
            if cursor.rowcount == 0:
                raise VersionConflict(session_id)
        return expected_version + 1

    def delete_older_than(self, cutoff: float) -> int:
        with self._lock:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM chat_messages WHERE session_id IN "
                "(SELECT session_id FROM chat_sessions "
                "WHERE last_active_at < ?)",
                (cutoff,),
            )
            connection.execute(
                "DELETE FROM chat_traces WHERE session_id IN "
                "(SELECT session_id FROM chat_sessions "
                "WHERE last_active_at < ?)",
                (cutoff,),
            )
            cursor = connection.execute(
                "DELETE FROM chat_sessions WHERE last_active_at < ?",
                (cutoff,),
            )
            connection.execute("COMMIT")
            return int(cursor.rowcount)

    def clear(self) -> None:
        with self._lock:
            connection = self._connect()
            connection.execute("DELETE FROM chat_messages")
            connection.execute("DELETE FROM chat_traces")
            connection.execute("DELETE FROM chat_sessions")


class PostgresSessionRepository:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._ready = False

    def ensure_schema(self) -> None:
        with self._lock:
            if self._ready:
                return
            with get_pool().connection() as connection:
                connection.execute(_POSTGRES_SESSIONS_DDL)
                rows: Any = connection.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'chat_sessions'"
                ).fetchall()
                columns = {str(row["column_name"]) for row in rows}
                for name, ddl in _POSTGRES_ADD_COLUMNS:
                    if name not in columns:
                        connection.execute(
                            f"ALTER TABLE chat_sessions ADD COLUMN {ddl}"
                        )
                connection.execute(_POSTGRES_MESSAGES_DDL)
                for statement in _POSTGRES_MESSAGES_INDEXES:
                    connection.execute(statement)
                connection.execute(_POSTGRES_TRACES_DDL)
                for statement in _POSTGRES_TRACES_INDEXES:
                    connection.execute(statement)
            self._ready = True
            self._migrate_payloads()

    def _migrate_payloads(self) -> None:
        with get_pool().connection() as connection:
            rows: Any = connection.execute(
                "SELECT session_id FROM chat_sessions "
                "WHERE payload IS NOT NULL AND payload <> '{}'::jsonb"
            ).fetchall()
        for row in rows:
            session_id = str(row["session_id"])
            try:
                with get_pool().connection() as connection:
                    payload_row: Any = connection.execute(
                        "SELECT payload FROM chat_sessions "
                        "WHERE session_id = %s",
                        (session_id,),
                    ).fetchone()
                    record = payload_row["payload"] if payload_row else None
                    if not isinstance(record, dict):
                        continue
                    count_row: Any = connection.execute(
                        "SELECT COUNT(*) AS total FROM chat_messages "
                        "WHERE session_id = %s",
                        (session_id,),
                    ).fetchone()
                    if count_row and int(count_row["total"]) > 0:
                        connection.execute(
                            "UPDATE chat_sessions SET payload = %s "
                            "WHERE session_id = %s",
                            (Jsonb({}), session_id),
                        )
                        continue
                    with connection.transaction():
                        self._migrate_record(
                            connection, session_id, record
                        )
                        connection.execute(
                            "UPDATE chat_sessions SET payload = %s "
                            "WHERE session_id = %s",
                            (Jsonb({}), session_id),
                        )
            except Exception as exc:
                logger.warning(
                    "迁移会话失败 session=%s：%s", session_id, exc
                )

    def _migrate_record(self, connection: Any, session_id: str, record: dict) -> None:
        updated_at = float(record.get("updated_at") or time.time())
        connection.execute(
            "UPDATE chat_sessions SET buyer_id = %s, human_mode = %s, "
            "created_at = %s, last_active_at = %s, updated_at = %s, "
            "pending_action = %s, version = 0 WHERE session_id = %s",
            (
                record.get("buyer_id"),
                bool(record.get("human_mode")),
                float(record.get("created_at") or updated_at),
                updated_at,
                updated_at,
                Jsonb(record.get("pending_action"))
                if record.get("pending_action")
                else None,
                session_id,
            ),
        )
        id_map: dict[Any, int] = {}
        for message in record.get("messages") or []:
            if not isinstance(message, dict):
                continue
            row = connection.execute(
                "INSERT INTO chat_messages "
                "(session_id, role, source, content, client_msg_id, "
                "created_at) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    session_id,
                    str(message.get("role") or "user"),
                    message.get("source"),
                    str(message.get("content") or ""),
                    message.get("client_msg_id"),
                    updated_at,
                ),
            ).fetchone()
            id_map[message.get("id")] = int(row["id"])
        for trace in record.get("traces") or []:
            if not isinstance(trace, dict):
                continue
            payload = dict(trace)
            old_user_id = payload.get("user_message_id")
            if old_user_id in id_map:
                payload["user_message_id"] = id_map[old_user_id]
            payload.pop("id", None)
            connection.execute(
                "INSERT INTO chat_traces "
                "(session_id, user_message_id, status, route, "
                "first_response_ms, payload, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    session_id,
                    payload.get("user_message_id"),
                    payload.get("status"),
                    payload.get("route"),
                    payload.get("first_response_ms"),
                    Jsonb(payload),
                    float(payload.get("started_at") or updated_at),
                ),
            )

    def create(self, session_id: str, buyer_id: str | None, now: float) -> None:
        with get_pool().connection() as connection:
            connection.execute(
                "INSERT INTO chat_sessions "
                "(session_id, buyer_id, status, human_mode, created_at, "
                "last_active_at, updated_at, version, payload) "
                "VALUES (%s, %s, 'active', FALSE, %s, %s, %s, 0, %s) "
                "ON CONFLICT (session_id) DO NOTHING",
                (session_id, buyer_id, now, now, now, Jsonb({})),
            )

    def _row_to_meta(self, row: Any) -> dict[str, Any]:
        return {
            "session_id": str(row["session_id"]),
            "buyer_id": row["buyer_id"],
            "status": str(row["status"] or "active"),
            "human_mode": bool(row["human_mode"]),
            "assigned_agent": row["assigned_agent"],
            "created_at": float(row["created_at"] or 0),
            "last_active_at": float(row["last_active_at"] or 0),
            "closed_at": row["closed_at"],
            "close_reason": row["close_reason"],
            "version": int(row["version"] or 0),
            "pending_action": _parse_pending(row["pending_action"]),
        }

    def get_meta(self, session_id: str) -> dict[str, Any] | None:
        with get_pool().connection() as connection:
            row: Any = connection.execute(
                "SELECT * FROM chat_sessions WHERE session_id = %s",
                (session_id,),
            ).fetchone()
        return self._row_to_meta(row) if row is not None else None

    def full_record(self, session_id: str) -> dict[str, Any] | None:
        meta = self.get_meta(session_id)
        if meta is None:
            return None
        with get_pool().connection() as connection:
            message_rows: Any = connection.execute(
                "SELECT id, role, source, content, created_at "
                "FROM chat_messages WHERE session_id = %s ORDER BY id",
                (session_id,),
            ).fetchall()
            trace_rows: Any = connection.execute(
                "SELECT id, payload FROM chat_traces "
                "WHERE session_id = %s ORDER BY id",
                (session_id,),
            ).fetchall()
        messages: list[dict[str, Any]] = [
            {
                "id": int(row["id"]),
                "role": str(row["role"]),
                "content": str(row["content"]),
                **({"source": str(row["source"])} if row["source"] else {}),
            }
            for row in message_rows
        ]
        traces: list[dict[str, Any]] = []
        for row in trace_rows:
            payload = row["payload"] or {}
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = {}
            payload = dict(payload)
            payload["id"] = int(row["id"])
            traces.append(payload)
        record = dict(meta)
        record["messages"] = messages
        record["traces"] = traces
        record["updated_at"] = meta["last_active_at"]
        record["next_message_id"] = (
            int(messages[-1]["id"]) + 1 if messages else 1
        )
        record["next_trace_id"] = int(traces[-1]["id"]) + 1 if traces else 1
        return record

    def list_meta(self) -> list[dict[str, Any]]:
        with get_pool().connection() as connection:
            rows: Any = connection.execute(
                "SELECT * FROM chat_sessions ORDER BY last_active_at ASC"
            ).fetchall()
        return [self._row_to_meta(row) for row in rows]

    def all_records(self) -> list[dict[str, Any]]:
        return [
            record
            for meta in self.list_meta()
            if (record := self.full_record(meta["session_id"])) is not None
        ]

    def append_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        source: str | None,
        client_msg_id: str | None,
        expected_version: int,
        now: float,
    ) -> tuple[int, int]:
        try:
            with get_pool().connection() as connection:
                with connection.transaction():
                    cursor: Any = connection.execute(
                        "UPDATE chat_sessions SET version = version + 1, "
                        "last_active_at = %s, updated_at = %s "
                        "WHERE session_id = %s AND version = %s",
                        (now, now, session_id, expected_version),
                    )
                    if cursor.rowcount == 0:
                        raise VersionConflict(session_id)
                    row: Any = connection.execute(
                        "INSERT INTO chat_messages "
                        "(session_id, role, source, content, client_msg_id, "
                        "created_at) VALUES (%s, %s, %s, %s, %s, %s) "
                        "RETURNING id",
                        (
                            session_id,
                            role,
                            source,
                            content,
                            client_msg_id,
                            now,
                        ),
                    ).fetchone()
                    return int(row["id"]), expected_version + 1
        except UniqueViolation as exc:
            raise DuplicateMessage(str(exc)) from exc

    def append_trace(
        self,
        session_id: str,
        trace: dict[str, Any],
        *,
        expected_version: int,
        now: float,
    ) -> tuple[int, int]:
        payload = dict(trace)
        payload.pop("id", None)
        with get_pool().connection() as connection:
            with connection.transaction():
                cursor = connection.execute(
                    "UPDATE chat_sessions SET version = version + 1, "
                    "last_active_at = %s, updated_at = %s "
                    "WHERE session_id = %s AND version = %s",
                    (now, now, session_id, expected_version),
                )
                if cursor.rowcount == 0:
                    raise VersionConflict(session_id)
                row: Any = connection.execute(
                    "INSERT INTO chat_traces "
                    "(session_id, user_message_id, status, route, "
                    "first_response_ms, payload, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (
                        session_id,
                        payload.get("user_message_id"),
                        payload.get("status"),
                        payload.get("route"),
                        payload.get("first_response_ms"),
                        Jsonb(payload),
                        float(payload.get("started_at") or now),
                    ),
                ).fetchone()
                return int(row["id"]), expected_version + 1

    def update_meta(
        self,
        session_id: str,
        changes: dict[str, Any],
        *,
        expected_version: int,
        now: float,
    ) -> int:
        sets: list[str] = []
        params: list[Any] = []
        for key, value in changes.items():
            if key not in _META_FIELDS:
                continue
            if key == "pending_action":
                value = Jsonb(value) if value is not None else None
            sets.append(f"{key} = %s")
            params.append(value)
        sets.extend(
            [
                "last_active_at = %s",
                "updated_at = %s",
                "version = version + 1",
            ]
        )
        params.extend([now, now, session_id, expected_version])
        sql = (
            f"UPDATE chat_sessions SET {', '.join(sets)} "
            "WHERE session_id = %s AND version = %s"
        )
        with get_pool().connection() as connection:
            cursor: Any = connection.execute(sql, params)
            if cursor.rowcount == 0:
                raise VersionConflict(session_id)
        return expected_version + 1

    def delete_older_than(self, cutoff: float) -> int:
        with get_pool().connection() as connection:
            with connection.transaction():
                connection.execute(
                    "DELETE FROM chat_messages WHERE session_id IN "
                    "(SELECT session_id FROM chat_sessions "
                    "WHERE last_active_at < %s)",
                    (cutoff,),
                )
                connection.execute(
                    "DELETE FROM chat_traces WHERE session_id IN "
                    "(SELECT session_id FROM chat_sessions "
                    "WHERE last_active_at < %s)",
                    (cutoff,),
                )
                cursor = connection.execute(
                    "DELETE FROM chat_sessions WHERE last_active_at < %s",
                    (cutoff,),
                )
                return int(cursor.rowcount)

    def clear(self) -> None:
        with get_pool().connection() as connection:
            with connection.transaction():
                connection.execute("DELETE FROM chat_messages")
                connection.execute("DELETE FROM chat_traces")
                connection.execute("DELETE FROM chat_sessions")


class AsyncThreadedSessionRepository:
    """Async facade over a sync repository with a dedicated thread pool.

    Used for SQLite (and as a Windows fallback) so session DB work never
    competes with the process-wide ``asyncio.to_thread`` executor.
    """

    def __init__(self, repository: Repository, max_workers: int):
        self._repository = repository
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="session-db",
        )
        logger.info(
            "会话仓库使用专用线程池 | workers=%d", max_workers
        )

    async def _run(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        call = functools.partial(func, *args, **kwargs)
        return await loop.run_in_executor(self._executor, call)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    async def ensure_schema(self) -> None:
        await self._run(self._repository.ensure_schema)

    async def create(
        self, session_id: str, buyer_id: str | None, now: float
    ) -> None:
        await self._run(self._repository.create, session_id, buyer_id, now)

    async def get_meta(self, session_id: str) -> dict[str, Any] | None:
        return await self._run(self._repository.get_meta, session_id)

    async def full_record(self, session_id: str) -> dict[str, Any] | None:
        return await self._run(self._repository.full_record, session_id)

    async def list_meta(self) -> list[dict[str, Any]]:
        return await self._run(self._repository.list_meta)

    async def all_records(self) -> list[dict[str, Any]]:
        return await self._run(self._repository.all_records)

    async def append_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        source: str | None,
        client_msg_id: str | None,
        expected_version: int,
        now: float,
    ) -> tuple[int, int]:
        return await self._run(
            self._repository.append_message,
            session_id,
            role=role,
            content=content,
            source=source,
            client_msg_id=client_msg_id,
            expected_version=expected_version,
            now=now,
        )

    async def append_trace(
        self,
        session_id: str,
        trace: dict[str, Any],
        *,
        expected_version: int,
        now: float,
    ) -> tuple[int, int]:
        return await self._run(
            self._repository.append_trace,
            session_id,
            trace,
            expected_version=expected_version,
            now=now,
        )

    async def update_meta(
        self,
        session_id: str,
        changes: dict[str, Any],
        *,
        expected_version: int,
        now: float,
    ) -> int:
        return await self._run(
            self._repository.update_meta,
            session_id,
            changes,
            expected_version=expected_version,
            now=now,
        )

    async def delete_older_than(self, cutoff: float) -> int:
        return await self._run(self._repository.delete_older_than, cutoff)

    async def clear(self) -> None:
        await self._run(self._repository.clear)


class AsyncPostgresSessionRepository:
    """Native async Postgres session repository.

    Uses its own ``AsyncConnectionPool`` so session traffic is isolated from
    the sync pool used by orders/audit.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._pool = AsyncConnectionPool(
            conninfo=settings.database_url,
            min_size=settings.session_db_pool_min_size,
            max_size=settings.session_db_pool_max_size,
            timeout=settings.session_db_pool_timeout,
            kwargs={"row_factory": dict_row, "autocommit": True},
            open=False,
        )
        self._opened = False
        self._open_lock = asyncio.Lock()

    async def _ensure_open(self) -> None:
        if self._opened:
            return
        async with self._open_lock:
            if self._opened:
                return
            settings = get_settings()
            await self._pool.open(
                wait=True, timeout=settings.session_db_pool_timeout
            )
            self._opened = True
            logger.info(
                "异步 Postgres 会话仓库已连接 | pool=%d",
                settings.session_db_pool_max_size,
            )

    async def close(self) -> None:
        if self._opened:
            await self._pool.close()
            self._opened = False

    async def ensure_schema(self) -> None:
        await self._ensure_open()
        async with self._pool.connection() as connection:
            await connection.execute(_POSTGRES_SESSIONS_DDL)
            cursor = await connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'chat_sessions'"
            )
            rows: Any = await cursor.fetchall()
            columns = {str(row["column_name"]) for row in rows}
            for name, ddl in _POSTGRES_ADD_COLUMNS:
                if name not in columns:
                    await connection.execute(
                        f"ALTER TABLE chat_sessions ADD COLUMN {ddl}"
                    )
            await connection.execute(_POSTGRES_MESSAGES_DDL)
            for statement in _POSTGRES_MESSAGES_INDEXES:
                await connection.execute(statement)
            await connection.execute(_POSTGRES_TRACES_DDL)
            for statement in _POSTGRES_TRACES_INDEXES:
                await connection.execute(statement)
        await self._migrate_payloads()

    async def _migrate_payloads(self) -> None:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT session_id FROM chat_sessions "
                "WHERE payload IS NOT NULL AND payload <> '{}'::jsonb"
            )
            rows: Any = await cursor.fetchall()
        for row in rows:
            session_id = str(row["session_id"])
            try:
                async with self._pool.connection() as connection:
                    cursor = await connection.execute(
                        "SELECT payload FROM chat_sessions "
                        "WHERE session_id = %s",
                        (session_id,),
                    )
                    payload_row: Any = await cursor.fetchone()
                    record = payload_row["payload"] if payload_row else None
                    if not isinstance(record, dict):
                        continue
                    cursor = await connection.execute(
                        "SELECT COUNT(*) AS total FROM chat_messages "
                        "WHERE session_id = %s",
                        (session_id,),
                    )
                    count_row: Any = await cursor.fetchone()
                    if count_row and int(count_row["total"]) > 0:
                        await connection.execute(
                            "UPDATE chat_sessions SET payload = %s "
                            "WHERE session_id = %s",
                            (Jsonb({}), session_id),
                        )
                        continue
                    async with connection.transaction():
                        await self._migrate_record(
                            connection, session_id, record
                        )
                        await connection.execute(
                            "UPDATE chat_sessions SET payload = %s "
                            "WHERE session_id = %s",
                            (Jsonb({}), session_id),
                        )
            except Exception as exc:
                logger.warning(
                    "迁移会话失败 session=%s：%s", session_id, exc
                )

    async def _migrate_record(
        self, connection: Any, session_id: str, record: dict
    ) -> None:
        updated_at = float(record.get("updated_at") or time.time())
        await connection.execute(
            "UPDATE chat_sessions SET buyer_id = %s, human_mode = %s, "
            "created_at = %s, last_active_at = %s, updated_at = %s, "
            "pending_action = %s, version = 0 WHERE session_id = %s",
            (
                record.get("buyer_id"),
                bool(record.get("human_mode")),
                float(record.get("created_at") or updated_at),
                updated_at,
                updated_at,
                Jsonb(record.get("pending_action"))
                if record.get("pending_action")
                else None,
                session_id,
            ),
        )
        id_map: dict[Any, int] = {}
        for message in record.get("messages") or []:
            if not isinstance(message, dict):
                continue
            cursor = await connection.execute(
                "INSERT INTO chat_messages "
                "(session_id, role, source, content, client_msg_id, "
                "created_at) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    session_id,
                    str(message.get("role") or "user"),
                    message.get("source"),
                    str(message.get("content") or ""),
                    message.get("client_msg_id"),
                    updated_at,
                ),
            )
            inserted = await cursor.fetchone()
            id_map[message.get("id")] = int(inserted["id"])
        for trace in record.get("traces") or []:
            if not isinstance(trace, dict):
                continue
            payload = dict(trace)
            old_user_id = payload.get("user_message_id")
            if old_user_id in id_map:
                payload["user_message_id"] = id_map[old_user_id]
            payload.pop("id", None)
            await connection.execute(
                "INSERT INTO chat_traces "
                "(session_id, user_message_id, status, route, "
                "first_response_ms, payload, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    session_id,
                    payload.get("user_message_id"),
                    payload.get("status"),
                    payload.get("route"),
                    payload.get("first_response_ms"),
                    Jsonb(payload),
                    float(payload.get("started_at") or updated_at),
                ),
            )

    async def create(
        self, session_id: str, buyer_id: str | None, now: float
    ) -> None:
        await self._ensure_open()
        async with self._pool.connection() as connection:
            await connection.execute(
                "INSERT INTO chat_sessions "
                "(session_id, buyer_id, status, human_mode, created_at, "
                "last_active_at, updated_at, version, payload) "
                "VALUES (%s, %s, 'active', FALSE, %s, %s, %s, 0, %s) "
                "ON CONFLICT (session_id) DO NOTHING",
                (session_id, buyer_id, now, now, now, Jsonb({})),
            )

    def _row_to_meta(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_id": str(row["session_id"]),
            "buyer_id": row["buyer_id"],
            "status": str(row["status"] or "active"),
            "human_mode": bool(row["human_mode"]),
            "assigned_agent": row["assigned_agent"],
            "created_at": float(row["created_at"] or 0),
            "last_active_at": float(row["last_active_at"] or 0),
            "closed_at": row["closed_at"],
            "close_reason": row["close_reason"],
            "version": int(row["version"] or 0),
            "pending_action": _parse_pending(row["pending_action"]),
        }

    async def get_meta(self, session_id: str) -> dict[str, Any] | None:
        await self._ensure_open()
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM chat_sessions WHERE session_id = %s",
                (session_id,),
            )
            row: Any = await cursor.fetchone()
        return self._row_to_meta(row) if row is not None else None

    async def full_record(self, session_id: str) -> dict[str, Any] | None:
        meta = await self.get_meta(session_id)
        if meta is None:
            return None
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT id, role, source, content, created_at "
                "FROM chat_messages WHERE session_id = %s ORDER BY id",
                (session_id,),
            )
            message_rows: Any = await cursor.fetchall()
            cursor = await connection.execute(
                "SELECT id, payload FROM chat_traces "
                "WHERE session_id = %s ORDER BY id",
                (session_id,),
            )
            trace_rows: Any = await cursor.fetchall()
        messages: list[dict[str, Any]] = [
            {
                "id": int(row["id"]),
                "role": str(row["role"]),
                "content": str(row["content"]),
                **({"source": str(row["source"])} if row["source"] else {}),
            }
            for row in message_rows
        ]
        traces: list[dict[str, Any]] = []
        for row in trace_rows:
            payload = row["payload"] or {}
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = {}
            payload = dict(payload)
            payload["id"] = int(row["id"])
            traces.append(payload)
        record = dict(meta)
        record["messages"] = messages
        record["traces"] = traces
        record["updated_at"] = meta["last_active_at"]
        record["next_message_id"] = (
            int(messages[-1]["id"]) + 1 if messages else 1
        )
        record["next_trace_id"] = int(traces[-1]["id"]) + 1 if traces else 1
        return record

    async def list_meta(self) -> list[dict[str, Any]]:
        await self._ensure_open()
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM chat_sessions ORDER BY last_active_at ASC"
            )
            rows: Any = await cursor.fetchall()
        return [self._row_to_meta(row) for row in rows]

    async def all_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for meta in await self.list_meta():
            record = await self.full_record(meta["session_id"])
            if record is not None:
                records.append(record)
        return records

    async def append_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        source: str | None,
        client_msg_id: str | None,
        expected_version: int,
        now: float,
    ) -> tuple[int, int]:
        await self._ensure_open()
        try:
            async with self._pool.connection() as connection:
                async with connection.transaction():
                    cursor = await connection.execute(
                        "UPDATE chat_sessions SET version = version + 1, "
                        "last_active_at = %s, updated_at = %s "
                        "WHERE session_id = %s AND version = %s",
                        (now, now, session_id, expected_version),
                    )
                    if cursor.rowcount == 0:
                        raise VersionConflict(session_id)
                    cursor = await connection.execute(
                        "INSERT INTO chat_messages "
                        "(session_id, role, source, content, client_msg_id, "
                        "created_at) VALUES (%s, %s, %s, %s, %s, %s) "
                        "RETURNING id",
                        (
                            session_id,
                            role,
                            source,
                            content,
                            client_msg_id,
                            now,
                        ),
                    )
                    inserted: Any = await cursor.fetchone()
                    return int(inserted["id"]), expected_version + 1
        except UniqueViolation as exc:
            raise DuplicateMessage(str(exc)) from exc

    async def append_trace(
        self,
        session_id: str,
        trace: dict[str, Any],
        *,
        expected_version: int,
        now: float,
    ) -> tuple[int, int]:
        payload = dict(trace)
        payload.pop("id", None)
        await self._ensure_open()
        async with self._pool.connection() as connection:
            async with connection.transaction():
                cursor = await connection.execute(
                    "UPDATE chat_sessions SET version = version + 1, "
                    "last_active_at = %s, updated_at = %s "
                    "WHERE session_id = %s AND version = %s",
                    (now, now, session_id, expected_version),
                )
                if cursor.rowcount == 0:
                    raise VersionConflict(session_id)
                cursor = await connection.execute(
                    "INSERT INTO chat_traces "
                    "(session_id, user_message_id, status, route, "
                    "first_response_ms, payload, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (
                        session_id,
                        payload.get("user_message_id"),
                        payload.get("status"),
                        payload.get("route"),
                        payload.get("first_response_ms"),
                        Jsonb(payload),
                        float(payload.get("started_at") or now),
                    ),
                )
                inserted: Any = await cursor.fetchone()
                return int(inserted["id"]), expected_version + 1

    async def update_meta(
        self,
        session_id: str,
        changes: dict[str, Any],
        *,
        expected_version: int,
        now: float,
    ) -> int:
        sets: list[str] = []
        params: list[Any] = []
        for key, value in changes.items():
            if key not in _META_FIELDS:
                continue
            if key == "pending_action":
                value = Jsonb(value) if value is not None else None
            sets.append(f"{key} = %s")
            params.append(value)
        sets.extend(
            [
                "last_active_at = %s",
                "updated_at = %s",
                "version = version + 1",
            ]
        )
        params.extend([now, now, session_id, expected_version])
        sql = (
            f"UPDATE chat_sessions SET {', '.join(sets)} "
            "WHERE session_id = %s AND version = %s"
        )
        await self._ensure_open()
        async with self._pool.connection() as connection:
            cursor = await connection.execute(sql, params)
            if cursor.rowcount == 0:
                raise VersionConflict(session_id)
        return expected_version + 1

    async def delete_older_than(self, cutoff: float) -> int:
        await self._ensure_open()
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await connection.execute(
                    "DELETE FROM chat_messages WHERE session_id IN "
                    "(SELECT session_id FROM chat_sessions "
                    "WHERE last_active_at < %s)",
                    (cutoff,),
                )
                await connection.execute(
                    "DELETE FROM chat_traces WHERE session_id IN "
                    "(SELECT session_id FROM chat_sessions "
                    "WHERE last_active_at < %s)",
                    (cutoff,),
                )
                cursor = await connection.execute(
                    "DELETE FROM chat_sessions WHERE last_active_at < %s",
                    (cutoff,),
                )
                return int(cursor.rowcount)

    async def clear(self) -> None:
        await self._ensure_open()
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await connection.execute("DELETE FROM chat_messages")
                await connection.execute("DELETE FROM chat_traces")
                await connection.execute("DELETE FROM chat_sessions")


Repository = SqliteSessionRepository | PostgresSessionRepository

_repository: Repository | None = None
_repository_lock = threading.Lock()


def get_repository() -> Repository | None:
    global _repository
    settings = get_settings()
    if not settings.session_persistence:
        return None
    mode = (settings.session_storage_mode or "normalized").strip().lower()
    if mode != "normalized":
        return None
    with _repository_lock:
        if _repository is not None:
            return _repository
        backend = (settings.session_store_backend or "sqlite").strip().lower()
        repository: Repository
        if backend == "postgres":
            candidate: Repository = PostgresSessionRepository()
            try:
                candidate.ensure_schema()
            except Exception as exc:
                logger.warning(
                    "Postgres 会话仓库不可用，回退 SQLite：%s", exc
                )
                candidate = SqliteSessionRepository(_sqlite_path())
                candidate.ensure_schema()
            repository = candidate
        else:
            repository = SqliteSessionRepository(_sqlite_path())
            repository.ensure_schema()
        _repository = repository
        return repository


def reset_repository() -> None:
    global _repository
    with _repository_lock:
        _repository = None
    reset_async_repositories()


def ensure_schema() -> None:
    repository = get_repository()
    if repository is not None:
        repository.ensure_schema()


AsyncRepository = (
    AsyncThreadedSessionRepository | AsyncPostgresSessionRepository
)

_async_repositories: dict[int, AsyncPostgresSessionRepository] = {}
_async_repo_locks: dict[int, asyncio.Lock] = {}
_async_threaded: AsyncThreadedSessionRepository | None = None
_async_threaded_lock = threading.Lock()


async def get_async_repository() -> AsyncRepository | None:
    settings = get_settings()
    if not settings.session_persistence:
        return None
    mode = (settings.session_storage_mode or "normalized").strip().lower()
    if mode != "normalized":
        return None
    backend = (settings.session_store_backend or "sqlite").strip().lower()
    if backend == "postgres":
        running_loop = asyncio.get_running_loop()
        is_proactor = (
            sys.platform == "win32"
            and type(running_loop).__name__ == "ProactorEventLoop"
        )
        if is_proactor:
            logger.warning(
                "Windows ProactorEventLoop 不支持异步 psycopg，"
                "会话库回退到专用线程池"
            )
        else:
            key = id(running_loop)
            repository = _async_repositories.get(key)
            if repository is not None:
                return repository
            lock = _async_repo_locks.setdefault(key, asyncio.Lock())
            async with lock:
                repository = _async_repositories.get(key)
                if repository is None:
                    candidate = AsyncPostgresSessionRepository()
                    await candidate.ensure_schema()
                    repository = candidate
                    _async_repositories[key] = repository
                return repository

    global _async_threaded
    threaded_repository = _async_threaded
    if threaded_repository is not None:
        return threaded_repository
    with _async_threaded_lock:
        if _async_threaded is None:
            sync_repository = get_repository()
            if sync_repository is None:
                return None
            _async_threaded = AsyncThreadedSessionRepository(
                sync_repository, settings.session_sqlite_workers
            )
        return _async_threaded


def reset_async_repositories() -> None:
    global _async_threaded
    _async_repositories.clear()
    _async_repo_locks.clear()
    with _async_threaded_lock:
        if _async_threaded is not None:
            _async_threaded.close()
        _async_threaded = None


async def close_async_repositories() -> None:
    global _async_threaded
    for repository in list(_async_repositories.values()):
        try:
            await repository.close()
        except Exception as exc:
            logger.warning("关闭异步会话仓库失败：%s", exc)
    _async_repositories.clear()
    _async_repo_locks.clear()
    with _async_threaded_lock:
        if _async_threaded is not None:
            _async_threaded.close()
        _async_threaded = None


async def ensure_async_schema() -> None:
    repository = await get_async_repository()
    if repository is not None:
        await repository.ensure_schema()
