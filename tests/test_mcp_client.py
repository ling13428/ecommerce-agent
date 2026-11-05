import asyncio
from types import SimpleNamespace

from pydantic import BaseModel

import tools.mcp_client as mcp_client
import tools.registry as registry
from core.tool_auth import verify_approval_token, verify_context_token
from tools.context import ToolContext
from tools.registry import (
    ToolSpec,
    execute_tool_async,
    register_tool,
    unregister_tool,
)

SECRET = "mcp-test-secret"


class ReadArgs(BaseModel):
    order_id: str | None = None


class WriteArgs(BaseModel):
    order_id: str


def _settings(backend="mcp"):
    return SimpleNamespace(
        tool_backend=backend,
        tool_secret_value=SECRET,
        tool_context_ttl_seconds=300,
        tool_approval_ttl_seconds=300,
        mcp_timeout=5.0,
    )


def _run(coro):
    return asyncio.run(coro)


def _register(name, *, kind="read", uses_context=True, server="commerce"):
    spec = ToolSpec(
        name=name,
        description="test only",
        args_model=ReadArgs if kind == "read" else WriteArgs,
        func=lambda **kwargs: {"local": True},
        kind=kind,
        uses_context=uses_context,
        server=server,
    )
    register_tool(spec)
    return spec


def test_local_backend_does_not_call_mcp(monkeypatch):
    calls: list[tuple] = []

    async def fake_call(*args, **kwargs):
        calls.append((args, kwargs))
        return {}

    monkeypatch.setattr(registry, "get_settings", lambda: _settings("local"))
    monkeypatch.setattr(registry, "call_mcp", fake_call)
    spec = _register("_mcp_local_read")
    try:
        result = _run(execute_tool_async(spec.name, {"order_id": "ORD-1"}))
    finally:
        unregister_tool(spec.name)

    assert result["ok"] is True
    assert result["result"] == {"local": True}
    assert calls == []


def test_remote_read_injects_context_token(monkeypatch):
    captured: dict = {}

    async def fake_call(server, tool, arguments, timeout=None):
        captured.update(server=server, tool=tool, arguments=arguments, timeout=timeout)
        return {"found": True, "order": {"order_id": "ORD-1"}}

    monkeypatch.setattr(registry, "get_settings", lambda: _settings("mcp"))
    monkeypatch.setattr(registry, "call_mcp", fake_call)
    spec = _register("_mcp_remote_read")
    try:
        result = _run(
            execute_tool_async(
                spec.name,
                {"order_id": "ORD-1"},
                context=ToolContext(buyer_id="BUY-0001", session_id="s-1"),
            )
        )
    finally:
        unregister_tool(spec.name)

    assert result == {"ok": True, "result": {"found": True, "order": {"order_id": "ORD-1"}}}
    assert captured["server"] == "commerce"
    assert captured["tool"] == "_mcp_remote_read"
    claims = verify_context_token(captured["arguments"]["context_token"], SECRET)
    assert claims["sub"] == "BUY-0001"
    assert claims["sid"] == "s-1"


def test_remote_write_requires_confirmation_before_rpc(monkeypatch):
    calls: list = []

    async def fake_call(*args, **kwargs):
        calls.append(args)
        return {}

    monkeypatch.setattr(registry, "get_settings", lambda: _settings("mcp"))
    monkeypatch.setattr(registry, "call_mcp", fake_call)
    spec = _register("_mcp_remote_write", kind="write")
    try:
        result = _run(
            execute_tool_async(
                spec.name,
                {"order_id": "ORD-1"},
                context=ToolContext(buyer_id="BUY-0001", session_id="s-1"),
            )
        )
    finally:
        unregister_tool(spec.name)

    assert result["status"] == "confirm_required"
    assert calls == []


def test_remote_write_injects_approval_token(monkeypatch):
    captured: dict = {}

    async def fake_call(server, tool, arguments, timeout=None):
        captured.update(server=server, tool=tool, arguments=arguments)
        return {"ok": True, "order_id": "ORD-1"}

    monkeypatch.setattr(registry, "get_settings", lambda: _settings("mcp"))
    monkeypatch.setattr(registry, "call_mcp", fake_call)
    spec = _register("_mcp_remote_write", kind="write")
    try:
        result = _run(
            execute_tool_async(
                spec.name,
                {"order_id": "ORD-1"},
                confirmed=True,
                idempotency_key="jti-1",
                context=ToolContext(buyer_id="BUY-0001", session_id="s-1"),
            )
        )
    finally:
        unregister_tool(spec.name)

    assert result["ok"] is True
    claims = verify_approval_token(
        captured["arguments"]["approval_token"],
        SECRET,
        tool=spec.name,
        arguments={"order_id": "ORD-1"},
    )
    assert claims["jti"] == "jti-1"
    assert claims["sub"] == "BUY-0001"


def test_remote_knowledge_abstain_becomes_handoff(monkeypatch):
    async def fake_call(server, tool, arguments, timeout=None):
        return {"abstained": True, "reason": "低于阈值", "query": "能便宜点吗"}

    monkeypatch.setattr(registry, "get_settings", lambda: _settings("mcp"))
    monkeypatch.setattr(registry, "call_mcp", fake_call)

    result = _run(execute_tool_async("search_knowledge", {"query": "能便宜点吗"}))

    assert result["ok"] is True
    assert result["status"] == "handoff"
    assert "知识库无可靠答案" in result["reason"]
    assert result["abstained"] is True


def test_remote_failure_is_reported_as_tool_error(monkeypatch):
    async def fake_call(*args, **kwargs):
        raise mcp_client.MCPToolError("boom")

    monkeypatch.setattr(registry, "get_settings", lambda: _settings("mcp"))
    monkeypatch.setattr(registry, "call_mcp", fake_call)
    spec = _register("_mcp_remote_fail")
    try:
        result = _run(execute_tool_async(spec.name, {"order_id": "ORD-1"}))
    finally:
        unregister_tool(spec.name)

    assert result["ok"] is False
    assert "工具服务暂时不可用" in result["error"]


def test_payload_parses_structured_text_and_plain():
    structured = SimpleNamespace(structuredContent={"found": True}, content=[], isError=False)
    assert mcp_client._payload(structured) == {"found": True}

    text = SimpleNamespace(
        structuredContent=None,
        content=[SimpleNamespace(text='{"found": false}')],
        isError=False,
    )
    assert mcp_client._payload(text) == {"found": False}

    plain = SimpleNamespace(
        structuredContent=None,
        content=[SimpleNamespace(text="not json")],
        isError=False,
    )
    assert mcp_client._payload(plain) == {"message": "not json"}
