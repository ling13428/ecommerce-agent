from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from core.config import BASE_DIR

CATALOG = BASE_DIR / "data" / "products" / "catalog.json"

CATEGORY_ALIASES = {
    "keyboard": "键盘",
    "键盘": "键盘",
    "mouse": "鼠标",
    "鼠标": "鼠标",
    "headset": "耳机",
    "headphone": "耳机",
    "耳机": "耳机",
}


@lru_cache(maxsize=1)
def _products() -> list[dict[str, Any]]:
    with CATALOG.open("r", encoding="utf-8") as handle:
        return list(json.load(handle)["products"])


def _normalize_category(value: str | None) -> str | None:
    if not value:
        return None
    return CATEGORY_ALIASES.get(value.strip().lower())


def _searchable(product: dict[str, Any]) -> str:
    params = " ".join(
        str(item) for item in (product.get("params") or {}).values()
    )
    return " ".join(
        (
            product.get("model", ""),
            product.get("name", ""),
            product.get("category", ""),
            product.get("subcategory", ""),
            product.get("specs", ""),
            params,
        )
    ).lower()


def recommend_products(
    *,
    budget: int | None = None,
    category: str | None = None,
    use_case: str | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    normalized_category = _normalize_category(category)
    keywords = [
        item
        for item in (use_case or "").lower().replace("，", " ").split()
        if item
    ]

    candidates: list[tuple[float, dict[str, Any], list[str]]] = []
    for product in _products():
        price = int(product["price"])
        if budget is not None and price > budget:
            continue
        if normalized_category and product["category"] != normalized_category:
            continue
        if int(product.get("stock", 0)) <= 0:
            continue

        reasons: list[str] = []
        score = 0.0
        if budget is not None:
            if price <= budget:
                reasons.append("在预算内")
                score += 2
        text = _searchable(product)
        matched = [keyword for keyword in keywords if keyword in text]
        if matched:
            reasons.append(f"匹配需求：{'、'.join(matched)}")
            score += 3 * len(matched)
        if product.get("activity"):
            reasons.append(f"活动：{product['activity']}")
            score += 1.5
        if int(product.get("stock", 0)) > 10:
            reasons.append("库存充足")
            score += 1
        score += min(price, 2000) / 2000
        candidates.append((score, product, reasons))

    candidates.sort(key=lambda item: (-item[0], int(item[1]["price"])))
    results = [
        {
            "product_id": product["id"],
            "model": product["model"],
            "name": product["name"],
            "category": product["category"],
            "price": product["price"],
            "stock": product["stock"],
            "activity": product.get("activity"),
            "shipping": product.get("shipping"),
            "reasons": reasons,
        }
        for _, product, reasons in candidates[:limit]
    ]

    if not results:
        return {
            "found": False,
            "message": "没有找到符合条件的商品，可以放宽预算或换一个品类。",
            "query": {
                "budget": budget,
                "category": normalized_category,
                "use_case": use_case,
            },
        }
    return {
        "found": True,
        "count": len(results),
        "products": results,
        "query": {
            "budget": budget,
            "category": normalized_category,
            "use_case": use_case,
        },
    }
