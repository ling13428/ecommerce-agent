from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Mapping

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from core.auth import AuthError
from core.config import get_settings
from core.tool_auth import args_digest, verify_approval_token, verify_context_token
from mcp_servers.idempotency import run_once, run_once_async
from tools.context import ToolContext

logger = logging.getLogger("ecommerce_agent.mcp")


class ToolAccessError(RuntimeError):
    pass


def tool_secret() -> str:
    secret = get_settings().tool_secret_value
    if not secret:
        raise ToolAccessError("MCP 工具签名密钥未配置")
    return secret


def context_from_token(token: str | None) -> ToolContext:
    if not token:
        raise ToolAccessError("缺少工具上下文令牌")
    try:
        claims = verify_context_token(token, tool_secret())
    except AuthError as exc:
        raise ToolAccessError(f"工具上下文令牌无效：{exc}") from exc
    return ToolContext(
        buyer_id=str(claims.get("sub") or "") or None,
        session_id=str(claims.get("sid") or "") or None,
    )


def run_write(
    tool: str,
    arguments: Mapping[str, Any],
    approval_token: str | None,
    func,
    *,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    if not approval_token:
        raise ToolAccessError("写操作缺少审批令牌")
    try:
        claims = verify_approval_token(
            approval_token,
            tool_secret(),
            tool=tool,
            arguments=arguments,
        )
    except AuthError as exc:
        raise ToolAccessError(f"写操作审批令牌无效：{exc}") from exc
    if context is not None:
        if (str(claims.get("sub") or "") or None) != context.buyer_id:
            raise ToolAccessError("审批令牌与工具上下文的买家不一致")
        session_id = str(claims.get("sid") or "")
        if session_id and context.session_id and session_id != context.session_id:
            raise ToolAccessError("审批令牌与工具上下文的会话不一致")
    key = f"{tool}:{claims['jti']}:{args_digest(arguments)}"
    return run_once(key, func)


async def run_write_async(
    tool: str,
    arguments: Mapping[str, Any],
    approval_token: str | None,
    func: Callable[[], Awaitable[dict[str, Any]]],
    *,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    if not approval_token:
        raise ToolAccessError("写操作缺少审批令牌")
    try:
        claims = verify_approval_token(
            approval_token,
            tool_secret(),
            tool=tool,
            arguments=arguments,
        )
    except AuthError as exc:
        raise ToolAccessError(f"写操作审批令牌无效：{exc}") from exc
    if context is not None:
        if (str(claims.get("sub") or "") or None) != context.buyer_id:
            raise ToolAccessError("审批令牌与工具上下文的买家不一致")
        session_id = str(claims.get("sid") or "")
        if session_id and context.session_id and session_id != context.session_id:
            raise ToolAccessError("审批令牌与工具上下文的会话不一致")
    key = f"{tool}:{claims['jti']}:{args_digest(arguments)}"
    return await run_once_async(key, func)


def build_server(
    name: str,
    *,
    instructions: str,
    host: str = "127.0.0.1",
    port: int = 9000,
) -> FastMCP:
    server = FastMCP(
        name,
        instructions=instructions,
        host=host,
        port=port,
        streamable_http_path="/mcp",
    )

    @server.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "server": name})

    return server
