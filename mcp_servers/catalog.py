from __future__ import annotations

from typing import Any

from mcp_servers.common import build_server
from tools import products as product_tools
from tools import recommend as recommend_tools

INSTRUCTIONS = "商品主数据与导购推荐。价格为实时数据，不进入知识库。"


def get_product(
    product_id: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    return product_tools.get_product(product_id=product_id, name=name)


def recommend_products(
    budget: int | None = None,
    category: str | None = None,
    use_case: str | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    return recommend_tools.recommend_products(
        budget=budget,
        category=category,
        use_case=use_case,
        limit=limit,
    )


def build(host: str = "127.0.0.1", port: int = 9102):
    server = build_server(
        "catalog", instructions=INSTRUCTIONS, host=host, port=port
    )
    for tool in (get_product, recommend_products):
        server.add_tool(tool)
    return server
