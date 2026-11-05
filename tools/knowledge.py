from __future__ import annotations

from typing import Any

from rag.search import DEFAULT_TOP_K, SearchResult
from rag.search import search_knowledge as _search_rag
from tools.products import detect_product_id


def _payload(result: SearchResult, product_id: str | None) -> dict[str, Any]:
    found = bool(result.hits) and not result.abstained
    return {
        "found": found,
        "abstained": result.abstained,
        "reason": result.reason,
        "query": result.query,
        "product_id": product_id,
        "include_deprecated": result.include_deprecated,
        "top_score": (
            round(result.top_score, 4)
            if result.top_score is not None
            else None
        ),
        "results": [
            {
                "doc_id": hit.doc_id,
                "parent_id": hit.parent_id,
                "title": hit.title,
                "section": hit.section_path,
                "source": hit.metadata.get("source"),
                "authority_level": hit.metadata.get("authority_level"),
                "version": hit.metadata.get("version"),
                "effective_date": hit.metadata.get("effective_date"),
                "valid_until": hit.metadata.get("valid_until"),
                "deprecated": bool(hit.metadata.get("deprecated", False)),
                "policy_domain": hit.metadata.get("policy_domain"),
                "scope": hit.metadata.get("scope"),
                "region": hit.metadata.get("region"),
                "score": round(hit.score, 4),
                "fusion_score": (
                    round(hit.fusion_score, 4)
                    if hit.fusion_score is not None
                    else None
                ),
                "rerank_score": hit.rerank_score,
                "content": hit.parent_text,
            }
            for hit in result.hits
        ],
    }


def search_knowledge(
    query: str,
    product_id: str | None = None,
    top_k: int = DEFAULT_TOP_K,
    include_deprecated: bool = False,
) -> dict[str, Any]:
    effective_product_id = product_id or detect_product_id(query)
    result = _search_rag(
        query,
        top_k=top_k,
        product_id=effective_product_id,
        include_deprecated=include_deprecated,
    )
    return _payload(result, effective_product_id)
