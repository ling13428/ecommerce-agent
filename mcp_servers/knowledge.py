from __future__ import annotations

from typing import Any

from mcp_servers.common import build_server
from tools import knowledge as knowledge_tools

INSTRUCTIONS = (
    "店铺与商品知识库检索。只返回检索结果和置信信息，"
    "是否转人工由 orchestrator 决定。"
)


def search_knowledge(
    query: str,
    product_id: str | None = None,
    top_k: int = 5,
    include_deprecated: bool = False,
) -> dict[str, Any]:
    return knowledge_tools.search_knowledge(
        query,
        product_id=product_id,
        top_k=top_k,
        include_deprecated=include_deprecated,
    )


def build(host: str = "127.0.0.1", port: int = 9103):
    server = build_server(
        "knowledge", instructions=INSTRUCTIONS, host=host, port=port
    )
    server.add_tool(search_knowledge)
    return server
