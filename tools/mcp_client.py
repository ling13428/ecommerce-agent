from __future__ import annotations

import asyncio
import json
import logging
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from core.config import Settings, get_settings

logger = logging.getLogger("ecommerce_agent.mcp_client")

_URL_FIELDS = {
    "commerce": "mcp_commerce_url",
    "catalog": "mcp_catalog_url",
    "knowledge": "mcp_knowledge_url",
}

_sessions: dict[tuple[int, str], ClientSession] = {}
_stacks: dict[tuple[int, str], AsyncExitStack] = {}
_locks: dict[tuple[int, str], asyncio.Lock] = {}


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


def _key(server: str) -> tuple[int, str]:
    return (id(asyncio.get_running_loop()), server)


async def _get_session(server: str) -> ClientSession:
    key = _key(server)
    session = _sessions.get(key)
    if session is not None:
        return session

    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        session = _sessions.get(key)
        if session is not None:
            return session

        settings = get_settings()
        url = server_url(server, settings)
        stack = AsyncExitStack()
        try:
            read_stream, write_stream, _ = await stack.enter_async_context(
                streamablehttp_client(
                    url,
                    timeout=settings.mcp_timeout,
                    sse_read_timeout=settings.mcp_timeout,
                )
            )
            session = await stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()
        except Exception as exc:
            await stack.aclose()
            raise MCPToolError(f"{server} 连接失败：{exc}") from exc
        _stacks[key] = stack
        _sessions[key] = session
        return session


async def _reset_session(server: str) -> None:
    key = _key(server)
    _sessions.pop(key, None)
    stack = _stacks.pop(key, None)
    if stack is not None:
        try:
            await stack.aclose()
        except Exception as exc:
            logger.warning("关闭 MCP 会话失败 server=%s：%s", server, exc)


async def close_mcp_sessions() -> None:
    for server in list({key[1] for key in _sessions}):
        await _reset_session(server)


async def call_mcp(
    server: str,
    tool: str,
    arguments: dict[str, Any],
    *,
    timeout: float | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    effective_timeout = timeout if timeout is not None else settings.mcp_timeout
    try:
        result = await _call_with_session(
            server, tool, arguments, effective_timeout
        )
    except MCPToolError:
        raise
    except Exception as exc:
        raise MCPToolError(f"{server}.{tool} 调用失败：{exc}") from exc

    if getattr(result, "isError", False):
        raise MCPToolError(f"{server}.{tool} 返回错误：{_text(result)}")
    return _payload(result)


async def _call_with_session(
    server: str,
    tool: str,
    arguments: dict[str, Any],
    timeout: float,
) -> Any:
    session = await _get_session(server)
    try:
        return await asyncio.wait_for(
            session.call_tool(tool, arguments), timeout=timeout
        )
    except asyncio.TimeoutError:
        raise
    except Exception:
        await _reset_session(server)
        session = await _get_session(server)
        return await asyncio.wait_for(
            session.call_tool(tool, arguments), timeout=timeout
        )
