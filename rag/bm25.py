from __future__ import annotations

import logging
import math
import threading
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from core.config import get_settings
from rag.tokenize import tokenize

logger = logging.getLogger("ecommerce_agent.bm25")

_DOCUMENT_SQL = """
SELECT
    c.chunk_id,
    c.parent_id,
    c.doc_id,
    c.product_id,
    c.title,
    c.section_path,
    c.unit_kind,
    c.content,
    c.metadata AS chunk_metadata,
    p.metadata AS parent_metadata
FROM knowledge_chunks AS c
JOIN knowledge_parents AS p ON p.parent_id = c.parent_id
"""

_VERSION_SQL = "SELECT version FROM knowledge_state WHERE id = 1"

_index_cache: dict[str, tuple[float, int | None, "BM25Index"]] = {}
_index_lock = threading.Lock()


@dataclass(frozen=True)
class BM25Document:
    chunk_id: str
    parent_id: str
    doc_id: str
    product_id: str
    title: str
    section_path: str
    unit_kind: str
    content: str
    metadata: dict[str, Any]


def _is_deprecated(metadata: dict[str, Any]) -> bool:
    value = metadata.get("deprecated", False)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _searchable_text(document: BM25Document) -> str:
    return " ".join(
        (
            document.product_id,
            document.title,
            document.section_path,
            document.content,
        )
    )


def _read_documents(conn: Any) -> list[BM25Document]:
    documents: list[BM25Document] = []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_DOCUMENT_SQL)
        for row in cur.fetchall():
            metadata = dict(row.get("parent_metadata") or {})
            metadata.update(row.get("chunk_metadata") or {})
            documents.append(
                BM25Document(
                    chunk_id=str(row["chunk_id"]),
                    parent_id=str(row["parent_id"]),
                    doc_id=str(row["doc_id"]),
                    product_id=str(row["product_id"]),
                    title=str(row["title"]),
                    section_path=str(row["section_path"]),
                    unit_kind=str(row["unit_kind"]),
                    content=str(row["content"]),
                    metadata=metadata,
                )
            )
    return documents


def _load_documents(
    database_url: str, connection: Any | None = None
) -> list[BM25Document]:
    if connection is not None:
        return _read_documents(connection)
    with psycopg.connect(database_url) as conn:
        return _read_documents(conn)


def _read_index_version(
    connection: Any | None, database_url: str
) -> int | None:
    try:
        if connection is not None:
            row = connection.execute(_VERSION_SQL).fetchone()
        else:
            with psycopg.connect(database_url) as conn:
                row = conn.execute(_VERSION_SQL).fetchone()
    except psycopg.errors.UndefinedTable:
        logger.warning("knowledge_state 表不存在，BM25 仅按 TTL 刷新")
        if connection is not None:
            connection.rollback()
        return None
    except psycopg.Error as exc:
        logger.warning("读取 BM25 索引版本失败：%s", exc)
        if connection is not None:
            connection.rollback()
        return None
    return int(row[0]) if row else None


class _BM25:
    def __init__(
        self, corpus: list[list[str]], *, k1: float = 1.5, b: float = 0.75
    ) -> None:
        self.k1 = k1
        self.b = b
        self.documents = len(corpus)
        self.term_freqs = [Counter(tokens) for tokens in corpus]
        self.doc_lengths = [len(tokens) for tokens in corpus]
        self.average_length = (
            sum(self.doc_lengths) / self.documents if self.documents else 0.0
        )

        document_freq: Counter[str] = Counter()
        for frequencies in self.term_freqs:
            document_freq.update(frequencies.keys())
        self.idf = {
            term: math.log(
                1.0
                + (self.documents - frequency + 0.5)
                / (frequency + 0.5)
            )
            for term, frequency in document_freq.items()
        }

    def get_scores(self, query_tokens: list[str]) -> list[float]:
        scores = [0.0] * self.documents
        if not self.documents or self.average_length <= 0:
            return scores

        for term in query_tokens:
            idf = self.idf.get(term)
            if idf is None:
                continue
            for index, frequencies in enumerate(self.term_freqs):
                term_frequency = frequencies.get(term, 0)
                if not term_frequency:
                    continue
                length = self.doc_lengths[index]
                denominator = term_frequency + self.k1 * (
                    1.0 - self.b + self.b * length / self.average_length
                )
                scores[index] += (
                    idf * term_frequency * (self.k1 + 1.0) / denominator
                )
        return scores


class BM25Index:
    def __init__(self, documents: list[BM25Document]) -> None:
        self.documents = documents
        self._bm25: _BM25 | None = None
        if not documents:
            return
        corpus = [tokenize(_searchable_text(document)) for document in documents]
        if not any(corpus):
            return
        self._bm25 = _BM25(corpus, k1=1.5, b=0.75)

    @property
    def available(self) -> bool:
        return self._bm25 is not None

    def search(
        self,
        query: str,
        *,
        top_k: int,
        product_id: str | None = None,
        include_deprecated: bool = False,
    ) -> list[tuple[str, float]]:
        if self._bm25 is None:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []

        scores = self._bm25.get_scores(tokens)
        ranked: list[tuple[str, float]] = []
        for document, score in zip(self.documents, scores, strict=False):
            if not include_deprecated and _is_deprecated(document.metadata):
                continue
            if product_id and document.product_id not in (
                product_id,
                "STORE",
                "PLATFORM",
            ):
                continue
            value = float(score)
            if value <= 0:
                continue
            ranked.append((document.chunk_id, value))

        ranked.sort(key=lambda item: (-item[1], item[0]))
        return ranked[:top_k]


def _get_index(
    database_url: str, connection: Any | None = None
) -> BM25Index:
    settings = get_settings()
    ttl = settings.rag_bm25_index_ttl
    version = _read_index_version(connection, database_url)
    now = time.monotonic()

    with _index_lock:
        cached = _index_cache.get(database_url)
        if cached is not None:
            built_at, cached_version, index = cached
            if version is not None:
                if cached_version == version:
                    return index
            elif ttl > 0 and now - built_at < ttl:
                return index

        documents = _load_documents(database_url, connection)
        index = BM25Index(documents)
        _index_cache[database_url] = (time.monotonic(), version, index)
        logger.info(
            "BM25 索引已加载：%d 条子块（version=%s）",
            len(documents),
            version,
        )
        return index


def warmup_bm25(database_url: str | None = None) -> None:
    url = database_url or get_settings().database_url
    try:
        index = _get_index(url)
    except Exception as exc:
        logger.warning("BM25 预热失败，首次检索时重试：%s", exc)
        return
    logger.info("BM25 预热完成：可检索=%s", index.available)


def invalidate_index(database_url: str | None = None) -> None:
    with _index_lock:
        if database_url is None:
            _index_cache.clear()
        else:
            _index_cache.pop(database_url, None)


def search_bm25(
    query: str,
    *,
    top_k: int,
    product_id: str | None = None,
    include_deprecated: bool = False,
    database_url: str | None = None,
    connection: Any | None = None,
) -> list[tuple[str, float]]:
    if not query.strip():
        return []
    url = database_url or get_settings().database_url
    try:
        index = _get_index(url, connection)
    except Exception as exc:
        logger.warning("BM25 索引加载失败，回退纯稠密检索：%s", exc)
        if connection is not None:
            connection.rollback()
        return []
    return index.search(
        query,
        top_k=top_k,
        product_id=product_id,
        include_deprecated=include_deprecated,
    )
