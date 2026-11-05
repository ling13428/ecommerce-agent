from pathlib import Path

import pytest

from rag.chunk import MAX_CHILD, build_document
from rag.clean import DocumentError, parse_document

SAMPLE = """---
doc_id: T001
product_id: P2001
title: 测试耳机
doc_type: product_spec
category: 音频
source: 模拟商品资料
authority_level: 中
version: v1
effective_date: 2026-10-21
deprecated: false
---

> 模拟数据声明：本文档为测试数据。

# 测试耳机

## 基础参数

| 项目 | 说明 |
|---|---|
| 编号 | T001 |
| 连接 | 蓝牙 |

## 连接与兼容

- 支持手机连接。
- 支持平板连接。

## 常见问题

**Q：连不上怎么办？**
A：先重新配对。

**Q：支持双设备吗？**
A：以商品页说明为准。
"""


def _write(tmp_path: Path, content: str = SAMPLE) -> Path:
    path = tmp_path / "T001-spec.md"
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_document_reads_front_matter_and_cleans_body(tmp_path):
    document = parse_document(_write(tmp_path))

    assert document.doc_id == "T001"
    assert document.product_id == "P2001"
    assert document.meta["deprecated"] is False
    assert document.title == "测试耳机"
    assert all("模拟数据声明" not in block.text for block in document.blocks)


def test_build_document_creates_parent_and_child_links(tmp_path):
    document = parse_document(_write(tmp_path))
    parents, children, _ = build_document(document)

    assert len(parents) == 1
    assert parents[0].parent_id == "T001_P001"
    assert parents[0].child_ids == [child.chunk_id for child in children]
    assert {child.parent_id for child in children} == {"T001_P001"}
    assert len({child.chunk_id for child in children}) == len(children)
    assert all(child.text.startswith("P2001 测试耳机") for child in children)


def test_faq_pairs_are_not_merged(tmp_path):
    document = parse_document(_write(tmp_path))
    _, children, _ = build_document(document)

    faq_children = [child for child in children if child.unit_kind == "faq"]
    assert len(faq_children) == 2
    assert "连不上怎么办" in faq_children[0].text
    assert "支持双设备吗" in faq_children[1].text


def test_children_stay_within_hard_limit(tmp_path):
    long_section = "这是用于测试切片的句子。" * 40
    content = SAMPLE.replace(
        "- 支持手机连接。\n- 支持平板连接。",
        long_section,
    )
    document = parse_document(_write(tmp_path, content))
    _, children, warnings = build_document(document)

    assert children
    assert all(child.char_count <= MAX_CHILD for child in children)
    assert not any("超过" in warning for warning in warnings)


def test_long_document_splits_into_multiple_parents(tmp_path):
    sections = "\n\n".join(
        f"## 小节 {index}\n\n{'这是一段用于测试父块分组的说明文字。' * 30}"
        for index in range(1, 4)
    )
    content = SAMPLE.split("## 基础参数")[0] + sections
    document = parse_document(_write(tmp_path, content))
    parents, _, _ = build_document(document)

    assert len(parents) >= 2
    assert all(parent.char_count <= 1500 for parent in parents)


def test_operational_price_section_is_dropped(tmp_path):
    content = SAMPLE.replace(
        "## 连接与兼容",
        "## 关于价格与库存\n\n价格以商品页为准。\n\n## 连接与兼容",
    )
    document = parse_document(_write(tmp_path, content))

    assert document.dropped_sections == ["关于价格与库存"]
    assert all(block.h2 != "关于价格与库存" for block in document.blocks)


def test_price_leak_is_reported(tmp_path):
    content = SAMPLE.replace("| 连接 | 蓝牙 |", "| 价格 | 299 元 |")
    document = parse_document(_write(tmp_path, content))

    assert any("结构化事实泄漏" in warning for warning in document.warnings)


def test_invalid_doc_type_is_rejected(tmp_path):
    content = SAMPLE.replace("doc_type: product_spec", "doc_type: unknown")
    with pytest.raises(DocumentError):
        parse_document(_write(tmp_path, content))


def test_missing_field_is_rejected(tmp_path):
    content = SAMPLE.replace("authority_level: 中\n", "")
    with pytest.raises(DocumentError):
        parse_document(_write(tmp_path, content))
