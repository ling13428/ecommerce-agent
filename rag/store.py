from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

PARENT_COLUMNS = (
    "parent_id",
    "doc_id",
    "product_id",
    "title",
    "section_path",
    "text",
    "char_count",
    "child_ids",
)
CHUNK_COLUMNS = (
    "chunk_id",
    "parent_id",
    "doc_id",
    "product_id",
    "title",
    "section_path",
    "unit_kind",
    "text",
    "char_count",
)


class IngestError(RuntimeError):
    pass


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise IngestError(f"{path.name} 第 {line_no} 行不是合法 JSON") from exc
            if not isinstance(record, dict):
                raise IngestError(f"{path.name} 第 {line_no} 行必须是 JSON 对象")
            records.append(record)
    return records


def _require(record: dict[str, Any], keys: tuple[str, ...], label: str) -> None:
    missing = [key for key in keys if key not in record or record[key] is None]
    if missing:
        identifier = record.get("parent_id") or record.get("chunk_id") or "?"
        raise IngestError(f"{label} {identifier} 缺少字段：{', '.join(missing)}")


def validate_inputs(
    parents: list[dict[str, Any]],
    children: list[dict[str, Any]],
) -> None:
    if not parents:
        raise IngestError("没有父块数据")
    if not children:
        raise IngestError("没有子块数据")

    parent_ids: set[str] = set()
    for parent in parents:
        _require(parent, PARENT_COLUMNS, "父块")
        parent_id = str(parent["parent_id"])
        if parent_id in parent_ids:
            raise IngestError(f"父块 parent_id 重复：{parent_id}")
        parent_ids.add(parent_id)

    chunk_ids: set[str] = set()
    for child in children:
        _require(child, CHUNK_COLUMNS, "子块")
        chunk_id = str(child["chunk_id"])
        if chunk_id in chunk_ids:
            raise IngestError(f"子块 chunk_id 重复：{chunk_id}")
        chunk_ids.add(chunk_id)
        parent_id = str(child["parent_id"])
        if parent_id not in parent_ids:
            raise IngestError(
                f"子块 {chunk_id} 引用了不存在的父块 {parent_id}"
            )


def _metadata(record: dict[str, Any], columns: tuple[str, ...]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key not in columns}


def _parent_row(record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        record["parent_id"],
        record["doc_id"],
        record["product_id"],
        record["title"],
        record["section_path"],
        record["text"],
        int(record["char_count"]),
        Jsonb(_metadata(record, PARENT_COLUMNS)),
    )


def _chunk_row(
    record: dict[str, Any], embedding: list[float]
) -> tuple[Any, ...]:
    return (
        record["chunk_id"],
        record["parent_id"],
        record["doc_id"],
        record["product_id"],
        record["title"],
        record["section_path"],
        record["unit_kind"],
        record["text"],
        int(record["char_count"]),
        Vector(embedding),
        Jsonb(_metadata(record, CHUNK_COLUMNS)),
    )


PARENT_UPSERT = """
INSERT INTO knowledge_parents (
    parent_id, doc_id, product_id, title, section_path, content, char_count, metadata
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (parent_id) DO UPDATE SET
    doc_id = EXCLUDED.doc_id,
    product_id = EXCLUDED.product_id,
    title = EXCLUDED.title,
    section_path = EXCLUDED.section_path,
    content = EXCLUDED.content,
    char_count = EXCLUDED.char_count,
    metadata = EXCLUDED.metadata
"""

BUMP_INDEX_VERSION = """
INSERT INTO knowledge_state (id, version, updated_at)
VALUES (1, 1, now())
ON CONFLICT (id) DO UPDATE SET
    version = knowledge_state.version + 1,
    updated_at = now()
"""

CHUNK_UPSERT = """
INSERT INTO knowledge_chunks (
    chunk_id, parent_id, doc_id, product_id, title, section_path,
    unit_kind, content, char_count, embedding, metadata
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (chunk_id) DO UPDATE SET
    parent_id = EXCLUDED.parent_id,
    doc_id = EXCLUDED.doc_id,
    product_id = EXCLUDED.product_id,
    title = EXCLUDED.title,
    section_path = EXCLUDED.section_path,
    unit_kind = EXCLUDED.unit_kind,
    content = EXCLUDED.content,
    char_count = EXCLUDED.char_count,
    embedding = EXCLUDED.embedding,
    metadata = EXCLUDED.metadata
"""


def upsert_knowledge(
    parents: list[dict[str, Any]],
    children: list[dict[str, Any]],
    embeddings: list[list[float]],
    database_url: str,
    prune: bool = False,
) -> dict[str, int]:
    validate_inputs(parents, children)
    if len(children) != len(embeddings):
        raise IngestError(
            f"子块与向量数量不一致：{len(children)} vs {len(embeddings)}"
        )

    parent_rows = [_parent_row(parent) for parent in parents]
    chunk_rows = [
        _chunk_row(child, embedding)
        for child, embedding in zip(children, embeddings, strict=True)
    ]

    with psycopg.connect(database_url) as conn:
        register_vector(conn)
        with conn.transaction():
            with conn.cursor() as cur:
                cur.executemany(PARENT_UPSERT, parent_rows)
                cur.executemany(CHUNK_UPSERT, chunk_rows)

                if prune:
                    parent_ids = [row[0] for row in parent_rows]
                    chunk_ids = [row[0] for row in chunk_rows]
                    cur.execute(
                        "DELETE FROM knowledge_chunks "
                        "WHERE NOT (chunk_id = ANY(%s))",
                        (chunk_ids,),
                    )
                    cur.execute(
                        "DELETE FROM knowledge_parents "
                        "WHERE NOT (parent_id = ANY(%s))",
                        (parent_ids,),
                    )

                cur.execute(BUMP_INDEX_VERSION)

        parent_row = conn.execute(
            "SELECT count(*) FROM knowledge_parents"
        ).fetchone()
        chunk_row = conn.execute(
            "SELECT count(*) FROM knowledge_chunks"
        ).fetchone()
        parent_count = parent_row[0] if parent_row else 0
        chunk_count = chunk_row[0] if chunk_row else 0

    return {
        "parents": int(parent_count),
        "chunks": int(chunk_count),
        "input_parents": len(parents),
        "input_chunks": len(children),
    }
