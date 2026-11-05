from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from rag.clean import Block, Document

TARGET_CHILD_MIN = 100
TARGET_CHILD_MAX = 400
MAX_CHILD = 500
MAX_PARENT = 1200
HARD_MAX_PARENT = 1500

TABLE_SEPARATOR_RE = re.compile(r"^\|?\s*:?-{3,}")


@dataclass
class Segment:
    h2: str
    h3: str
    blocks: list[Block]
    part: int = 1


@dataclass
class Unit:
    text: str
    kind: str


@dataclass
class Parent:
    parent_id: str
    doc_id: str
    product_id: str
    title: str
    section_path: str
    text: str
    char_count: int
    child_ids: list[str]
    metadata: dict[str, Any]

    def to_record(self) -> dict[str, Any]:
        return {
            "parent_id": self.parent_id,
            "doc_id": self.doc_id,
            "product_id": self.product_id,
            "title": self.title,
            "section_path": self.section_path,
            "text": self.text,
            "char_count": self.char_count,
            "child_ids": self.child_ids,
            **self.metadata,
        }


@dataclass
class Child:
    chunk_id: str
    parent_id: str
    doc_id: str
    product_id: str
    title: str
    section_path: str
    unit_kind: str
    text: str
    char_count: int
    metadata: dict[str, Any]

    def to_record(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "parent_id": self.parent_id,
            "doc_id": self.doc_id,
            "product_id": self.product_id,
            "title": self.title,
            "section_path": self.section_path,
            "unit_kind": self.unit_kind,
            "text": self.text,
            "char_count": self.char_count,
            **self.metadata,
        }


def build_segments(doc: Document) -> list[Segment]:
    segments: list[Segment] = []
    for block in doc.blocks:
        if segments and (segments[-1].h2, segments[-1].h3) == (block.h2, block.h3):
            segments[-1].blocks.append(block)
        else:
            segments.append(Segment(h2=block.h2, h3=block.h3, blocks=[block]))
    return segments


def _render_segment(segment: Segment) -> str:
    lines: list[str] = []
    if segment.h2:
        lines.append(f"## {segment.h2}")
    if segment.h3:
        lines.append(f"### {segment.h3}")
    for block in segment.blocks:
        lines.append(block.text)
    return "\n\n".join(line for line in lines if line.strip())


def _parent_text(doc: Document, segments: list[Segment]) -> str:
    parts = [f"# {doc.title}"]
    parts.extend(_render_segment(segment) for segment in segments)
    return "\n\n".join(part for part in parts if part.strip())


def _split_oversized_segment(segment: Segment) -> list[Segment]:
    parts: list[Segment] = []
    buffer: list[Block] = []
    length = 0
    for block in segment.blocks:
        block_len = len(block.text) + 2
        if buffer and length + block_len > MAX_PARENT:
            parts.append(Segment(segment.h2, segment.h3, buffer))
            buffer, length = [], 0
        buffer.append(block)
        length += block_len
    if buffer:
        parts.append(Segment(segment.h2, segment.h3, buffer))
    for index, part in enumerate(parts, 1):
        part.part = index
    return parts or [segment]


def _group_segments(doc: Document, segments: list[Segment]) -> list[list[Segment]]:
    if len(_parent_text(doc, segments)) <= MAX_PARENT:
        return [segments]

    expanded: list[Segment] = []
    for segment in segments:
        if len(_render_segment(segment)) > MAX_PARENT:
            expanded.extend(_split_oversized_segment(segment))
        else:
            expanded.append(segment)

    groups: list[list[Segment]] = []
    current: list[Segment] = []
    current_len = 0
    for segment in expanded:
        segment_len = len(_render_segment(segment)) + 2
        if current and current_len + segment_len > MAX_PARENT:
            groups.append(current)
            current, current_len = [], 0
        current.append(segment)
        current_len += segment_len
    if current:
        groups.append(current)

    if len(groups) > 1:
        last_len = sum(len(_render_segment(s)) + 2 for s in groups[-1])
        prev_len = sum(len(_render_segment(s)) + 2 for s in groups[-2])
        if last_len < TARGET_CHILD_MIN * 4 and prev_len + last_len <= MAX_PARENT:
            groups[-2].extend(groups.pop())
    return groups


def _parent_path(doc: Document, segments: list[Segment]) -> str:
    names: list[str] = []
    for segment in segments:
        if segment.h2 and segment.h2 not in names:
            names.append(segment.h2)
    path = doc.title if not names else f"{doc.title} > {' / '.join(names)}"
    if any(segment.part > 1 for segment in segments):
        path += "（分节）"
    return path


def _split_table(text: str) -> list[str]:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    has_separator = len(lines) > 1 and bool(
        TABLE_SEPARATOR_RE.match(lines[1].replace(" ", ""))
    )
    header = lines[:2] if has_separator else lines[:1]
    rows = lines[2:] if has_separator else lines[1:]
    if not rows:
        return [text]

    parts: list[str] = []
    current = list(header)
    current_len = sum(len(line) + 1 for line in current)
    for row in rows:
        if len(current) > len(header) and current_len + len(row) + 1 > MAX_CHILD:
            parts.append("\n".join(current))
            current = list(header)
            current_len = sum(len(line) + 1 for line in current)
        current.append(row)
        current_len += len(row) + 1
    if len(current) > len(header):
        parts.append("\n".join(current))
    return parts or [text]


def _split_list(text: str) -> list[str]:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    parts: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        if current and current_len + len(line) + 1 > MAX_CHILD:
            parts.append("\n".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        parts.append("\n".join(current))
    return parts or [text]


def _split_sentences(text: str) -> list[str]:
    sentences = [
        sentence.strip()
        for sentence in re.findall(r"[^。！？；!?;\n]+[。！？；!?;]?", text)
        if sentence.strip()
    ]
    if not sentences:
        return [text]
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > TARGET_CHILD_MAX:
            parts.append(current)
            current = ""
        current += sentence
    if current:
        parts.append(current)
    return parts


def _expand_blocks(blocks: list[Block]) -> list[Unit]:
    units: list[Unit] = []
    for block in blocks:
        if len(block.text) <= MAX_CHILD:
            units.append(Unit(block.text, block.kind))
            continue
        if block.kind == "table":
            units.extend(Unit(part, "table") for part in _split_table(block.text))
        elif block.kind == "list":
            units.extend(Unit(part, "list") for part in _split_list(block.text))
        else:
            units.extend(
                Unit(part, block.kind) for part in _split_sentences(block.text)
            )
    return units


@dataclass
class _BufferItem:
    segment: Segment
    text: str
    kind: str


def _unique_segments(items: list[_BufferItem]) -> list[Segment]:
    unique: list[Segment] = []
    for item in items:
        if not any(item.segment is segment for segment in unique):
            unique.append(item.segment)
    return unique


def _multi_section_body(items: list[_BufferItem]) -> str:
    lines: list[str] = []
    current_h2 = ""
    current_h3 = ""
    for item in items:
        segment = item.segment
        if segment.h2 != current_h2:
            if segment.h2:
                lines.append(f"## {segment.h2}")
            current_h2 = segment.h2
            current_h3 = ""
        if segment.h3 and segment.h3 != current_h3:
            lines.append(f"### {segment.h3}")
            current_h3 = segment.h3
        lines.append(item.text)
    return "\n\n".join(line for line in lines if line.strip())


def _child_prefix(doc: Document, segment: Segment) -> str:
    parts = [f"{doc.product_id} {doc.title}"]
    if segment.h2:
        parts.append(segment.h2)
    if segment.h3:
        parts.append(segment.h3)
    return " > ".join(parts)


def _base_metadata(doc: Document) -> dict[str, Any]:
    keys = (
        "doc_type",
        "category",
        "source",
        "authority_level",
        "version",
        "effective_date",
        "deprecated",
        "policy_domain",
        "region",
        "scope",
        "valid_until",
        "review_date",
        "supersedes",
        "superseded_by",
        "source_file",
        "source_format",
        "parser",
        "parsed_at",
        "page_count",
        "ocr_model",
        "duplicate_of",
    )
    return {key: doc.meta[key] for key in keys if key in doc.meta}


def _build_children(
    doc: Document,
    segments: list[Segment],
    parent_id: str,
    start_index: int,
) -> list[Child]:
    children: list[Child] = []
    buffer: list[_BufferItem] = []
    buffer_len = 0
    index = start_index
    metadata = _base_metadata(doc)

    def add_child(path: str, body: str, kind: str) -> None:
        nonlocal index
        index += 1
        text = f"{path}\n\n{body}"
        children.append(
            Child(
                chunk_id=f"{doc.doc_id}_C{index:03d}",
                parent_id=parent_id,
                doc_id=doc.doc_id,
                product_id=doc.product_id,
                title=doc.title,
                section_path=path,
                unit_kind=kind,
                text=text,
                char_count=len(text),
                metadata=metadata,
            )
        )

    def flush() -> None:
        nonlocal buffer, buffer_len
        if not buffer:
            return
        unique = _unique_segments(buffer)
        if len(unique) == 1:
            path = _child_prefix(doc, unique[0])
            body = "\n\n".join(item.text for item in buffer)
        else:
            path = f"{doc.product_id} {doc.title}"
            names: list[str] = []
            for segment in unique:
                if segment.h2 and segment.h2 not in names:
                    names.append(segment.h2)
            if names:
                path += " > " + " / ".join(names)
            body = _multi_section_body(buffer)
        kinds = {item.kind for item in buffer}
        kind = kinds.pop() if len(kinds) == 1 else "section"
        add_child(path, body, kind)
        buffer, buffer_len = [], 0

    for segment in segments:
        prefix = _child_prefix(doc, segment)
        for unit in _expand_blocks(segment.blocks):
            if unit.kind in {"faq", "table"}:
                flush()
                add_child(prefix, unit.text, unit.kind)
                continue

            if (
                children
                and children[-1].unit_kind == "faq"
                and children[-1].section_path == prefix
                and children[-1].char_count + len(unit.text) + 2 <= TARGET_CHILD_MAX
            ):
                children[-1].text = f"{children[-1].text}\n\n{unit.text}"
                children[-1].char_count = len(children[-1].text)
                continue

            if buffer:
                new_segment = not any(
                    item.segment is segment for item in buffer
                )
                if new_segment:
                    if len(_unique_segments(buffer)) >= 2:
                        flush()
                    else:
                        buffer_len += len(segment.h2) + 6
                        if segment.h3:
                            buffer_len += len(segment.h3) + 7
            if buffer and buffer_len + len(unit.text) + 2 > TARGET_CHILD_MAX:
                flush()
            buffer.append(_BufferItem(segment, unit.text, unit.kind))
            buffer_len += len(unit.text) + 2
    flush()
    return children


def build_document(
    doc: Document,
) -> tuple[list[Parent], list[Child], list[str]]:
    segments = build_segments(doc)
    if not segments:
        raise ValueError(f"{doc.path.name}: 没有可切片的正文")

    parents: list[Parent] = []
    children: list[Child] = []
    warnings = list(doc.warnings)
    short_children = 0
    child_index = 0
    metadata = _base_metadata(doc)

    for index, group in enumerate(_group_segments(doc, segments), 1):
        parent_id = f"{doc.doc_id}_P{index:03d}"
        path = _parent_path(doc, group)
        text = _parent_text(doc, group)
        if len(text) > HARD_MAX_PARENT:
            warnings.append(
                f"{doc.path.name}: 父块 {parent_id} 长度 {len(text)} 超过 {HARD_MAX_PARENT}"
            )

        new_children = _build_children(doc, group, parent_id, child_index)
        child_index += len(new_children)
        for child in new_children:
            if child.char_count > MAX_CHILD:
                warnings.append(
                    f"{doc.path.name}: 子块 {child.chunk_id} 长度 {child.char_count} 超过 {MAX_CHILD}"
                )
            elif child.char_count < TARGET_CHILD_MIN and child.unit_kind not in {
                "faq",
                "table",
            }:
                short_children += 1

        parents.append(
            Parent(
                parent_id=parent_id,
                doc_id=doc.doc_id,
                product_id=doc.product_id,
                title=doc.title,
                section_path=path,
                text=text,
                char_count=len(text),
                child_ids=[child.chunk_id for child in new_children],
                metadata=metadata,
            )
        )
        children.extend(new_children)

    if short_children:
        warnings.append(
            f"{doc.path.name}: {short_children} 个子块短于 {TARGET_CHILD_MIN} 字"
        )
    return parents, children, warnings
