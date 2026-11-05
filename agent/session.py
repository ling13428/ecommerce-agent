from __future__ import annotations

import copy
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from agent.session_store import (
    clear_records,
    is_shared_store,
    load_record,
    load_records,
    save_record,
)

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
                summary=str(pending.get("summary", "")),
                idempotency_key=str(pending.get("idempotency_key") or uuid4().hex),
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
            updated_at=float(record.get("updated_at") or time.time()),
            next_message_id=int(record.get("next_message_id") or 1),
            next_trace_id=int(record.get("next_trace_id") or 1),
        )

    def _persist(self) -> None:
        save_record(self.to_record())

    def add_message(
        self, role: str, content: str, *, source: str | None = None
    ) -> dict[str, Any]:
        message: dict[str, Any] = {
            "id": self.next_message_id,
            "role": role,
            "content": content,
        }
        if source:
            message["source"] = source
        self.next_message_id += 1
        self.messages.append(message)
        if self.max_messages is not None and len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages :]
        self.updated_at = time.time()
        self._persist()
        return message

    def add_user(self, content: str) -> dict[str, Any]:
        return self.add_message("user", content)

    def add_assistant(self, content: str, *, source: str | None = None) -> None:
        if content.strip():
            self.add_message("assistant", content, source=source)

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
        record["id"] = self.next_trace_id
        self.next_trace_id += 1
        self.traces.append(record)
        if self.max_traces is not None and len(self.traces) > self.max_traces:
            self.traces = self.traces[-self.max_traces :]
        self.updated_at = time.time()
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

    def set_human_mode(self, enabled: bool) -> None:
        if self.human_mode == enabled:
            return
        self.human_mode = enabled
        self.updated_at = time.time()
        self._persist()

    def set_buyer_id(self, buyer_id: str | None) -> None:
        normalized = (buyer_id or "").strip().upper() or None
        if self.buyer_id == normalized:
            return
        self.buyer_id = normalized
        self.updated_at = time.time()
        self._persist()

    def set_pending(self, name: str, args: dict[str, Any], summary: str) -> None:
        self.pending_action = PendingAction(name=name, args=args, summary=summary)
        self.updated_at = time.time()
        self._persist()

    def pop_pending(self) -> PendingAction | None:
        pending = self.pending_action
        self.pending_action = None
        self.updated_at = time.time()
        self._persist()
        return pending

    def clear_pending(self) -> None:
        if self.pending_action is None:
            return
        self.pending_action = None
        self.updated_at = time.time()
        self._persist()


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
                "跳过无法恢复的会话 %s：%s", record.get("session_id"), exc
            )
            continue
        with _sessions_lock:
            _sessions[session.session_id] = session


def load_persisted_sessions() -> int:
    _ensure_loaded()
    if is_shared_store():
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
        if session is None:
            session = SessionState(session_id=session_id)
            _sessions[session_id] = session
            session._persist()
        session.updated_at = now
        return session


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


def list_sessions() -> list[dict[str, Any]]:
    _ensure_loaded()
    if is_shared_store():
        _refresh_all()
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


def reset_sessions(*, clear_persisted: bool = False) -> None:
    global _loaded
    with _sessions_lock:
        _sessions.clear()
        _loaded = False
    if clear_persisted:
        clear_records()
        with _sessions_lock:
            _loaded = True
