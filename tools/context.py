from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolContext:
    buyer_id: str | None = None
    session_id: str | None = None
