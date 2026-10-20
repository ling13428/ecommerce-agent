import asyncio
from types import SimpleNamespace

from pydantic import BaseModel

from agent.llm_agent import run_llm_agent
from agent.session import SessionState
from tools.registry import (
    ToolSpec,
    execute_tool,
    register_tool,
    unregister_tool,
)


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


def new_session(message="P1001 多少钱"):
    session = SessionState(session_id="test")
    session.add_user(message)
    return session


def test_tool_call_then_final_answer():
    client = FakeClient(
        [
            [
                tool_chunk(
                    call_id="call_1",
                    name="get_product",
                    arguments='{"product_id":',
                ),
                tool_chunk(arguments=' "P1001"}'),
            ],
            [content_chunk("这款耳机价格是 299 元。")],
        ]
    )
    session = new_session()

    events = collect(session, client)

    tool_events = [event for event in events if event["type"] == "tool_call"]
    assert tool_events[0]["name"] == "get_product"
    assert tool_events[0]["args"] == {"product_id": "P1001"}
    assert "".join(
        event["content"] for event in events if event["type"] == "delta"
    ) == "这款耳机价格是 299 元。"
    assert session.messages[-1]["role"] == "assistant"


def test_handoff_tool_stops_the_loop():
    client = FakeClient(
        [
            [
                tool_chunk(
                    call_id="call_1",
                    name="transfer_to_human",
                    arguments='{"reason": "用户要求人工"}',
                )
            ]
        ]
    )
    session = new_session("我要找人工")

    events = collect(session, client)

    assert any(event["type"] == "handoff" for event in events)
    assert any(event["type"] == "delta" for event in events)


class WriteArgs(BaseModel):
    order_id: str


def test_write_tool_waits_for_confirmation():
    spec = ToolSpec(
        name="_cancel_order",
        description="test only",
        args_model=WriteArgs,
        func=lambda order_id: {"cancelled": order_id},
        kind="write",
    )
    register_tool(spec)
    try:
        client = FakeClient(
            [
                [
                    tool_chunk(
                        call_id="call_1",
                        name="_cancel_order",
                        arguments='{"order_id": "A100"}',
                    )
                ]
            ]
        )
        session = new_session("取消订单 A100")

        events = collect(session, client)

        assert any(event["type"] == "confirm_required" for event in events)
        assert session.pending_action is not None
        assert session.pending_action.name == "_cancel_order"

        confirmed = execute_tool(
            "_cancel_order",
            {"order_id": "A100"},
            confirmed=True,
            idempotency_key="test-key",
        )
        assert confirmed["result"] == {"cancelled": "A100"}
    finally:
        unregister_tool("_cancel_order")


def test_user_confirmation_executes_pending_write_only_once():
    from main import resolve_pending_confirmation

    spec = ToolSpec(
        name="_cancel_order",
        description="test only",
        args_model=WriteArgs,
        func=lambda order_id: {"cancelled": order_id},
        kind="write",
    )
    register_tool(spec)
    try:
        session = new_session("确认")
        session.set_pending(
            "_cancel_order", {"order_id": "A100"}, "即将取消订单 A100"
        )

        event = resolve_pending_confirmation(session, "确认")

        assert event is not None
        assert event["confirmed"] is True
        assert event["ok"] is True
        assert session.pending_action is None
        assert any(
            "用户已明确确认" in message["content"] for message in session.messages
        )
        assert resolve_pending_confirmation(session, "确认") is None
    finally:
        unregister_tool("_cancel_order")


def test_user_cancellation_clears_pending_write():
    from main import resolve_pending_confirmation

    spec = ToolSpec(
        name="_cancel_order",
        description="test only",
        args_model=WriteArgs,
        func=lambda order_id: {"cancelled": order_id},
        kind="write",
    )
    register_tool(spec)
    try:
        session = new_session("算了")
        session.set_pending(
            "_cancel_order", {"order_id": "A100"}, "即将取消订单 A100"
        )

        event = resolve_pending_confirmation(session, "算了")

        assert event is not None
        assert event["type"] == "confirmation_cancelled"
        assert session.pending_action is None
    finally:
        unregister_tool("_cancel_order")
