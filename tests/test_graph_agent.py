import asyncio
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import BaseModel

from agent.graph_agent import NoPendingInterrupt, run_graph_agent_resume
from agent.llm_agent import run_llm_agent
from agent.session import SessionState
from core.config import get_settings
from tools.registry import ToolSpec, register_tool, unregister_tool


class EmptyArgs(BaseModel):
    pass


class FakeStream:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


class FakeCompletions:
    def __init__(self, streams):
        self._streams = list(streams)

    async def create(self, **kwargs):
        return FakeStream(self._streams.pop(0))


class FakeClient:
    def __init__(self, streams):
        self.chat = SimpleNamespace(completions=FakeCompletions(streams))


def content_chunk(text):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=None))
        ]
    )


def tool_chunk(index=0, call_id=None, name=None, arguments=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            index=index,
                            id=call_id,
                            function=SimpleNamespace(
                                name=name, arguments=arguments
                            ),
                        )
                    ],
                )
            )
        ]
    )


def collect(session, client):
    async def run():
        return [event async for event in run_llm_agent(session, client=client)]

    return asyncio.run(run())


def new_session(message="你好"):
    session = SessionState(session_id=f"graph-test-{uuid4().hex}")
    session.add_user(message)
    return session


def collect_resume(session, approved, client):
    async def run():
        return [
            event
            async for event in run_graph_agent_resume(
                session, approved=approved, client=client
            )
        ]

    return asyncio.run(run())


def test_read_tools_run_in_parallel():
    def slow_a():
        time.sleep(0.25)
        return {"tool": "a"}

    def slow_b():
        time.sleep(0.25)
        return {"tool": "b"}

    register_tool(
        ToolSpec(
            name="_slow_a",
            description="test only",
            args_model=EmptyArgs,
            func=slow_a,
        )
    )
    register_tool(
        ToolSpec(
            name="_slow_b",
            description="test only",
            args_model=EmptyArgs,
            func=slow_b,
        )
    )
    try:
        client = FakeClient(
            [
                [
                    tool_chunk(index=0, call_id="call_a", name="_slow_a", arguments="{}"),
                    tool_chunk(index=1, call_id="call_b", name="_slow_b", arguments="{}"),
                ],
                [content_chunk("都查好了。")],
            ]
        )

        started = time.monotonic()
        events = collect(new_session(), client)
        elapsed = time.monotonic() - started

        tool_events = [event for event in events if event["type"] == "tool_call"]
        assert {event["name"] for event in tool_events} == {"_slow_a", "_slow_b"}
        assert elapsed < 0.45
    finally:
        unregister_tool("_slow_a")
        unregister_tool("_slow_b")


class WriteArgs(BaseModel):
    order_id: str


def test_batch_tool_calls_keep_read_after_write():
    register_tool(
        ToolSpec(
            name="_batch_write",
            description="test only",
            args_model=WriteArgs,
            func=lambda order_id: {"cancelled": order_id},
            kind="write",
        )
    )
    register_tool(
        ToolSpec(
            name="_batch_read",
            description="test only",
            args_model=EmptyArgs,
            func=lambda: {"ok": True},
        )
    )
    try:
        client = FakeClient(
            [
                [
                    tool_chunk(
                        index=0,
                        call_id="call_w",
                        name="_batch_write",
                        arguments='{"order_id": "A100"}',
                    ),
                    tool_chunk(
                        index=1,
                        call_id="call_r",
                        name="_batch_read",
                        arguments="{}",
                    ),
                ]
            ]
        )

        session = new_session("取消订单 A100")
        events = collect(session, client)

        tool_events = [event for event in events if event["type"] == "tool_call"]
        assert len(tool_events) == 2
        assert any(event["type"] == "confirm_required" for event in events)
        assert session.pending_action is not None
        assert session.pending_action.name == "_batch_write"
    finally:
        unregister_tool("_batch_write")
        unregister_tool("_batch_read")


def test_legacy_engine_dispatch(monkeypatch):
    monkeypatch.setenv("AGENT_ENGINE", "legacy")
    get_settings.cache_clear()
    try:
        client = FakeClient([[content_chunk("旧引擎可用。")]])
        events = collect(new_session(), client)
        assert "".join(
            event["content"] for event in events if event["type"] == "delta"
        ) == "旧引擎可用。"
    finally:
        get_settings.cache_clear()


def _write_order_tool(calls):
    def cancel(order_id):
        calls.append(order_id)
        return {"cancelled": order_id}

    return ToolSpec(
        name="_resume_cancel",
        description="test only",
        args_model=WriteArgs,
        func=cancel,
        kind="write",
    ), "_resume_cancel"


def test_interrupt_resume_executes_write_once():
    calls: list[str] = []
    spec, name = _write_order_tool(calls)
    register_tool(spec)
    try:
        client = FakeClient(
            [
                [
                    tool_chunk(
                        call_id="call_w",
                        name=name,
                        arguments='{"order_id": "A100"}',
                    )
                ],
                [content_chunk("订单 A100 已取消。")],
            ]
        )
        session = new_session("取消订单 A100")

        first = collect(session, client)
        assert any(event["type"] == "confirm_required" for event in first)
        assert session.pending_action is not None
        assert calls == []

        second = collect_resume(session, True, client)
        types = [event["type"] for event in second]
        assert "tool_call" in types
        assert "delta" in types
        assert calls == ["A100"]
        assert session.pending_action is None
        assert session.messages[-1]["role"] == "assistant"
    finally:
        unregister_tool(name)


def test_interrupt_resume_cancel_does_not_execute():
    calls: list[str] = []
    spec, name = _write_order_tool(calls)
    register_tool(spec)
    try:
        client = FakeClient(
            [
                [
                    tool_chunk(
                        call_id="call_w",
                        name=name,
                        arguments='{"order_id": "A200"}',
                    )
                ],
                [content_chunk("好的，已取消本次操作。")],
            ]
        )
        session = new_session("取消订单 A200")

        collect(session, client)
        assert session.pending_action is not None

        second = collect_resume(session, False, client)
        assert any(
            event["type"] == "confirmation_cancelled" for event in second
        )
        assert calls == []
        assert session.pending_action is None
        assert "".join(
            event["content"]
            for event in second
            if event["type"] == "delta"
        ) == "好的，已取消本次操作。"
    finally:
        unregister_tool(name)


def test_resume_without_interrupt_raises():
    session = new_session("确认")
    with pytest.raises(NoPendingInterrupt):
        collect_resume(session, True, FakeClient([]))
