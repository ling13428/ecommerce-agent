from __future__ import annotations

from typing import Any

from services.recommend import recommend_products as _recommend


def recommend_products(
    budget: int | None = None,
    category: str | None = None,
    use_case: str | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    return _recommend(
        budget=budget,
        category=category,
        use_case=use_case,
        limit=limit,
    )
