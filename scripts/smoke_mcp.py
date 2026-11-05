from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import get_settings  # noqa: E402
from core.tool_auth import create_context_token  # noqa: E402
from tools.mcp_client import MCPToolError, call_mcp  # noqa: E402


async def run(buyer_id: str) -> int:
    settings = get_settings()
    secret = settings.tool_secret_value
    if not secret:
        print("未配置 TOOL_SECRET / AUTH_SECRET，无法签发工具令牌")
        return 2

    context_token = create_context_token(
        secret,
        buyer_id=buyer_id,
        session_id="mcp-smoke",
        ttl_seconds=settings.tool_context_ttl_seconds,
    )
    checks = [
        ("catalog", "get_product", {"product_id": "P2001"}),
        ("commerce", "get_order", {"context_token": context_token}),
        ("knowledge", "search_knowledge", {"query": "VK75 Pro 触发键程", "top_k": 3}),
    ]

    failed = 0
    for server, tool, arguments in checks:
        try:
            result = await call_mcp(server, tool, arguments)
        except MCPToolError as exc:
            failed += 1
            print(f"[FAIL] {server}.{tool}: {exc}")
            continue
        summary = {
            key: result.get(key)
            for key in ("found", "abstained", "count", "status")
            if key in result
        }
        print(f"[OK] {server}.{tool}: {json.dumps(summary, ensure_ascii=False)}")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="检查内部 MCP server 是否可用")
    parser.add_argument("--buyer-id", default="BUY-0001")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.buyer_id)))


if __name__ == "__main__":
    main()
