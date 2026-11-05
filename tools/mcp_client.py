from __future__ import annotations

import json
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from core.config import Settings, get_settings

_URL_FIELDS = {
    "commerce": "mcp_commerce_url",
    "catalog": "mcp_catalog_url",
    "knowledge": "mcp_knowledge_url",
}


class MCPToolError(RuntimeError):
    pass


def server_url(server: str, settings: Settings | None = None) -> str:
    field = _URL_FIELDS.get(server)
    if field is None:
        raise MCPToolError(f"未知的 MCP server：{server}")
    current = settings or get_settings()
    return str(getattr(current, field))


def _text(result: Any) -> str:
    parts = [
        str(getattr(item, "text", "") or "")
        for item in getattr(result, "content", []) or []
    ]
    return "\n".join(part for part in parts if part)


def _payload(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    text = _text(result)
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"message": text}
    return parsed if isinstance(parsed, dict) else {"result": parsed}


async def call_mcp(
    server: str,
    tool: str,
    arguments: dict[str, Any],
    *,
    timeout: float | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    url = server_url(server, settings)
    effective_timeout = timeout if timeout is not None else settings.mcp_timeout
    try:
        async with streamablehttp_client(
            url,
            timeout=effective_timeout,
            sse_read_timeout=effective_timeout,
        ) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments)
    except MCPToolError:
        raise
    except Exception as exc:
        raise MCPToolError(f"{server}.{tool} 调用失败：{exc}") from exc

    if getattr(result, "isError", False):
        raise MCPToolError(f"{server}.{tool} 返回错误：{_text(result)}")
    return _payload(result)
