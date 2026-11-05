from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
MULTI_BLANK_RE = re.compile(r"\n{3,}")
LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
DOC_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

REQUIRED_FIELDS = (
    "doc_id",
    "product_id",
    "title",
    "doc_type",
    "source",
    "authority_level",
    "version",
    "effective_date",
    "deprecated",
)
POLICY_DOC_TYPES = {
    "store_policy",
    "platform_rule",
    "policy_faq",
    "refusal_boundary",
    "policy_notice",
}
DOC_TYPES = {
    "product_overview",
    "product_spec",
    "product_faq",
    *POLICY_DOC_TYPES,
}
AUTHORITY_LEVELS = {"高", "中", "低"}
POLICY_SCOPES = {"STORE", "PLATFORM"}

LEAK_PATTERNS = (
    re.compile(r"[¥￥]\s*\d+"),
    re.compile(r"\d+(?:\.\d+)?\s*元"),
    re.compile(r"库存\s*[:：]?\s*\d+"),
    re.compile(r"(?:满|每满)\s*\d+\s*(?:减|优惠)"),
    re.compile(r"第[二2]件半价"),
    re.compile(r"赠(?:送)?表带"),
)
DROP_SECTIONS = {"关于价格与库存"}
META_DISCLAIMER_RE = re.compile(
    r"^(?:价格、库存|价格与库存).*(?:本文档|商品页|商品工具)"
)


class DocumentError(ValueError):
    pass


@dataclass
class Block:
    kind: str
    text: str
    h2: str = ""
    h3: str = ""


@dataclass
class Document:
    path: Path
    meta: dict[str, Any]
    title: str
    blocks: list[Block]
    dropped_sections: list[str] = field(default_factory=list)
    dropped_blocks: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def doc_id(self) -> str:
        return str(self.meta["doc_id"])

    @property
    def product_id(self) -> str:
        return str(self.meta["product_id"])


def _parse_scalar(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    return text


def _parse_front_matter(raw: str, name: str) -> tuple[dict[str, str], str]:
    match = FRONT_MATTER_RE.match(raw)
    if match is None:
        raise DocumentError(f"{name}: 缺少 YAML front matter")

    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise DocumentError(f"{name}: front matter 行格式错误：{stripped[:40]}")
        key, value = stripped.split(":", 1)
        key = key.strip()
        if not key:
            raise DocumentError(f"{name}: front matter 存在空字段名")
        meta[key] = _parse_scalar(value)

    return meta, raw[match.end() :]


def _validate_meta(meta: dict[str, str], name: str) -> dict[str, Any]:
    missing = [field for field in REQUIRED_FIELDS if not str(meta.get(field, "")).strip()]
    if missing:
        raise DocumentError(f"{name}: front matter 缺少字段 {', '.join(missing)}")

    doc_id = str(meta["doc_id"]).strip()
    if not DOC_ID_RE.match(doc_id):
        raise DocumentError(f"{name}: doc_id 只能包含字母、数字、下划线和短横线")

    doc_type = str(meta["doc_type"]).strip()
    if doc_type not in DOC_TYPES:
        raise DocumentError(
            f"{name}: doc_type={doc_type} 非法，允许 {sorted(DOC_TYPES)}"
        )

    authority = str(meta["authority_level"]).strip()
    if authority not in AUTHORITY_LEVELS:
        raise DocumentError(
            f"{name}: authority_level={authority} 非法，允许 {sorted(AUTHORITY_LEVELS)}"
        )

    deprecated_raw = str(meta["deprecated"]).strip().lower()
    if deprecated_raw not in {"true", "false"}:
        raise DocumentError(f"{name}: deprecated 必须是 true 或 false")
    deprecated = deprecated_raw == "true"

    effective_date = str(meta["effective_date"]).strip()
    try:
        datetime.strptime(effective_date, "%Y-%m-%d")
    except ValueError as exc:
        raise DocumentError(
            f"{name}: effective_date={effective_date} 必须是 YYYY-MM-DD"
        ) from exc

    normalized: dict[str, Any] = {key: str(value).strip() for key, value in meta.items()}
    normalized["doc_id"] = doc_id
    normalized["doc_type"] = doc_type
    normalized["authority_level"] = authority
    normalized["deprecated"] = deprecated
    normalized["effective_date"] = effective_date
    return normalized


def _clean_body(body: str) -> str:
    text = HTML_COMMENT_RE.sub("", body)
    lines: list[str] = []
    for line in text.split("\n"):
        line = line.replace("\xa0", " ").rstrip()
        if re.match(r"^\s*>\s*模拟数据声明", line):
            continue
        lines.append(line)
    text = "\n".join(lines)
    return MULTI_BLANK_RE.sub("\n\n", text).strip()


def _classify(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "paragraph"
    if all(line.startswith("|") for line in lines):
        return "table"
    if all(LIST_RE.match(line) for line in lines):
        return "list"
    if lines[0].startswith("**Q") or re.match(r"^Q\s*[:：]", lines[0]):
        return "faq"
    return "paragraph"


def _parse_blocks(body: str, fallback_title: str) -> tuple[str, list[Block]]:
    title = ""
    h2 = ""
    h3 = ""
    buffer: list[str] = []
    blocks: list[Block] = []

    def flush() -> None:
        nonlocal buffer
        text = "\n".join(buffer).strip()
        if text:
            blocks.append(Block(kind=_classify(text), text=text, h2=h2, h3=h3))
        buffer = []

    for line in body.split("\n"):
        heading = HEADING_RE.match(line)
        if heading is not None:
            flush()
            level = len(heading.group(1))
            heading_text = heading.group(2).strip()
            if level == 1:
                title = heading_text
            elif level == 2:
                h2, h3 = heading_text, ""
            elif level == 3:
                h3 = heading_text
            continue
        if not line.strip():
            flush()
        else:
            buffer.append(line)
    flush()

    return title or fallback_title, blocks


def _check_leaks(blocks: list[Block], name: str) -> list[str]:
    warnings: list[str] = []
    for block in blocks:
        for line in block.text.splitlines():
            for pattern in LEAK_PATTERNS:
                if pattern.search(line):
                    warnings.append(
                        f"{name}: 疑似结构化事实泄漏：{line.strip()[:60]}"
                    )
                    break
    return warnings


def _check_product(meta: dict[str, Any], name: str) -> list[str]:
    try:
        from tools.products import PRODUCTS
    except Exception:
        return []
    product_id = str(meta["product_id"])
    if product_id in POLICY_SCOPES:
        if meta["doc_type"] not in POLICY_DOC_TYPES:
            return [
                f"{name}: 商品文档不能使用 product_id={product_id}，"
                "店铺/平台政策请使用 policy doc_type"
            ]
        return []
    if product_id not in PRODUCTS:
        return [f"{name}: product_id={product_id} 不在当前商品库中"]
    return []


def parse_document(path: Path) -> Document:
    raw = path.read_text(encoding="utf-8-sig")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    meta_raw, body_raw = _parse_front_matter(raw, path.name)
    meta = _validate_meta(meta_raw, path.name)
    body = _clean_body(body_raw)
    title, blocks = _parse_blocks(body, str(meta["title"]))

    dropped_sections: list[str] = []
    dropped_blocks = 0
    kept_blocks: list[Block] = []
    for block in blocks:
        if block.h2 in DROP_SECTIONS:
            if block.h2 not in dropped_sections:
                dropped_sections.append(block.h2)
            continue
        if META_DISCLAIMER_RE.match(block.text):
            dropped_blocks += 1
            continue
        kept_blocks.append(block)
    blocks = kept_blocks

    if not blocks:
        raise DocumentError(f"{path.name}: 正文为空或缺少有效内容")

    if meta["doc_type"] in POLICY_DOC_TYPES:
        warnings = _check_product(meta, path.name)
    else:
        warnings = _check_leaks(blocks, path.name) + _check_product(
            meta, path.name
        )
    return Document(
        path=path,
        meta=meta,
        title=title,
        blocks=blocks,
        dropped_sections=dropped_sections,
        dropped_blocks=dropped_blocks,
        warnings=warnings,
    )
