from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from core.cache import get_redis, redis_enabled
from core.config import BASE_DIR, get_settings
from core.db import get_pool

logger = logging.getLogger("ecommerce_agent.session_store")

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at REAL NOT NULL
)
"""

_POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated
    ON chat_sessions (updated_at DESC);
"""

_INDEX_KEY = "sessions:index"


def _parse_record(payload: Any) -> dict[str, Any] | None:
    if not payload:
        return None
    try:
        record = json.loads(payload) if isinstance(payload, str) else payload
    except (TypeError, json.JSONDecodeError):
        logger.warning("跳过损坏的会话记录")
        return None
    if isinstance(record, dict) and record.get("session_id"):
        return record
    return None


def _sqlite_path() -> Path:
    path = Path(get_settings().session_db_path)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


class SessionStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._connection: sqlite3.Connection | None = None
        self._failed = False

    def _connect(self) -> sqlite3.Connection | None:
        if self._failed:
            return None
        if self._connection is not None:
            return self._connection
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(
                str(self.path), check_same_thread=False, timeout=10
            )
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(_SQLITE_SCHEMA)
            connection.commit()
        except Exception as exc:
            logger.warning("会话持久化不可用，回退到内存：%s", exc)
            self._failed = True
            return None
        self._connection = connection
        return connection

    def save(self, record: dict[str, Any]) -> None:
        payload = json.dumps(record, ensure_ascii=False)
        with self._lock:
            connection = self._connect()
            if connection is None:
                return
            try:
                connection.execute(
                    "INSERT INTO chat_sessions (session_id, payload, updated_at) "
                    "VALUES (?, ?, ?) "
                    "ON CONFLICT(session_id) DO UPDATE SET "
                    "payload = excluded.payload, updated_at = excluded.updated_at",
                    (
                        str(record["session_id"]),
                        payload,
                        float(record.get("updated_at") or 0),
                    ),
                )
                connection.commit()
            except Exception as exc:
                logger.warning(
                    "保存会话失败 session=%s：%s", record.get("session_id"), exc
                )

    def load_one(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            connection = self._connect()
            if connection is None:
                return None
            try:
                row = connection.execute(
                    "SELECT payload FROM chat_sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            except Exception as exc:
                logger.warning("读取会话失败：%s", exc)
                return None
        return _parse_record(row[0]) if row else None

    def load_all(self) -> list[dict[str, Any]]:
        with self._lock:
            connection = self._connect()
            if connection is None:
                return []
            try:
                rows = connection.execute(
                    "SELECT payload FROM chat_sessions ORDER BY updated_at ASC"
                ).fetchall()
            except Exception as exc:
                logger.warning("读取会话失败：%s", exc)
                return []
        records: list[dict[str, Any]] = []
        for (payload,) in rows:
            record = _parse_record(payload)
            if record is not None:
                records.append(record)
        return records

    def clear(self) -> None:
        with self._lock:
            connection = self._connect()
            if connection is None:
                return
            connection.execute("DELETE FROM chat_sessions")
            connection.commit()

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None


class PostgresSessionStore:
    def __init__(self) -> None:
        self._ready = False
        self._lock = threading.Lock()

    def ensure_schema(self) -> None:
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            pool = get_pool()
            with pool.connection() as connection:
                for statement in _POSTGRES_SCHEMA.split(";"):
                    statement = statement.strip()
                    if statement:
                        connection.execute(statement)
            self._ready = True

    def save(self, record: dict[str, Any]) -> None:
        self.ensure_schema()
        pool = get_pool()
        try:
            with pool.connection() as connection:
                connection.execute(
                    "INSERT INTO chat_sessions (session_id, payload, updated_at) "
                    "VALUES (%s, %s, %s) "
                    "ON CONFLICT (session_id) DO UPDATE SET "
                    "payload = EXCLUDED.payload, updated_at = EXCLUDED.updated_at",
                    (
                        str(record["session_id"]),
                        Jsonb(record),
                        float(record.get("updated_at") or 0),
                    ),
                )
        except Exception as exc:
            logger.warning(
                "Postgres 保存会话失败 session=%s：%s",
                record.get("session_id"),
                exc,
            )

    def load_one(self, session_id: str) -> dict[str, Any] | None:
        self.ensure_schema()
        try:
            with get_pool().connection() as connection:
                row: Any = connection.execute(
                    "SELECT payload FROM chat_sessions WHERE session_id = %s",
                    (session_id,),
                ).fetchone()
        except Exception as exc:
            logger.warning("Postgres 读取会话失败：%s", exc)
            return None
        return _parse_record(row["payload"]) if row else None

    def load_all(self) -> list[dict[str, Any]]:
        self.ensure_schema()
        try:
            with get_pool().connection() as connection:
                rows: Any = connection.execute(
                    "SELECT payload FROM chat_sessions ORDER BY updated_at ASC"
                ).fetchall()
        except Exception as exc:
            logger.warning("Postgres 读取会话列表失败：%s", exc)
            return []
        records: list[dict[str, Any]] = []
        for row in rows:
            record = _parse_record(row["payload"])
            if record is not None:
                records.append(record)
        return records

    def clear(self) -> None:
        self.ensure_schema()
        try:
            with get_pool().connection() as connection:
                connection.execute("DELETE FROM chat_sessions")
        except Exception as exc:
            logger.warning("Postgres 清空会话失败：%s", exc)


class RedisSessionStore:
    def __init__(self, client: Any, ttl_seconds: int):
        self.client = client
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _key(session_id: str) -> str:
        return f"session:{session_id}"

    def save(self, record: dict[str, Any]) -> None:
        session_id = str(record["session_id"])
        try:
            pipe = self.client.pipeline()
            pipe.set(
                self._key(session_id),
                json.dumps(record, ensure_ascii=False),
                ex=self.ttl_seconds,
            )
            pipe.zadd(
                _INDEX_KEY,
                {session_id: float(record.get("updated_at") or 0)},
            )
            pipe.expire(_INDEX_KEY, self.ttl_seconds)
            pipe.execute()
        except Exception as exc:
            logger.warning("Redis 保存会话失败 session=%s：%s", session_id, exc)

    def load_one(self, session_id: str) -> dict[str, Any] | None:
        try:
            payload = self.client.get(self._key(session_id))
        except Exception as exc:
            logger.warning("Redis 读取会话失败：%s", exc)
            return None
        return _parse_record(payload)

    def load_all(self) -> list[dict[str, Any]]:
        try:
            session_ids = self.client.zrange(_INDEX_KEY, 0, -1)
            if not session_ids:
                return []
            payloads = self.client.mget(
                [self._key(str(session_id)) for session_id in session_ids]
            )
        except Exception as exc:
            logger.warning("Redis 读取会话列表失败：%s", exc)
            return []
        records: list[dict[str, Any]] = []
        for payload in payloads:
            record = _parse_record(payload)
            if record is not None:
                records.append(record)
        return records

    def clear(self) -> None:
        try:
            session_ids = self.client.zrange(_INDEX_KEY, 0, -1)
            if session_ids:
                self.client.delete(
                    *[self._key(str(session_id)) for session_id in session_ids]
                )
            self.client.delete(_INDEX_KEY)
        except Exception as exc:
            logger.warning("Redis 清空会话失败：%s", exc)


class CompositeSessionStore:
    def __init__(self, hot: RedisSessionStore, durable: Any):
        self.hot = hot
        self.durable = durable

    def save(self, record: dict[str, Any]) -> None:
        self.durable.save(record)
        self.hot.save(record)

    def load_one(self, session_id: str) -> dict[str, Any] | None:
        record = self.hot.load_one(session_id)
        if record is not None:
            return record
        record = self.durable.load_one(session_id)
        if record is not None:
            self.hot.save(record)
        return record

    def load_all(self) -> list[dict[str, Any]]:
        return self.durable.load_all()

    def clear(self) -> None:
        self.durable.clear()
        self.hot.clear()


_Store = SessionStore | PostgresSessionStore | RedisSessionStore | CompositeSessionStore
_store: _Store | None = None
_store_lock = threading.Lock()


def get_store() -> _Store | None:
    global _store
    settings = get_settings()
    with _store_lock:
        if _store is not None:
            return _store

        durable: SessionStore | PostgresSessionStore | None = None
        if settings.session_persistence:
            backend = (settings.session_store_backend or "sqlite").strip().lower()
            if backend == "postgres":
                candidate = PostgresSessionStore()
                try:
                    candidate.ensure_schema()
                except Exception as exc:
                    logger.warning(
                        "Postgres 会话存储不可用，回退 SQLite：%s", exc
                    )
                    durable = SessionStore(_sqlite_path())
                else:
                    durable = candidate
            else:
                durable = SessionStore(_sqlite_path())

        hot: RedisSessionStore | None = None
        if redis_enabled():
            client = get_redis()
            if client is not None:
                hot = RedisSessionStore(client, settings.session_ttl_seconds)

        if hot is not None and durable is not None:
            _store = CompositeSessionStore(hot, durable)
        elif hot is not None:
            _store = hot
        else:
            _store = durable
        return _store


def reset_store() -> None:
    global _store
    with _store_lock:
        _store = None


def is_shared_store() -> bool:
    return isinstance(
        get_store(), (RedisSessionStore, PostgresSessionStore, CompositeSessionStore)
    )


def save_record(record: dict[str, Any]) -> None:
    store = get_store()
    if store is not None:
        store.save(record)


def load_record(session_id: str) -> dict[str, Any] | None:
    store = get_store()
    if store is None:
        return None
    return store.load_one(session_id)


def load_records() -> list[dict[str, Any]]:
    store = get_store()
    if store is None:
        return []
    return store.load_all()


def clear_records() -> None:
    store = get_store()
    if store is not None:
        store.clear()
