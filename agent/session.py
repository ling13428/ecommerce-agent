from __future__ import annotations

import asyncio
import copy
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from agent.session_repo import get_async_repository
from agent.session_store import (
    append_message_record,
    append_trace_record,
    async_append_message_record,
    async_append_trace_record,
    async_cache_record,
    async_create_session_record,
    async_delete_cached_record,
    async_load_record,
    async_load_records,
    async_update_session_meta,
    cache_record,
    clear_records,
    create_session_record,
    delete_cached_record,
    has_repository,
    is_shared_store,
    load_record,
    load_records,
    save_record,
    update_session_meta,
)
from core.config import get_settings

logger = logging.getLogger("ecommerce_agent.session")


@dataclass
class PendingAction:
    name: str
    args: dict[str, Any]
    summary: str
    idempotency_key: str = field(default_factory=lambda: uuid4().hex)


@dataclass
class SessionState:
    session_id: str
    max_messages: int | None = None
    max_traces: int | None = None
    context_messages: int = 20
    messages: list[dict[str, Any]] = field(default_factory=list)
    traces: list[dict[str, Any]] = field(default_factory=list)
    pending_action: PendingAction | None = None
    human_mode: bool = False
    buyer_id: str | None = None
    status: str = "active"
    assigned_agent: str | None = None
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)
    closed_at: float | None = None
    close_reason: str | None = None
    version: int = 0
    updated_at: float = field(default_factory=time.time)
    next_message_id: int = 1
    next_trace_id: int = 1

    def to_record(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "max_messages": self.max_messages,
            "max_traces": self.max_traces,
            "context_messages": self.context_messages,
            "messages": copy.deepcopy(self.messages),
            "traces": copy.deepcopy(self.traces),
            "pending_action": (
                {
                    "name": self.pending_action.name,
                    "args": copy.deepcopy(self.pending_action.args),
                    "summary": self.pending_action.summary,
                    "idempotency_key": self.pending_action.idempotency_key,
                }
                if self.pending_action is not None
                else None
            ),
            "human_mode": self.human_mode,
            "buyer_id": self.buyer_id,
            "status": self.status,
            "assigned_agent": self.assigned_agent,
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
            "closed_at": self.closed_at,
            "close_reason": self.close_reason,
            "version": self.version,
            "updated_at": self.updated_at,
            "next_message_id": self.next_message_id,
            "next_trace_id": self.next_trace_id,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "SessionState":
        pending = record.get("pending_action")
        pending_action = None
        if isinstance(pending, dict):
            pending_action = PendingAction(
                name=str(pending.get("name", "")),
                args=dict(pending.get("args") or {}),
                summary=str(pending.get("summary") or ""),
                idempotency_key=str(
                    pending.get("idempotency_key") or uuid4().hex
                ),
            )
        created_at = float(record.get("created_at") or 0)
        last_active_at = float(
            record.get("last_active_at")
            or record.get("updated_at")
            or time.time()
        )
        return cls(
            session_id=str(record["session_id"]),
            max_messages=record.get("max_messages"),
            max_traces=record.get("max_traces"),
            context_messages=int(record.get("context_messages") or 20),
            messages=list(record.get("messages") or []),
            traces=list(record.get("traces") or []),
            pending_action=pending_action,
            human_mode=bool(record.get("human_mode", False)),
            buyer_id=(
                str(record["buyer_id"]).strip()
                if record.get("buyer_id")
                else None
            ),
            status=str(record.get("status") or "active"),
            assigned_agent=record.get("assigned_agent"),
            created_at=created_at or last_active_at,
            last_active_at=last_active_at,
            closed_at=record.get("closed_at"),
            close_reason=record.get("close_reason"),
            version=int(record.get("version") or 0),
            updated_at=float(
                record.get("updated_at") or last_active_at or time.time()
            ),
            next_message_id=int(record.get("next_message_id") or 1),
            next_trace_id=int(record.get("next_trace_id") or 1),
        )

    def _persist(self) -> None:
        if has_repository():
            cache_record(self.to_record())
        else:
            save_record(self.to_record())

    def add_message(
        self,
        role: str,
        content: str,
        *,
        source: str | None = None,
        client_msg_id: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        message: dict[str, Any] = {
            "id": self.next_message_id,
            "role": role,
            "content": content,
        }
        if source:
            message["source"] = source
        appended = append_message_record(
            self.session_id,
            role=role,
            content=content,
            source=source,
            client_msg_id=client_msg_id,
            expected_version=self.version,
            now=now,
        )
        if appended is not None:
            row_id, new_version = appended
            message["id"] = row_id
            self.version = new_version
            self.next_message_id = max(self.next_message_id, row_id + 1)
        else:
            self.next_message_id += 1
        self.messages.append(message)
        if self.max_messages is not None and len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages :]
        self.updated_at = now
        self.last_active_at = now
        self._persist()
        return message

    def add_user(
        self, content: str, *, client_msg_id: str | None = None
    ) -> dict[str, Any]:
        return self.add_message(
            "user", content, client_msg_id=client_msg_id
        )

    def add_assistant(
        self,
        content: str,
        *,
        source: str | None = None,
        client_msg_id: str | None = None,
    ) -> None:
        if content.strip():
            self.add_message(
                "assistant",
                content,
                source=source,
                client_msg_id=client_msg_id,
            )

    def add_system(self, content: str) -> None:
        self.add_message("system", content)

    def snapshot(self) -> list[dict[str, Any]]:
        messages = self.messages
        if self.context_messages and len(messages) > self.context_messages:
            messages = messages[-self.context_messages :]
        return [
            {"role": message["role"], "content": message["content"]}
            for message in messages
        ]

    def public_messages(
        self, *, after_id: int = 0, human_only: bool = False
    ) -> list[dict[str, Any]]:
        result = []
        for message in self.messages:
            if message["role"] == "system":
                continue
            if after_id and message["id"] <= after_id:
                continue
            if human_only and message.get("source") != "human":
                continue
            result.append(dict(message))
        return result

    def last_user_message(self) -> str:
        for message in reversed(self.messages):
            if message["role"] == "user":
                return str(message["content"])
        return ""

    def add_trace(self, trace: dict[str, Any]) -> dict[str, Any]:
        record = copy.deepcopy(trace)
        now = time.time()
        appended = append_trace_record(
            self.session_id,
            record,
            expected_version=self.version,
            now=now,
        )
        if appended is not None:
            row_id, new_version = appended
            record["id"] = row_id
            self.version = new_version
            self.next_trace_id = max(self.next_trace_id, row_id + 1)
        else:
            record["id"] = self.next_trace_id
            self.next_trace_id += 1
        self.traces.append(record)
        if self.max_traces is not None and len(self.traces) > self.max_traces:
            self.traces = self.traces[-self.max_traces :]
        self.updated_at = now
        self.last_active_at = now
        self._persist()
        return record

    def public_traces(
        self, *, after_id: int = 0, limit: int | None = None
    ) -> list[dict[str, Any]]:
        traces = [
            copy.deepcopy(trace)
            for trace in self.traces
            if trace["id"] > after_id
        ]
        if limit is not None and limit > 0:
            traces = traces[-limit:]
        return traces

    def _update_meta(self, changes: dict[str, Any]) -> None:
        now = time.time()
        self.updated_at = now
        self.last_active_at = now
        new_version = update_session_meta(
            self.session_id,
            changes,
            expected_version=self.version,
            now=now,
        )
        if new_version is not None:
            self.version = new_version
        self._persist()

    def set_human_mode(self, enabled: bool) -> None:
        if self.human_mode == enabled:
            return
        self.human_mode = enabled
        changes: dict[str, Any] = {"human_mode": enabled}
        if self.status != "closed":
            self.status = "handed_off" if enabled else "active"
            changes["status"] = self.status
        self._update_meta(changes)

    def set_buyer_id(self, buyer_id: str | None) -> None:
        normalized = (buyer_id or "").strip().upper() or None
        if self.buyer_id == normalized:
            return
        self.buyer_id = normalized
        self._update_meta({"buyer_id": normalized})

    def set_pending(
        self,
        name: str,
        args: dict[str, Any],
        summary: str,
        *,
        idempotency_key: str | None = None,
    ) -> None:
        self.pending_action = PendingAction(
            name=name,
            args=args,
            summary=summary,
            idempotency_key=idempotency_key or uuid4().hex,
        )
        self._update_meta(
            {
                "pending_action": {
                    "name": self.pending_action.name,
                    "args": self.pending_action.args,
                    "summary": self.pending_action.summary,
                    "idempotency_key": self.pending_action.idempotency_key,
                }
            }
        )

    def pop_pending(self) -> PendingAction | None:
        pending = self.pending_action
        if pending is None:
            return None
        self.pending_action = None
        self._update_meta({"pending_action": None})
        return pending

    def clear_pending(self) -> None:
        if self.pending_action is None:
            return
        self.pending_action = None
        self._update_meta({"pending_action": None})

    def close(self, reason: str) -> None:
        if self.status == "closed":
            return
        now = time.time()
        self.status = "closed"
        self.closed_at = now
        self.close_reason = reason
        self._update_meta(
            {
                "status": "closed",
                "closed_at": now,
                "close_reason": reason,
            }
        )

    async def _persist_async(self) -> None:
        if await get_async_repository() is not None:
            await async_cache_record(self.to_record())
        else:
            await asyncio.to_thread(save_record, self.to_record())

    async def add_message_async(
        self,
        role: str,
        content: str,
        *,
        source: str | None = None,
        client_msg_id: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        message: dict[str, Any] = {
            "id": self.next_message_id,
            "role": role,
            "content": content,
        }
        if source:
            message["source"] = source
        appended = await async_append_message_record(
            self.session_id,
            role=role,
            content=content,
            source=source,
            client_msg_id=client_msg_id,
            expected_version=self.version,
            now=now,
        )
        if appended is not None:
            row_id, new_version = appended
            message["id"] = row_id
            self.version = new_version
            self.next_message_id = max(self.next_message_id, row_id + 1)
        else:
            self.next_message_id += 1
        self.messages.append(message)
        if self.max_messages is not None and len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages :]
        self.updated_at = now
        self.last_active_at = now
        await self._persist_async()
        return message

    async def add_user_async(
        self, content: str, *, client_msg_id: str | None = None
    ) -> dict[str, Any]:
        return await self.add_message_async(
            "user", content, client_msg_id=client_msg_id
        )

    async def add_assistant_async(
        self,
        content: str,
        *,
        source: str | None = None,
        client_msg_id: str | None = None,
    ) -> None:
        if content.strip():
            await self.add_message_async(
                "assistant",
                content,
                source=source,
                client_msg_id=client_msg_id,
            )

    async def add_system_async(self, content: str) -> None:
        await self.add_message_async("system", content)

    async def add_trace_async(self, trace: dict[str, Any]) -> dict[str, Any]:
        record = copy.deepcopy(trace)
        now = time.time()
        appended = await async_append_trace_record(
            self.session_id,
            record,
            expected_version=self.version,
            now=now,
        )
        if appended is not None:
            row_id, new_version = appended
            record["id"] = row_id
            self.version = new_version
            self.next_trace_id = max(self.next_trace_id, row_id + 1)
        else:
            record["id"] = self.next_trace_id
            self.next_trace_id += 1
        self.traces.append(record)
        if self.max_traces is not None and len(self.traces) > self.max_traces:
            self.traces = self.traces[-self.max_traces :]
        self.updated_at = now
        self.last_active_at = now
        await self._persist_async()
        return record

    async def _update_meta_async(self, changes: dict[str, Any]) -> None:
        now = time.time()
        self.updated_at = now
        self.last_active_at = now
        new_version = await async_update_session_meta(
            self.session_id,
            changes,
            expected_version=self.version,
            now=now,
        )
        if new_version is not None:
            self.version = new_version
        await self._persist_async()

    async def set_human_mode_async(self, enabled: bool) -> None:
        if self.human_mode == enabled:
            return
        self.human_mode = enabled
        changes: dict[str, Any] = {"human_mode": enabled}
        if self.status != "closed":
            self.status = "handed_off" if enabled else "active"
            changes["status"] = self.status
        await self._update_meta_async(changes)

    async def set_buyer_id_async(self, buyer_id: str | None) -> None:
        normalized = (buyer_id or "").strip().upper() or None
        if self.buyer_id == normalized:
            return
        self.buyer_id = normalized
        await self._update_meta_async({"buyer_id": normalized})

    async def set_pending_async(
        self,
        name: str,
        args: dict[str, Any],
        summary: str,
        *,
        idempotency_key: str | None = None,
    ) -> None:
        self.pending_action = PendingAction(
            name=name,
            args=args,
            summary=summary,
            idempotency_key=idempotency_key or uuid4().hex,
        )
        await self._update_meta_async(
            {
                "pending_action": {
                    "name": self.pending_action.name,
                    "args": self.pending_action.args,
                    "summary": self.pending_action.summary,
                    "idempotency_key": self.pending_action.idempotency_key,
                }
            }
        )

    async def pop_pending_async(self) -> PendingAction | None:
        pending = self.pending_action
        if pending is None:
            return None
        self.pending_action = None
        await self._update_meta_async({"pending_action": None})
        return pending

    async def clear_pending_async(self) -> None:
        if self.pending_action is None:
            return
        self.pending_action = None
        await self._update_meta_async({"pending_action": None})

    async def close_async(self, reason: str) -> None:
        if self.status == "closed":
            return
        now = time.time()
        self.status = "closed"
        self.closed_at = now
        self.close_reason = reason
        await self._update_meta_async(
            {
                "status": "closed",
                "closed_at": now,
                "close_reason": reason,
            }
        )


_sessions: dict[str, SessionState] = {}
_sessions_lock = threading.Lock()
_loaded = False


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    with _sessions_lock:
        if _loaded:
            return
        if is_shared_store():
            _loaded = True
            return
        records = load_records()
        for record in records:
            try:
                session = SessionState.from_record(record)
            except Exception as exc:
                logger.warning(
                    "跳过无法恢复的会话 %s：%s",
                    record.get("session_id"),
                    exc,
                )
                continue
            _sessions.setdefault(session.session_id, session)
        _loaded = True
        if records:
            logger.info("已加载 %d 个持久化会话", len(records))


def _refresh_session(session_id: str) -> None:
    record = load_record(session_id)
    if record is None:
        return
    try:
        session = SessionState.from_record(record)
    except Exception as exc:
        logger.warning("跳过无法恢复的会话 %s：%s", session_id, exc)
        return
    with _sessions_lock:
        _sessions[session_id] = session


def _refresh_all() -> None:
    for record in load_records():
        try:
            session = SessionState.from_record(record)
        except Exception as exc:
            logger.warning(
                "跳过无法恢复的会话 %s：%s",
                record.get("session_id"),
                exc,
            )
            continue
        with _sessions_lock:
            _sessions[session.session_id] = session


def load_persisted_sessions() -> int:
    _ensure_loaded()
    settings = get_settings()
    normalized = (
        settings.session_persistence
        and (settings.session_storage_mode or "normalized").strip().lower()
        == "normalized"
    )
    if is_shared_store() and not normalized:
        _refresh_all()
    with _sessions_lock:
        return len(_sessions)


def get_session(session_id: str) -> SessionState:
    _ensure_loaded()
    if is_shared_store():
        _refresh_session(session_id)
    now = time.time()
    with _sessions_lock:
        session = _sessions.get(session_id)
        if session is not None:
            session.updated_at = now
            return session
    session = SessionState(
        session_id=session_id,
        created_at=now,
        last_active_at=now,
        updated_at=now,
    )
    if has_repository():
        create_session_record(session_id, None, now)
    else:
        save_record(session.to_record())
    with _sessions_lock:
        existing = _sessions.setdefault(session_id, session)
        return existing


def get_existing_session(session_id: str) -> SessionState | None:
    _ensure_loaded()
    if is_shared_store():
        _refresh_session(session_id)
    with _sessions_lock:
        return _sessions.get(session_id)


def all_sessions() -> list[SessionState]:
    _ensure_loaded()
    if is_shared_store():
        _refresh_all()
    with _sessions_lock:
        return list(_sessions.values())


def _build_session_listing() -> list[dict[str, Any]]:
    with _sessions_lock:
        sessions = sorted(
            _sessions.values(), key=lambda item: item.updated_at, reverse=True
        )
        result = []
        for session in sessions:
            visible = [
                message
                for message in session.messages
                if message["role"] != "system"
            ]
            if not visible:
                continue
            result.append(
                {
                    "session_id": session.session_id,
                    "updated_at": session.updated_at,
                    "human_mode": session.human_mode,
                    "buyer_id": session.buyer_id,
                    "status": session.status,
                    "pending_action": (
                        session.pending_action.name
                        if session.pending_action is not None
                        else None
                    ),
                    "message_count": len(visible),
                    "trace_count": len(session.traces),
                    "last_message": visible[-1]["content"][:120],
                    "last_role": visible[-1]["role"],
                    "last_user_message": session.last_user_message()[:120],
                }
            )
        return result


def list_sessions() -> list[dict[str, Any]]:
    _ensure_loaded()
    if is_shared_store():
        _refresh_all()
    return _build_session_listing()


def is_session_expired(
    last_active_at: float, status: str, idle_seconds: float, now: float
) -> bool:
    if (status or "active").strip().lower() == "closed":
        return True
    return now - float(last_active_at or 0) > idle_seconds


def invalidate_session(session_id: str) -> None:
    with _sessions_lock:
        _sessions.pop(session_id, None)
    delete_cached_record(session_id)


async def invalidate_session_async(session_id: str) -> None:
    with _sessions_lock:
        _sessions.pop(session_id, None)
    await async_delete_cached_record(session_id)


async def _refresh_session_async(session_id: str) -> None:
    record = await async_load_record(session_id)
    if record is None:
        return
    try:
        session = SessionState.from_record(record)
    except Exception as exc:
        logger.warning("跳过无法恢复的会话 %s：%s", session_id, exc)
        return
    with _sessions_lock:
        _sessions[session_id] = session


async def _refresh_all_async() -> None:
    for record in await async_load_records():
        try:
            session = SessionState.from_record(record)
        except Exception as exc:
            logger.warning(
                "跳过无法恢复的会话 %s：%s",
                record.get("session_id"),
                exc,
            )
            continue
        with _sessions_lock:
            _sessions[session.session_id] = session


async def get_session_async(session_id: str) -> SessionState:
    _ensure_loaded()
    if is_shared_store():
        await _refresh_session_async(session_id)
    now = time.time()
    with _sessions_lock:
        session = _sessions.get(session_id)
        if session is not None:
            session.updated_at = now
            return session
    session = SessionState(
        session_id=session_id,
        created_at=now,
        last_active_at=now,
        updated_at=now,
    )
    if await get_async_repository() is not None:
        await async_create_session_record(session_id, None, now)
    else:
        await asyncio.to_thread(save_record, session.to_record())
    with _sessions_lock:
        return _sessions.setdefault(session_id, session)


async def get_existing_session_async(
    session_id: str,
) -> SessionState | None:
    _ensure_loaded()
    if is_shared_store():
        await _refresh_session_async(session_id)
    with _sessions_lock:
        return _sessions.get(session_id)


async def all_sessions_async() -> list[SessionState]:
    _ensure_loaded()
    if is_shared_store():
        await _refresh_all_async()
    with _sessions_lock:
        return list(_sessions.values())


async def list_sessions_async() -> list[dict[str, Any]]:
    _ensure_loaded()
    if is_shared_store():
        await _refresh_all_async()
    return _build_session_listing()


def reset_sessions(*, clear_persisted: bool = False) -> None:
    global _loaded
    with _sessions_lock:
        _sessions.clear()
        _loaded = False
    if clear_persisted:
        clear_records()
        with _sessions_lock:
            _loaded = True
