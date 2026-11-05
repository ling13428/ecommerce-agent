from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag.chunk import (  # noqa: E402
    MAX_CHILD,
    MAX_PARENT,
    TARGET_CHILD_MAX,
    TARGET_CHILD_MIN,
    build_document,
)
from rag.clean import Document, DocumentError, parse_document  # noqa: E402


def _stats(values: list[int]) -> dict[str, float | int]:
    if not values:
        return {"min": 0, "avg": 0, "max": 0}
    return {
        "min": min(values),
        "avg": round(sum(values) / len(values), 1),
        "max": max(values),
    }


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_corpus(input_dirs: list[Path], output_dir: Path) -> dict[str, Any]:
    documents: list[Document] = []
    parents: list[dict[str, Any]] = []
    children: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    per_document: list[dict[str, Any]] = []
    seen_ids: dict[str, str] = {}

    paths: list[Path] = []
    for input_dir in input_dirs:
        for path in sorted(input_dir.glob("*.md")):
            if path.name.lower() == "readme.md":
                continue
            paths.append(path)

    for path in paths:
        try:
            document = parse_document(path)
            if document.doc_id in seen_ids:
                raise DocumentError(
                    f"{path.name}: doc_id={document.doc_id} 与 {seen_ids[document.doc_id]} 重复"
                )
            seen_ids[document.doc_id] = path.name
            doc_parents, doc_children, doc_warnings = build_document(document)
        except DocumentError as exc:
            errors.append(str(exc))
            continue

        documents.append(document)
        parents.extend(parent.to_record() for parent in doc_parents)
        children.extend(child.to_record() for child in doc_children)
        warnings.extend(doc_warnings)
        per_document.append(
            {
                "doc_id": document.doc_id,
                "title": document.title,
                "product_id": document.product_id,
                "doc_type": document.meta["doc_type"],
                "parents": len(doc_parents),
                "chunks": len(doc_children),
                "parent_chars": [parent.char_count for parent in doc_parents],
                "child_chars": [child.char_count for child in doc_children],
                "dropped_sections": document.dropped_sections,
                "dropped_blocks": document.dropped_blocks,
                "warnings": doc_warnings,
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "parents.jsonl", parents)
    _write_jsonl(output_dir / "chunks.jsonl", children)

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_dirs": [str(path) for path in input_dirs],
        "output_dir": str(output_dir),
        "thresholds": {
            "child_min": TARGET_CHILD_MIN,
            "child_target_max": TARGET_CHILD_MAX,
            "child_hard_max": MAX_CHILD,
            "parent_target_max": MAX_PARENT,
        },
        "totals": {
            "documents": len(documents),
            "parents": len(parents),
            "chunks": len(children),
            "errors": len(errors),
            "warnings": len(warnings),
        },
        "lengths": {
            "parent": _stats([parent["char_count"] for parent in parents]),
            "child": _stats([child["char_count"] for child in children]),
        },
        "documents": per_document,
        "errors": errors,
        "warnings": warnings,
    }

    report_path = output_dir / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def _print_report(report: dict[str, Any]) -> None:
    totals = report["totals"]
    lengths = report["lengths"]
    print(
        f"完成：{totals['documents']} 篇文档 -> "
        f"{totals['parents']} 个父块 / {totals['chunks']} 个子块"
    )
    print(
        "父块长度 min/avg/max："
        f"{lengths['parent']['min']}/{lengths['parent']['avg']}/{lengths['parent']['max']}"
    )
    print(
        "子块长度 min/avg/max："
        f"{lengths['child']['min']}/{lengths['child']['avg']}/{lengths['child']['max']}"
    )
    if report["errors"]:
        print(f"失败 {len(report['errors'])} 篇：")
        for error in report["errors"]:
            print(f"  - {error}")
    if report["warnings"]:
        print(f"警告 {len(report['warnings'])} 条，详见 report.json")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="清洗并切片商品/政策文档（结构感知 + 父子块）")
    parser.add_argument(
        "--input",
        type=Path,
        nargs="+",
        default=[
            ROOT / "data" / "products" / "docs",
            ROOT / "data" / "policies" / "docs",
            ROOT / "data" / "policies" / "selected",
        ],
        help="Markdown 文档目录，可传多个；默认商品 + 政策 + 已选解析文档",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "processed",
        help="输出目录（parents.jsonl / chunks.jsonl / report.json）",
    )
    args = parser.parse_args(argv)

    input_dirs = [path for path in args.input if path.exists()]
    if not input_dirs:
        print("没有可用的输入目录")
        return 2
    missing = [str(path) for path in args.input if not path.exists()]
    if missing:
        print(f"跳过不存在的输入目录：{', '.join(missing)}")

    report = build_corpus(input_dirs, args.output)
    _print_report(report)
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
