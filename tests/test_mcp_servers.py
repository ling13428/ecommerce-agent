import asyncio

from mcp.shared.memory import create_connected_server_and_client_session

import tools.knowledge as knowledge
from core.config import get_settings
from core.tool_auth import create_approval_token, create_context_token
from mcp_servers import catalog, commerce
from mcp_servers import knowledge as knowledge_server
from rag.search import SearchHit, SearchResult

SECRET = get_settings().tool_secret_value


def _run(coro):
    return asyncio.run(coro)


async def _call(server, tool, arguments):
    async with create_connected_server_and_client_session(server) as session:
        await session.initialize()
        return await session.call_tool(tool, arguments)


def _context(buyer_id="BUY-0001"):
    return create_context_token(
        SECRET, buyer_id=buyer_id, session_id="s-test", ttl_seconds=300
    )


def _approval(tool, arguments, jti="jti-test"):
    return create_approval_token(
        SECRET,
        buyer_id="BUY-0001",
        session_id="s-test",
        tool=tool,
        arguments=arguments,
        idempotency_key=jti,
        ttl_seconds=300,
    )


def _error_text(result):
    return "\n".join(str(getattr(item, "text", "")) for item in result.content)


def _hit() -> SearchHit:
    return SearchHit(
        chunk_id="P2001-01_C001",
        parent_id="P2001-01_P001",
        doc_id="P2001-01",
        product_id="P2001",
        title="烬狐 VK75 Pro 磁轴键盘",
        section_path="概述",
        unit_kind="section",
        text="VK75 Pro 支持磁轴。",
        parent_text="## 概述\n\nVK75 Pro 支持磁轴。",
        score=0.72,
        metadata={"source": "模拟商品库"},
    )


def test_catalog_server_lists_and_returns_products():
    server = catalog.build()

    async def scenario():
        async with create_connected_server_and_client_session(server) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "get_product",
                "recommend_products",
            }
            result = await session.call_tool("get_product", {"product_id": "P2001"})
            assert result.isError is False
            assert result.structuredContent["found"] is True
            assert result.structuredContent["product"]["model"] == "VK75 Pro"

    _run(scenario())


def test_commerce_read_requires_context_token():
    server = commerce.build()
    result = _run(_call(server, "get_order", {}))

    assert result.isError is True
    assert "上下文令牌" in _error_text(result)


def test_commerce_read_uses_token_buyer(monkeypatch):
    monkeypatch.setattr(
        "tools.orders.order_service.list_orders",
        lambda buyer_id: [{"order_id": "ORD-1", "buyer_id": buyer_id}],
    )
    monkeypatch.setattr(
        "tools.orders.order_service.get_buyer",
        lambda buyer_id: {"buyer_id": buyer_id, "nickname": "测试", "member_level": "V1", "city": "上海"},
    )
    server = commerce.build()

    result = _run(_call(server, "get_order", {"context_token": _context("BUY-0009")}))

    assert result.isError is False
    payload = result.structuredContent
    assert payload["found"] is True
    assert payload["buyer"]["buyer_id"] == "BUY-0009"


def test_commerce_write_denied_without_approval(monkeypatch):
    called: list[str] = []
    monkeypatch.setattr(
        "tools.orders.cancel_order",
        lambda order_id, context=None: called.append(order_id) or {"ok": True},
    )
    server = commerce.build()

    result = _run(
        _call(
            server,
            "cancel_order",
            {"order_id": "ORD-1", "context_token": _context()},
        )
    )

    assert result.isError is True
    assert "审批令牌" in _error_text(result)
    assert called == []


def test_commerce_write_rejects_buyer_mismatch(monkeypatch):
    called: list[str] = []
    monkeypatch.setattr(
        "tools.orders.cancel_order",
        lambda order_id, context=None: called.append(order_id) or {"ok": True},
    )
    server = commerce.build()
    token = _approval("cancel_order", {"order_id": "ORD-1"})

    result = _run(
        _call(
            server,
            "cancel_order",
            {
                "order_id": "ORD-1",
                "context_token": _context("BUY-0002"),
                "approval_token": token,
            },
        )
    )

    assert result.isError is True
    assert "买家不一致" in _error_text(result)
    assert called == []


def test_commerce_write_rejects_args_mismatch(monkeypatch):
    called: list[str] = []
    monkeypatch.setattr(
        "tools.orders.cancel_order",
        lambda order_id, context=None: called.append(order_id) or {"ok": True},
    )
    server = commerce.build()
    token = _approval("cancel_order", {"order_id": "ORD-1"})

    result = _run(
        _call(
            server,
            "cancel_order",
            {
                "order_id": "ORD-2",
                "context_token": _context(),
                "approval_token": token,
            },
        )
    )

    assert result.isError is True
    assert "参数不匹配" in _error_text(result)
    assert called == []


def test_commerce_write_is_idempotent_by_jti(monkeypatch):
    called: list[str] = []

    def fake_cancel(order_id, context=None):
        called.append(order_id)
        return {"ok": True, "order_id": order_id, "count": len(called)}

    monkeypatch.setattr("tools.orders.cancel_order", fake_cancel)
    server = commerce.build()
    arguments = {"order_id": "ORD-1"}

    async def scenario():
        async with create_connected_server_and_client_session(server) as session:
            await session.initialize()
            payload = {
                "order_id": "ORD-1",
                "context_token": _context(),
                "approval_token": _approval("cancel_order", arguments, "jti-same"),
            }
            first = await session.call_tool("cancel_order", payload)
            second = await session.call_tool("cancel_order", payload)
            return first, second

    first, second = _run(scenario())

    assert first.isError is False
    assert first.structuredContent == second.structuredContent
    assert called == ["ORD-1"]


def test_knowledge_server_returns_raw_result_without_handoff(monkeypatch):
    monkeypatch.setattr(
        knowledge,
        "_search_rag",
        lambda query, **kwargs: SearchResult(
            query=query,
            hits=[_hit()],
            abstained=True,
            reason="最高相似度 0.210 低于阈值 0.55",
            min_score=0.55,
        ),
    )
    server = knowledge_server.build()

    result = _run(_call(server, "search_knowledge", {"query": "能便宜点吗"}))

    assert result.isError is False
    payload = result.structuredContent
    assert payload["abstained"] is True
    assert "status" not in payload
    assert "handoff" not in payload
