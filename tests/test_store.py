import json

import pytest

from rag.store import IngestError, load_jsonl, validate_inputs


def _parent(parent_id: str = "D001_P001") -> dict:
    return {
        "parent_id": parent_id,
        "doc_id": "D001",
        "product_id": "P2001",
        "title": "测试商品",
        "section_path": "测试商品",
        "text": "父块内容",
        "char_count": 4,
        "child_ids": ["D001_C001"],
    }


def _child(chunk_id: str = "D001_C001", parent_id: str = "D001_P001") -> dict:
    return {
        "chunk_id": chunk_id,
        "parent_id": parent_id,
        "doc_id": "D001",
        "product_id": "P2001",
        "title": "测试商品",
        "section_path": "测试商品",
        "unit_kind": "paragraph",
        "text": "子块内容",
        "char_count": 4,
    }


def test_validate_inputs_accepts_valid_records():
    validate_inputs([_parent()], [_child()])


def test_validate_inputs_rejects_missing_parent():
    with pytest.raises(IngestError, match="不存在的父块"):
        validate_inputs([_parent()], [_child(parent_id="D999_P001")])


def test_validate_inputs_rejects_duplicate_chunk_id():
    with pytest.raises(IngestError, match="chunk_id 重复"):
        validate_inputs([_parent()], [_child(), _child()])


def test_validate_inputs_rejects_missing_field():
    parent = _parent()
    parent.pop("title")
    with pytest.raises(IngestError, match="缺少字段"):
        validate_inputs([parent], [_child()])


def test_load_jsonl_reads_objects(tmp_path):
    path = tmp_path / "chunks.jsonl"
    path.write_text(
        json.dumps(_child(), ensure_ascii=False) + "\n\n", encoding="utf-8"
    )

    records = load_jsonl(path)

    assert records == [_child()]


def test_load_jsonl_reports_invalid_line(tmp_path):
    path = tmp_path / "chunks.jsonl"
    path.write_text("{not json}\n", encoding="utf-8")

    with pytest.raises(IngestError, match="第 1 行"):
        load_jsonl(path)
