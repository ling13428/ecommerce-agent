import asyncio
from types import SimpleNamespace

from pydantic import BaseModel

import tools.knowledge as knowledge
from agent.llm_agent import run_llm_agent
from agent.session import SessionState
from rag.search import SearchHit, SearchResult
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


def new_session(message="P2001 多少钱"):
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
                tool_chunk(arguments=' "P2001"}'),
            ],
            [content_chunk("这款键盘价格是 969 元。")],
        ]
    )
    session = new_session()

    events = collect(session, client)

    tool_events = [event for event in events if event["type"] == "tool_call"]
    assert tool_events[0]["name"] == "get_product"
    assert tool_events[0]["args"] == {"product_id": "P2001"}
    assert "".join(
        event["content"] for event in events if event["type"] == "delta"
    ) == "这款键盘价格是 969 元。"
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

    text = "".join(
        event["content"] for event in events if event["type"] == "delta"
    )
    assert "正在为你转接人工客服" in text
    assert any(event["type"] == "handoff" for event in events)
    assert any(event["type"] == "delta" for event in events)


def test_handoff_does_not_repeat_streamed_message():
    client = FakeClient(
        [
            [
                content_chunk("好的，正在为你转接人工客服。"),
                tool_chunk(
                    call_id="call_1",
                    name="transfer_to_human",
                    arguments='{"reason": "用户要求人工"}',
                ),
            ]
        ]
    )
    session = new_session("我要找人工")

    events = collect(session, client)

    text = "".join(
        event["content"] for event in events if event["type"] == "delta"
    )
    assert text == "好的，正在为你转接人工客服。"
    assert any(event["type"] == "handoff" for event in events)


def test_search_knowledge_auto_injects_product_id(monkeypatch):
    def fake(query, **kwargs):
        return SearchResult(
            query=query, hits=[], abstained=False, reason=None, min_score=0.55
        )

    monkeypatch.setattr(knowledge, "_search_rag", fake)

    client = FakeClient(
        [
            [
                tool_chunk(
                    call_id="call_1",
                    name="search_knowledge",
                    arguments='{"query": "续航多久"}',
                )
            ],
            [content_chunk("续航约 30 小时。")],
        ]
    )
    session = new_session("P2001 键盘续航多久")

    events = collect(session, client)

    tool_events = [event for event in events if event["type"] == "tool_call"]
    assert tool_events[0]["args"] == {
        "query": "续航多久",
        "product_id": "P2001",
    }


def test_search_tool_event_carries_rag_detail(monkeypatch):
    hit = SearchHit(
        chunk_id="c1",
        parent_id="p1",
        doc_id="P2001-02",
        product_id="P2001",
        title="VK75 Pro 参数",
        section_path="详细参数",
        unit_kind="section",
        text="续航约 30 小时",
        parent_text="VK75 Pro 内置 4000mAh 电池，续航约 30 小时。",
        score=0.81,
        metadata={"source": "data/products/docs/P2001-02.md"},
    )

    def fake(query, **kwargs):
        return SearchResult(
            query=query,
            hits=[hit],
            abstained=False,
            reason=None,
            min_score=0.55,
        )

    monkeypatch.setattr(knowledge, "_search_rag", fake)

    client = FakeClient(
        [
            [
                tool_chunk(
                    call_id="call_1",
                    name="search_knowledge",
                    arguments='{"query": "续航多久", "product_id": "P2001"}',
                )
            ],
            [content_chunk("续航约 30 小时。")],
        ]
    )
    session = new_session("P2001 键盘续航多久")

    events = collect(session, client)

    tool_event = next(event for event in events if event["type"] == "tool_call")
    assert tool_event["detail"]["kind"] == "rag"
    assert tool_event["detail"]["top_score"] == 0.81
    assert tool_event["detail"]["hits"][0]["doc_id"] == "P2001-02"
    assert "续航约 30 小时" in tool_event["detail"]["hits"][0]["content"]
    assert any(event["type"] == "llm_step" for event in events)


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

        event = asyncio.run(resolve_pending_confirmation(session, "确认"))

        assert event is not None
        assert event["confirmed"] is True
        assert event["ok"] is True
        assert session.pending_action is None
        assert any(
            "用户已明确确认" in message["content"] for message in session.messages
        )
        assert asyncio.run(resolve_pending_confirmation(session, "确认")) is None
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

        event = asyncio.run(resolve_pending_confirmation(session, "算了"))

        assert event is not None
        assert event["type"] == "confirmation_cancelled"
        assert session.pending_action is None
    finally:
        unregister_tool("_cancel_order")
