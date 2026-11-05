from __future__ import annotations

import argparse
import base64
import csv
import difflib
import hashlib
import io
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RAW_DIR = ROOT / "data" / "policies" / "raw"
POLICY_DOCS_DIR = ROOT / "data" / "policies" / "docs"
PARSED_DIR = ROOT / "data" / "policies" / "parsed"
REGISTRY = ROOT / "data" / "policies" / "registry.csv"
REPORT_JSON = PARSED_DIR / "parse_report.json"
REPORT_CSV = PARSED_DIR / "parse_report.csv"
OCR_CACHE = PARSED_DIR / "ocr_cache.json"
PARSED_AT = date.today().isoformat()

OCR_PROMPT = (
    "请逐行转写图片中的中文文字，保留标题、编号、项目符号和表格结构。"
    "表格请输出为 Markdown 表格；不要解释，不要补充图片中没有的内容。"
)
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

TITLES = {
    "RET-return-shipping": "退货运费标准",
    "LOG-delivery-sla": "配送时效标准",
    "PRI-price-protection-window": "价格保护期限表",
    "TRD-trade-in-valuation": "以旧换新估价表",
    "INV-invoice-types": "发票类型对比表",
    "RET-policy-v2": "退换货政策（2026 版）",
    "INV-invoice-guide": "发票开具指南",
    "LOG-service-agreement": "物流服务协议",
    "PRI-price-protection": "价格保护规则",
    "TRD-trade-in-agreement": "以旧换新服务协议",
    "RET-return-flow": "退换货流程",
    "LOG-delivery-map": "配送时效参考",
    "TRD-trade-in-flow": "以旧换新流程",
    "TRD-recycle-receipt-scan": "以旧换新回收单（扫描件）",
    "PLT-platform-notice-scan": "星潮商城规则变更公告（扫描件）",
}

BATCH_ONE = {".csv", ".xlsx", ".docx", ".html", ".pdf"}
FRONT_KEYS = (
    "doc_id",
    "product_id",
    "title",
    "doc_type",
    "category",
    "source",
    "authority_level",
    "version",
    "effective_date",
    "valid_until",
    "deprecated",
    "policy_domain",
    "region",
    "scope",
    "source_file",
    "source_format",
    "parser",
    "parsed_at",
    "page_count",
    "ocr_model",
    "duplicate_of",
)


class SkipError(RuntimeError):
    pass


def _md_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _md_table(headers: list[Any], rows: list[list[Any]]) -> str:
    if not headers:
        return ""
    head = "| " + " | ".join(_md_cell(cell) for cell in headers) + " |"
    separator = "|" + "|".join(["---"] * len(headers)) + "|"
    body = [
        "| " + " | ".join(_md_cell(cell) for cell in row) + " |"
        for row in rows
        if any(_md_cell(cell) for cell in row)
    ]
    return "\n".join([head, separator, *body])


def _normalize_rel(value: str) -> str:
    return value.replace("\\", "/").lstrip("/")


def _load_registry() -> list[dict[str, str]]:
    with REGISTRY.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _find_row(rows: list[dict[str, str]], path: Path) -> dict[str, str] | None:
    rel = _normalize_rel(str(path.relative_to(RAW_DIR.parent)))
    for row in rows:
        if _normalize_rel(row.get("file_name", "")) == rel:
            return row
    return None


def _title(path: Path, row: dict[str, str] | None) -> str:
    if path.stem in TITLES:
        return TITLES[path.stem]
    if row and row.get("note"):
        return row["note"].split("；")[0]
    return path.stem


def _front_matter(meta: dict[str, Any]) -> str:
    lines = ["---"]
    for key in FRONT_KEYS:
        value = meta.get(key, "")
        if value not in (None, ""):
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def _source_note(meta: dict[str, Any]) -> str:
    return (
        f"本文件由 `{meta['source_file']}`（{meta['source_format']}）解析生成，"
        f"解析器为 {meta['parser']}，解析时间 {meta['parsed_at']}。"
        f"原始文件属于{meta['policy_domain']}领域，适用范围为{meta['region']}，"
        f"生效日期 {meta['effective_date']}，失效日期 {meta['valid_until']}。"
        "解析结果仅用于本地 RAG 演示，具体条款以原始文件和店铺最新公告为准。"
    )


def _render(meta: dict[str, Any], body: str) -> str:
    note = _source_note(meta)
    return f"{_front_matter(meta)}\n\n{body}\n\n## 来源说明\n\n{note}\n"


def _compose(meta: dict[str, Any], title: str, body: str) -> str:
    if body.lstrip().startswith("# "):
        return _render(meta, body)
    return _render(meta, f"# {title}\n\n{body}")


def _parse_csv(path: Path) -> tuple[str, dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        raise ValueError("CSV 为空")
    headers = rows[0]
    data = rows[1:]
    table = _md_table(headers, data)
    return f"## 表格内容\n\n{table}", {"table_rows": len(data)}


def _parse_xlsx(path: Path) -> tuple[str, dict[str, Any]]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    sections: list[str] = []
    table_rows = 0
    for sheet in workbook.worksheets:
        rows = [
            list(row)
            for row in sheet.iter_rows(values_only=True)
            if any(cell not in (None, "") for cell in row)
        ]
        if not rows:
            continue
        headers = rows[0]
        data = rows[1:]
        table_rows += len(data)
        sections.append(
            f"## {sheet.title}\n\n{_md_table(headers, data)}"
        )
    workbook.close()
    if not sections:
        raise ValueError("XLSX 没有可解析的表格")
    return "\n\n".join(sections), {"table_rows": table_rows}


def _parse_docx(path: Path) -> tuple[str, dict[str, Any]]:
    from docx import Document

    document = Document(path)
    sections: list[str] = []
    table_rows = 0
    title = ""

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style = paragraph.style.name if paragraph.style else ""
        if style.startswith("Heading"):
            try:
                level = int(style.split()[-1])
            except ValueError:
                level = 2
            level = min(max(level, 1), 6)
            if not title:
                title = text
            sections.append(f"{'#' * level} {text}")
        else:
            sections.append(text)

    for index, table in enumerate(document.tables, 1):
        rows = [[cell.text for cell in row.cells] for row in table.rows]
        if not rows:
            continue
        table_rows += max(len(rows) - 1, 0)
        sections.append(f"## 表格 {index}\n\n{_md_table(rows[0], rows[1:])}")

    if not sections:
        raise ValueError("DOCX 没有可解析的正文")
    return "\n\n".join(sections), {"table_rows": table_rows, "doc_title": title}


def _parse_html(path: Path) -> tuple[str, dict[str, Any]]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml")
    sections: list[str] = []
    heading = soup.find(["h1", "h2"])
    if heading and heading.get_text(strip=True):
        sections.append(f"# {heading.get_text(strip=True)}")
    table_rows = 0
    for index, table in enumerate(soup.find_all("table"), 1):
        rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = [
                cell.get_text(" ", strip=True)
                for cell in tr.find_all(["th", "td"])
            ]
            if cells:
                rows.append(cells)
        if not rows:
            continue
        table_rows += max(len(rows) - 1, 0)
        sections.append(f"## 表格 {index}\n\n{_md_table(rows[0], rows[1:])}")
    if not sections:
        text = soup.get_text("\n", strip=True)
        if not text:
            raise ValueError("HTML 没有可解析的正文")
        sections.append(text)
    return "\n\n".join(sections), {"table_rows": table_rows}


def _reflow(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    paragraphs: list[str] = []
    buffer = ""
    for line in lines:
        if not buffer:
            buffer = line
        elif buffer.endswith(("。", "！", "？", "；", "：", ".", "!", "?")):
            paragraphs.append(buffer)
            buffer = line
        else:
            buffer += line
    if buffer:
        paragraphs.append(buffer)
    return paragraphs


def _parse_pdf(path: Path) -> tuple[str, dict[str, Any]]:
    import pdfplumber

    sections: list[str] = []
    text_chars = 0
    table_rows = 0
    page_count = 0
    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        for page_number, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            text_chars += len(text.strip())
            tables = page.extract_tables() or []
            if not text.strip() and not tables:
                continue
            sections.append(f"## 第 {page_number} 页")
            for paragraph in _reflow(text):
                sections.append(paragraph)
            for table in tables:
                if not table:
                    continue
                rows = [
                    [" ".join(str(cell or "").split()) for cell in row]
                    for row in table
                ]
                table_rows += max(len(rows) - 1, 0)
                sections.append(_md_table(rows[0], rows[1:]))
    if text_chars < 20:
        raise SkipError("无文本层，疑似扫描件，留待 OCR")
    return "\n\n".join(sections), {
        "table_rows": table_rows,
        "page_count": page_count,
        "text_chars": text_chars,
    }


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[A-Za-z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _load_ocr_cache() -> dict[str, str]:
    if not OCR_CACHE.exists():
        return {}
    try:
        return json.loads(OCR_CACHE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_ocr_cache(cache: dict[str, str]) -> None:
    OCR_CACHE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _ocr_client():
    from openai import OpenAI

    from core.config import get_settings

    settings = get_settings()
    if not settings.ocr_configured:
        raise RuntimeError(
            "OCR 未配置：请设置 OCR_API_KEY 或 EMBEDDING_API_KEY"
        )
    key = settings.effective_ocr_api_key
    return (
        OpenAI(
            api_key=key.get_secret_value(),
            base_url=settings.effective_ocr_base_url,
            timeout=settings.ocr_timeout,
            max_retries=0,
        ),
        settings.ocr_model,
    )


def _ocr_image_bytes(
    data: bytes,
    mime: str,
    cache: dict[str, str],
    client: Any,
    model: str,
) -> str:
    cache_key = hashlib.sha256(
        data + model.encode("utf-8") + OCR_PROMPT.encode("utf-8")
    ).hexdigest()
    if cache_key in cache:
        return cache[cache_key]

    encoded = base64.b64encode(data).decode("ascii")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": OCR_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{encoded}"},
                    },
                ],
            }
        ],
        temperature=0,
        max_tokens=2000,
    )
    text = _strip_code_fence(response.choices[0].message.content or "")
    if not text:
        raise RuntimeError("OCR 返回为空")
    cache[cache_key] = text
    return text


def _parse_image(
    path: Path,
    client: Any,
    model: str,
    cache: dict[str, str],
) -> tuple[str, dict[str, Any]]:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    text = _ocr_image_bytes(path.read_bytes(), mime, cache, client, model)
    return f"## OCR 转写\n\n{text}", {
        "ocr_model": model,
        "text_chars": len(text),
        "page_count": 1,
    }


def _parse_pdf_ocr(
    path: Path,
    client: Any,
    model: str,
    cache: dict[str, str],
) -> tuple[str, dict[str, Any]]:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(path))
    sections: list[str] = []
    text_chars = 0
    try:
        for index in range(len(document)):
            page = document[index]
            bitmap = page.render(scale=2.0)
            image = bitmap.to_pil()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            text = _ocr_image_bytes(
                buffer.getvalue(), "image/png", cache, client, model
            )
            text_chars += len(text)
            sections.append(f"## 第 {index + 1} 页\n\n{text}")
    finally:
        document.close()
    if text_chars == 0:
        raise RuntimeError("OCR 未识别出文字")
    return "\n\n".join(sections), {
        "ocr_model": model,
        "text_chars": text_chars,
        "page_count": len(sections),
    }


def _body_without_front_matter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2]
    return text


def _normalized(text: str) -> str:
    return re.sub(r"\s+", "", _body_without_front_matter(text))


def _load_reference_docs() -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for path in sorted(POLICY_DOCS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8-sig")
        docs.append(
            {
                "doc_id": path.stem,
                "text": _normalized(text),
                "hash": hashlib.sha256(_normalized(text).encode("utf-8")).hexdigest(),
            }
        )
    return docs


def _find_duplicate(
    text: str,
    references: list[dict[str, str]],
    threshold: float = 0.9,
) -> tuple[str, float]:
    normalized = _normalized(text)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    best_id = ""
    best_score = 0.0
    sample = normalized[:4000]
    for reference in references:
        if reference["hash"] == digest:
            return reference["doc_id"], 1.0
        other = reference["text"][:4000]
        if not other:
            continue
        score = difflib.SequenceMatcher(None, sample, other).ratio()
        if score > best_score:
            best_score = score
            best_id = reference["doc_id"]
    if best_score >= threshold:
        return best_id, best_score
    return "", best_score


def _meta_for(
    path: Path,
    row: dict[str, str],
    title: str,
    parser: str,
    extra: dict[str, Any],
) -> dict[str, Any]:
    platform = row.get("domain") == "平台规则"
    return {
        "doc_id": row["file_id"],
        "product_id": "PLATFORM" if platform else "STORE",
        "title": f"{title}（{row.get('format', path.suffix.upper()[1:])} 解析）",
        "doc_type": "platform_rule" if platform else "store_policy",
        "category": row.get("domain", ""),
        "source": f"{row.get('source', '')}·解析",
        "authority_level": row.get("authority_level", "高"),
        "version": row.get("version", "v1"),
        "effective_date": row.get("effective_date", ""),
        "valid_until": row.get("valid_until", ""),
        "deprecated": row.get("deprecated", "false"),
        "policy_domain": row.get("domain", ""),
        "region": "全国",
        "scope": "平台" if platform else "店铺",
        "source_file": _normalize_rel(str(path.relative_to(ROOT))),
        "source_format": row.get("format", path.suffix.upper()[1:]),
        "parser": parser,
        "parsed_at": PARSED_AT,
        "page_count": extra.get("page_count", ""),
        "ocr_model": extra.get("ocr_model", ""),
        "duplicate_of": extra.get("duplicate_of", ""),
    }


def _record_row(
    meta: dict[str, Any],
    parsed_file: str,
    status: str,
    extra: dict[str, Any],
    error: str = "",
) -> dict[str, Any]:
    return {
        "file_id": meta.get("doc_id", ""),
        "source_file": meta.get("source_file", ""),
        "format": meta.get("source_format", ""),
        "parser": meta.get("parser", ""),
        "status": status,
        "parsed_file": parsed_file,
        "duplicate_of": extra.get("duplicate_of", ""),
        "similarity": round(float(extra.get("similarity", 0.0)), 4),
        "char_count": int(extra.get("char_count", 0)),
        "table_rows": int(extra.get("table_rows", 0)),
        "page_count": int(extra.get("page_count", 0)),
        "ocr_model": meta.get("ocr_model", ""),
        "error": error,
    }


def _write_reports(records: list[dict[str, Any]]) -> None:
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    totals = {
        "files": len(records),
        "parsed": sum(1 for row in records if row["status"].startswith("已解析")),
        "duplicates": sum(
            1 for row in records if "重复" in row["status"]
        ),
        "skipped": sum(1 for row in records if row["status"].startswith("待OCR")),
        "errors": sum(
            1 for row in records if row["status"] in {"解析失败", "OCR失败"}
        ),
    }
    REPORT_JSON.write_text(
        json.dumps(
            {"generated_at": PARSED_AT, "totals": totals, "files": records},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with REPORT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "file_id",
                "source_file",
                "format",
                "parser",
                "status",
                "parsed_file",
                "duplicate_of",
                "similarity",
                "char_count",
                "table_rows",
                "page_count",
                "ocr_model",
                "error",
            ],
        )
        writer.writeheader()
        writer.writerows(records)


def _update_registry(rows: list[dict[str, str]], records: list[dict[str, Any]]) -> None:
    by_file = {_normalize_rel(row.get("file_name", "")): row for row in rows}
    for record in records:
        key = _normalize_rel(record["source_file"]).replace("data/policies/", "", 1)
        row = by_file.get(key)
        if row is None:
            continue
        row["status"] = record["status"]
        row["parsed_file"] = record["parsed_file"]
        row["parser"] = record["parser"]
        row["duplicate_of"] = record["duplicate_of"]
        if record["status"].startswith("已解析"):
            row["ingest_mode"] = (
                "RAG（解析后待入库）"
                if "重复" not in record["status"]
                else "不重复入库"
            )
        elif record["status"].startswith("待OCR"):
            row["ingest_mode"] = "待OCR"

    with REGISTRY.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = list(rows[0].keys()) if rows else []
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _sort_key(path: Path) -> tuple[int, str]:
    priority = {".csv": 0, ".xlsx": 1, ".docx": 2, ".html": 3, ".pdf": 4}
    return (priority.get(path.suffix.lower(), 9), str(path))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    argument_parser = argparse.ArgumentParser(
        description="解析政策原始文件：第一批结构化格式 + 第二批 OCR"
    )
    argument_parser.add_argument(
        "--ocr",
        action="store_true",
        help="启用第二批 OCR（PNG/JPG/扫描 PDF）",
    )
    args = argument_parser.parse_args()
    enable_ocr = args.ocr

    ocr_client = None
    ocr_model = ""
    ocr_cache: dict[str, str] = {}
    if enable_ocr:
        try:
            ocr_client, ocr_model = _ocr_client()
        except Exception as exc:
            print(f"OCR 初始化失败：{type(exc).__name__}: {exc}")
            return 2
        ocr_cache = _load_ocr_cache()

    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    for path in PARSED_DIR.glob("*.md"):
        path.unlink()

    rows = _load_registry()
    references = _load_reference_docs()
    records: list[dict[str, Any]] = []

    for path in sorted(RAW_DIR.rglob("*"), key=_sort_key):
        if not path.is_file():
            continue
        row = _find_row(rows, path)
        if row is None:
            continue
        suffix = path.suffix.lower()
        is_image = suffix in IMAGE_SUFFIXES
        if suffix not in BATCH_ONE and not (enable_ocr and is_image):
            records.append(
                {
                    "file_id": row["file_id"],
                    "source_file": _normalize_rel(str(path.relative_to(ROOT))),
                    "format": row.get("format", suffix.upper()[1:]),
                    "parser": "OCR（未执行）",
                    "status": "待OCR（第二批）",
                    "parsed_file": "",
                    "duplicate_of": "",
                    "similarity": 0.0,
                    "char_count": 0,
                    "table_rows": 0,
                    "page_count": 0,
                    "error": "图片/扫描件留待第二批 OCR",
                }
            )
            continue

        title = _title(path, row)
        try:
            if suffix == ".csv":
                body, extra = _parse_csv(path)
                parser = "csv"
            elif suffix == ".xlsx":
                body, extra = _parse_xlsx(path)
                parser = "openpyxl"
            elif suffix == ".docx":
                body, extra = _parse_docx(path)
                parser = "python-docx"
            elif suffix == ".html":
                body, extra = _parse_html(path)
                parser = "BeautifulSoup"
            elif is_image:
                body, extra = _parse_image(
                    path, ocr_client, ocr_model, ocr_cache
                )
                parser = ocr_model
            elif suffix == ".pdf":
                try:
                    body, extra = _parse_pdf(path)
                    parser = "pdfplumber"
                except SkipError:
                    if not enable_ocr:
                        raise
                    body, extra = _parse_pdf_ocr(
                        path, ocr_client, ocr_model, ocr_cache
                    )
                    parser = ocr_model
            else:
                raise SkipError("暂不支持的格式")
            extra["char_count"] = len(_normalized(body))
            meta = _meta_for(path, row, title, parser, extra)
            output_name = f"{path.stem}-{row.get('format', suffix.upper()[1:])}.md"
            output_path = PARSED_DIR / output_name
            output_text = _compose(meta, title, body)
            output_path.write_text(output_text, encoding="utf-8")
            duplicate_of, similarity = _find_duplicate(output_text, references)
            extra["duplicate_of"] = duplicate_of
            extra["similarity"] = similarity
            if duplicate_of:
                status = "已解析（重复，未入库）"
                meta["duplicate_of"] = duplicate_of
                output_text = _compose(meta, title, body)
                output_path.write_text(output_text, encoding="utf-8")
            else:
                status = "已解析（待入库）"
            references.append(
                {
                    "doc_id": meta["doc_id"],
                    "text": _normalized(output_text),
                    "hash": hashlib.sha256(
                        _normalized(output_text).encode("utf-8")
                    ).hexdigest(),
                }
            )
            records.append(
                _record_row(
                    meta,
                    _normalize_rel(str(output_path.relative_to(ROOT))),
                    status,
                    extra,
                )
            )
        except SkipError as exc:
            records.append(
                {
                    "file_id": row["file_id"],
                    "source_file": _normalize_rel(str(path.relative_to(ROOT))),
                    "format": row.get("format", suffix.upper()[1:]),
                    "parser": "qwen-vl-ocr" if enable_ocr else "pdfplumber",
                    "status": "待OCR（第二批）",
                    "parsed_file": "",
                    "duplicate_of": "",
                    "similarity": 0.0,
                    "char_count": 0,
                    "table_rows": 0,
                    "page_count": 0,
                    "error": str(exc),
                }
            )
        except Exception as exc:
            ocr_attempted = is_image or (suffix == ".pdf" and enable_ocr)
            records.append(
                {
                    "file_id": row["file_id"],
                    "source_file": _normalize_rel(str(path.relative_to(ROOT))),
                    "format": row.get("format", suffix.upper()[1:]),
                    "parser": ocr_model if ocr_attempted else suffix.lstrip("."),
                    "status": "OCR失败" if ocr_attempted else "解析失败",
                    "parsed_file": "",
                    "duplicate_of": "",
                    "similarity": 0.0,
                    "char_count": 0,
                    "table_rows": 0,
                    "page_count": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    if enable_ocr:
        _save_ocr_cache(ocr_cache)

    _update_registry(rows, records)
    _write_reports(records)

    parsed = [row for row in records if row["status"].startswith("已解析")]
    duplicates = [row for row in records if "重复" in row["status"]]
    skipped = [row for row in records if row["status"].startswith("待OCR")]
    failed = [
        row for row in records if row["status"] in {"解析失败", "OCR失败"}
    ]

    print(f"解析完成：{len(parsed)} 个文件")
    print(f"  其中重复：{len(duplicates)} 个")
    print(f"  待 OCR：{len(skipped)} 个")
    print(f"  失败：{len(failed)} 个")
    print(f"解析结果 -> {PARSED_DIR}")
    print(f"报告 -> {REPORT_JSON}")
    print(f"注册表 -> {REGISTRY}")
    for row in records:
        if row["status"] != "待OCR（第二批）":
            print(
                f"  [{row['status']}] {row['file_id']} "
                f"({row['format']}, chars={row['char_count']}, "
                f"dup={row['duplicate_of'] or '-'}, sim={row['similarity']})"
            )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
