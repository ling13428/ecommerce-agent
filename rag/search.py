from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

import psycopg
from openai import OpenAI
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from core.config import get_settings
from rag.bm25 import search_bm25
from rag.embedding import embed_query
from rag.rerank import rerank_documents

logger = logging.getLogger("ecommerce_agent.search")

DEFAULT_TOP_K = 5
DEFAULT_MIN_SCORE = 0.55
CANDIDATE_MULTIPLIER = 4
MIN_CANDIDATES = 20


class SearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    parent_id: str
    doc_id: str
    product_id: str
    title: str
    section_path: str
    unit_kind: str
    text: str
    parent_text: str
    score: float
    metadata: dict[str, Any]
    fusion_score: float | None = None
    rerank_score: float | None = None

    @property
    def citation(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "parent_id": self.parent_id,
            "title": self.title,
            "section": self.section_path,
            "source": self.metadata.get("source"),
            "authority_level": self.metadata.get("authority_level"),
            "version": self.metadata.get("version"),
            "effective_date": self.metadata.get("effective_date"),
            "valid_until": self.metadata.get("valid_until"),
            "policy_domain": self.metadata.get("policy_domain"),
            "region": self.metadata.get("region"),
            "scope": self.metadata.get("scope"),
            "deprecated": bool(self.metadata.get("deprecated", False)),
        }


@dataclass(frozen=True)
class SearchResult:
    query: str
    hits: list[SearchHit]
    abstained: bool
    reason: str | None
    min_score: float
    include_deprecated: bool = False
    dense_top_score: float | None = None

    @property
    def top_score(self) -> float | None:
        if self.dense_top_score is not None:
            return self.dense_top_score
        return self.hits[0].score if self.hits else None

    def citations(self) -> list[dict[str, Any]]:
        return [hit.citation for hit in self.hits]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "abstained": self.abstained,
            "reason": self.reason,
            "min_score": self.min_score,
            "include_deprecated": self.include_deprecated,
            "dense_top_score": self.dense_top_score,
            "hits": [
                {
                    "chunk_id": hit.chunk_id,
                    "parent_id": hit.parent_id,
                    "doc_id": hit.doc_id,
                    "product_id": hit.product_id,
                    "title": hit.title,
                    "section": hit.section_path,
                    "unit_kind": hit.unit_kind,
                    "score": round(hit.score, 4),
                    "fusion_score": (
                        round(hit.fusion_score, 4)
                        if hit.fusion_score is not None
                        else None
                    ),
                    "rerank_score": hit.rerank_score,
                    "text": hit.text,
                    "parent_text": hit.parent_text,
                    "citation": hit.citation,
                    "metadata": hit.metadata,
                }
                for hit in self.hits
            ],
        }


SEARCH_SQL_TEMPLATE = """
SELECT
    c.chunk_id,
    c.parent_id,
    c.doc_id,
    c.product_id,
    c.title,
    c.section_path,
    c.unit_kind,
    c.content AS chunk_text,
    c.metadata AS chunk_metadata,
    p.content AS parent_text,
    p.metadata AS parent_metadata,
    1 - (c.embedding <=> %s) AS score
FROM knowledge_chunks AS c
JOIN knowledge_parents AS p ON p.parent_id = c.parent_id
{where}
ORDER BY c.embedding <=> %s
LIMIT %s
"""

FETCH_BY_IDS_SQL = """
SELECT
    c.chunk_id,
    c.parent_id,
    c.doc_id,
    c.product_id,
    c.title,
    c.section_path,
    c.unit_kind,
    c.content AS chunk_text,
    c.metadata AS chunk_metadata,
    p.content AS parent_text,
    p.metadata AS parent_metadata,
    0.0 AS score
FROM knowledge_chunks AS c
JOIN knowledge_parents AS p ON p.parent_id = c.parent_id
WHERE c.chunk_id = ANY(%s)
"""


def _validate(top_k: int, candidate_k: int, min_score: float) -> None:
    if top_k < 1:
        raise SearchError("top_k 必须大于 0")
    if candidate_k < top_k:
        raise SearchError(
            f"candidate_k 不能小于 top_k：{candidate_k} < {top_k}"
        )
    if not 0 <= min_score <= 1:
        raise SearchError("min_score 必须在 0 到 1 之间")


def _fetch_rows(
    connection: Any,
    vector: Vector,
    limit: int,
    product_id: str | None,
    include_deprecated: bool = False,
) -> list[dict[str, Any]]:
    params: list[Any] = [vector]
    conditions: list[str] = []
    if product_id:
        conditions.append(
            "(c.product_id = %s OR c.scope_kind IN ('store', 'platform'))"
        )
        params.append(product_id)
    if not include_deprecated:
        conditions.append(
            "COALESCE((c.metadata->>'deprecated')::boolean, "
            "(p.metadata->>'deprecated')::boolean, false) = false"
        )
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.extend([vector, limit])

    with connection.cursor(row_factory=dict_row) as cur:
        cur.execute(SEARCH_SQL_TEMPLATE.format(where=where), params)
        return list(cur.fetchall())


def _fetch_rows_by_ids(
    connection: Any, chunk_ids: list[str]
) -> list[dict[str, Any]]:
    if not chunk_ids:
        return []
    with connection.cursor(row_factory=dict_row) as cur:
        cur.execute(FETCH_BY_IDS_SQL, [chunk_ids])
        return list(cur.fetchall())


def _row_to_hit(row: dict[str, Any]) -> SearchHit:
    metadata = dict(row.get("parent_metadata") or {})
    metadata.update(row.get("chunk_metadata") or {})
    return SearchHit(
        chunk_id=str(row["chunk_id"]),
        parent_id=str(row["parent_id"]),
        doc_id=str(row["doc_id"]),
        product_id=str(row["product_id"]),
        title=str(row["title"]),
        section_path=str(row["section_path"]),
        unit_kind=str(row["unit_kind"]),
        text=str(row["chunk_text"]),
        parent_text=str(row["parent_text"]),
        score=float(row["score"]),
        metadata=metadata,
    )


def _dedupe_by_parent(hits: list[SearchHit], top_k: int) -> list[SearchHit]:
    seen: set[str] = set()
    unique: list[SearchHit] = []
    for hit in hits:
        if hit.parent_id in seen:
            continue
        seen.add(hit.parent_id)
        unique.append(hit)
        if len(unique) >= top_k:
            break
    return unique


def _fuse_rrf(
    dense_ids: list[str], sparse_ids: list[str], rrf_k: int
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for rank, chunk_id in enumerate(dense_ids, 1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)
    for rank, chunk_id in enumerate(sparse_ids, 1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def _rerank_text(hit: SearchHit) -> str:
    return f"{hit.title} {hit.section_path}\n{hit.text}"


def _apply_rerank(
    query: str, hits: list[SearchHit], top_k: int
) -> list[SearchHit]:
    ranking = rerank_documents(query, [_rerank_text(hit) for hit in hits])
    if not ranking:
        return hits[:top_k]
    reranked = [
        replace(hits[index], rerank_score=score)
        for index, score in ranking
        if 0 <= index < len(hits)
    ]
    return reranked[:top_k]


def _hybrid_hits(
    connection: Any,
    query: str,
    dense_hits: list[SearchHit],
    *,
    product_id: str | None,
    include_deprecated: bool,
    database_url: str,
    sparse_k: int,
    rrf_k: int,
    dedupe_limit: int,
) -> list[SearchHit]:
    dense_ids = [hit.chunk_id for hit in dense_hits]
    sparse_ids = [
        chunk_id
        for chunk_id, _ in search_bm25(
            query,
            top_k=sparse_k,
            product_id=product_id,
            include_deprecated=include_deprecated,
            database_url=database_url,
            connection=connection,
        )
    ]
    fused = _fuse_rrf(dense_ids, sparse_ids, rrf_k)
    if not fused:
        return []

    rows = _fetch_rows_by_ids(connection, [chunk_id for chunk_id, _ in fused])
    rows_by_id = {str(row["chunk_id"]): row for row in rows}
    dense_scores = {hit.chunk_id: hit.score for hit in dense_hits}

    hits: list[SearchHit] = []
    for chunk_id, fusion_score in fused:
        row = rows_by_id.get(chunk_id)
        if row is None:
            continue
        hits.append(
            replace(
                _row_to_hit(row),
                score=dense_scores.get(chunk_id, 0.0),
                fusion_score=fusion_score,
            )
        )

    return _dedupe_by_parent(hits, dedupe_limit)


def search_knowledge(
    query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    candidate_k: int | None = None,
    min_score: float | None = None,
    product_id: str | None = None,
    include_deprecated: bool = False,
    hybrid: bool | None = None,
    rerank: bool | None = None,
    database_url: str | None = None,
    client: OpenAI | None = None,
    connection: Any | None = None,
) -> SearchResult:
    text = query.strip()
    if not text:
        raise SearchError("查询不能为空")

    settings = get_settings()
    if min_score is None:
        min_score = settings.rag_min_score

    dense_k = candidate_k or max(
        top_k * CANDIDATE_MULTIPLIER, MIN_CANDIDATES
    )
    _validate(top_k, dense_k, min_score)

    use_hybrid = (
        settings.rag_hybrid_enabled if hybrid is None else hybrid
    ) and connection is None
    use_rerank = (
        settings.rerank_enabled if rerank is None else rerank
    ) and connection is None

    vector = Vector(embed_query(text, client=client))

    dense_top: float | None = None
    hits: list[SearchHit] = []

    if connection is not None:
        rows = _fetch_rows(
            connection, vector, dense_k, product_id, include_deprecated
        )
        dense_hits = [_row_to_hit(row) for row in rows]
        dense_top = max((hit.score for hit in dense_hits), default=None)
        hits = _dedupe_by_parent(dense_hits, top_k)
    else:
        url = database_url or settings.database_url
        with psycopg.connect(url) as conn:
            register_vector(conn)
            rows = _fetch_rows(
                conn, vector, dense_k, product_id, include_deprecated
            )
            dense_hits = [_row_to_hit(row) for row in rows]
            dense_top = max((hit.score for hit in dense_hits), default=None)

            if use_hybrid:
                dedupe_limit = max(
                    settings.rerank_top_n if use_rerank else top_k, top_k
                )
                hits = _hybrid_hits(
                    conn,
                    text,
                    dense_hits,
                    product_id=product_id,
                    include_deprecated=include_deprecated,
                    database_url=url,
                    sparse_k=settings.rag_sparse_candidates,
                    rrf_k=settings.rag_rrf_k,
                    dedupe_limit=dedupe_limit,
                )
            else:
                hits = _dedupe_by_parent(dense_hits, top_k)

    if use_rerank and hits:
        hits = _apply_rerank(text, hits, top_k)
    else:
        hits = hits[:top_k]

    if not hits:
        return SearchResult(
            query=text,
            hits=[],
            abstained=True,
            reason="无检索结果",
            min_score=min_score,
            include_deprecated=include_deprecated,
            dense_top_score=dense_top,
        )

    abstained = dense_top is None or dense_top < min_score
    if dense_top is None:
        reason = "无稠密召回"
    elif abstained:
        reason = f"最高相似度 {dense_top:.3f} 低于阈值 {min_score:.2f}"
    else:
        reason = None

    logger.debug(
        "检索完成 query=%r hits=%d dense_top=%s abstained=%s hybrid=%s rerank=%s",
        text,
        len(hits),
        f"{dense_top:.3f}" if dense_top is not None else None,
        abstained,
        use_hybrid,
        use_rerank,
    )
    return SearchResult(
        query=text,
        hits=hits,
        abstained=abstained,
        reason=reason,
        min_score=min_score,
        include_deprecated=include_deprecated,
        dense_top_score=dense_top,
    )
