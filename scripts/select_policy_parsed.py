from __future__ import annotations

import csv
import json
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag.clean import DocumentError, parse_document  # noqa: E402

PARSED_DIR = ROOT / "data" / "policies" / "parsed"
SELECTED_DIR = ROOT / "data" / "policies" / "selected"
REGISTRY = ROOT / "data" / "policies" / "registry.csv"
MANIFEST = SELECTED_DIR / "manifest.json"
README = SELECTED_DIR / "README.md"

SELECTIONS = {
    "RET-return-shipping-CSV.md": "退货运费标准，CSV 系列规范版本",
    "LOG-delivery-sla-CSV.md": "配送时效标准，CSV 系列规范版本",
    "PRI-price-protection-window-CSV.md": "价保期限表，CSV 系列规范版本",
    "TRD-trade-in-valuation-CSV.md": "以旧换新估价表，CSV 系列规范版本",
    "INV-invoice-types-CSV.md": "发票类型对比表，CSV 系列规范版本",
    "TRD-recycle-receipt-scan-PDF.md": "以旧换新回收单扫描件，PDF 为 JPG 的规范版本",
    "PLT-platform-notice-scan-PDF.md": "平台规则变更公告扫描件，PDF 为 JPG 的规范版本",
}


def _clear_selected() -> None:
    if SELECTED_DIR.exists():
        for path in SELECTED_DIR.glob("*.md"):
            path.unlink()


def _copy_and_validate() -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    errors: list[str] = []
    for filename, reason in SELECTIONS.items():
        source = PARSED_DIR / filename
        if not source.exists():
            errors.append(f"缺少解析文件：{source}")
            continue
        target = SELECTED_DIR / filename
        shutil.copy2(source, target)
        try:
            document = parse_document(target)
        except DocumentError as exc:
            errors.append(str(exc))
            continue
        docs.append(
            {
                "doc_id": document.doc_id,
                "file": filename,
                "source_file": document.meta.get("source_file", ""),
                "format": document.meta.get("source_format", ""),
                "doc_type": document.meta["doc_type"],
                "effective_date": document.meta.get("effective_date", ""),
                "valid_until": document.meta.get("valid_until", ""),
                "reason": reason,
            }
        )
    if errors:
        raise SystemExit("选择失败：" + chr(10) + chr(10).join(errors))
    return docs


def _write_manifest(docs: list[dict[str, Any]]) -> None:
    MANIFEST.write_text(
        json.dumps(
            {
                "generated_at": date.today().isoformat(),
                "source_dir": "data/policies/parsed",
                "selected_dir": "data/policies/selected",
                "documents": docs,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_readme(docs: list[dict[str, Any]]) -> None:
    lines = "\n".join(
        f"- `{doc['file']}`：{doc['reason']}" for doc in docs
    )
    README.write_text(
        f"""# 已选解析文档

本目录只放已经确认要进入 RAG 的解析文档，默认由 `scripts/build_chunks.py` 读取。

当前共 {len(docs)} 篇：

{lines}

## 选择原则

- CSV 作为表格的规范版本，跳过对应 XLSX。
- 扫描 PDF 作为扫描件的规范版本，跳过对应 JPG。
- HTML 与 CSV 重复时跳过 HTML。
- 文本 PDF、DOCX、PNG 暂不并入，避免和现有政策 Markdown 重复。

## 重新生成

```powershell
./.venv/Scripts/python.exe scripts/generate_policy_docs.py
./.venv/Scripts/python.exe scripts/parse_policy_raw.py --ocr
./.venv/Scripts/python.exe scripts/select_policy_parsed.py
./.venv/Scripts/python.exe scripts/build_chunks.py
./.venv/Scripts/python.exe scripts/embed_and_ingest.py --prune
```

`manifest.json` 记录每篇文档的 `doc_id`、原始文件、格式和选择原因。
""",
        encoding="utf-8",
    )


def _update_registry(docs: list[dict[str, Any]]) -> None:
    with REGISTRY.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0].keys()) if rows else []

    by_id = {row["file_id"]: row for row in rows}
    for doc in docs:
        row = by_id.get(doc["doc_id"])
        if row is None:
            continue
        row["status"] = "已入库"
        row["ingest_mode"] = "RAG（解析结果）"
        row["parsed_file"] = f"data/policies/selected/{doc['file']}"

    with REGISTRY.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    SELECTED_DIR.mkdir(parents=True, exist_ok=True)
    _clear_selected()
    docs = _copy_and_validate()
    _write_manifest(docs)
    _write_readme(docs)
    _update_registry(docs)

    print(f"已选择 {len(docs)} 篇解析文档 -> {SELECTED_DIR}")
    print(f"清单 -> {MANIFEST}")
    print(f"说明 -> {README}")
    print(f"注册表 -> {REGISTRY}")
    for doc in docs:
        print(f"  {doc['doc_id']} | {doc['file']} | {doc['doc_type']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
