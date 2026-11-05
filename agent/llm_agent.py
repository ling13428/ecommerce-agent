from __future__ import annotations

from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from agent.graph_agent import run_graph_agent
from agent.legacy_agent import run_legacy_agent
from agent.router import RouteResult
from agent.session import SessionState
from core.config import get_settings


async def run_llm_agent(
    session: SessionState,
    client: AsyncOpenAI | None = None,
    route: RouteResult | None = None,
) -> AsyncIterator[dict[str, Any]]:
    settings = get_settings()
    engine = (settings.agent_engine or "graph").strip().lower()
    runner = run_legacy_agent if engine == "legacy" else run_graph_agent
    async for event in runner(session, client=client, route=route):
        yield event
