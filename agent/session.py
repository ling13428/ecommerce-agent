from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class PendingAction:
    name: str
    args: dict[str, Any]
    summary: str
    idempotency_key: str = field(default_factory=lambda: uuid4().hex)


@dataclass
class SessionState:
    session_id: str
    max_messages: int = 20
    messages: list[dict[str, Any]] = field(default_factory=list)
    pending_action: PendingAction | None = None
    updated_at: float = field(default_factory=time.time)

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages :]
        self.updated_at = time.time()

    def add_user(self, content: str) -> None:
        self.add_message("user", content)

    def add_assistant(self, content: str) -> None:
        if content.strip():
            self.add_message("assistant", content)

    def add_system(self, content: str) -> None:
        self.add_message("system", content)

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self.messages)

    def set_pending(self, name: str, args: dict[str, Any], summary: str) -> None:
        self.pending_action = PendingAction(name=name, args=args, summary=summary)
        self.updated_at = time.time()

    def pop_pending(self) -> PendingAction | None:
        pending = self.pending_action
        self.pending_action = None
        self.updated_at = time.time()
        return pending

    def clear_pending(self) -> None:
        self.pending_action = None
        self.updated_at = time.time()


_sessions: dict[str, SessionState] = {}
_sessions_lock = threading.Lock()
_last_cleanup = 0.0


def _cleanup_expired(now: float, ttl_seconds: float = 3600.0) -> None:
    expired = [
        session_id
        for session_id, session in _sessions.items()
        if now - session.updated_at > ttl_seconds
    ]
    for session_id in expired:
        _sessions.pop(session_id, None)


def get_session(session_id: str, *, max_messages: int = 20) -> SessionState:
    global _last_cleanup

    now = time.time()
    with _sessions_lock:
        if now - _last_cleanup > 300:
            _cleanup_expired(now)
            _last_cleanup = now

        session = _sessions.get(session_id)
        if session is None:
            session = SessionState(session_id=session_id, max_messages=max_messages)
            _sessions[session_id] = session
        session.updated_at = now
        return session


def reset_sessions() -> None:
    global _last_cleanup
    with _sessions_lock:
        _sessions.clear()
        _last_cleanup = 0.0
