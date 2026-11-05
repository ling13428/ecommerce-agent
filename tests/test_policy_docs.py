import csv
import json
from pathlib import Path

from rag.clean import POLICY_DOC_TYPES, parse_document

ROOT = Path(__file__).resolve().parent.parent
POLICY_DIR = ROOT / "data" / "policies" / "docs"
PARSED_DIR = ROOT / "data" / "policies" / "parsed"
SELECTED_DIR = ROOT / "data" / "policies" / "selected"
POLICY_REGISTRY = ROOT / "data" / "policies" / "registry.csv"
PARSE_REPORT = PARSED_DIR / "parse_report.json"


def test_policy_docs_parse_and_use_policy_types():
    paths = sorted(POLICY_DIR.glob("*.md"))
    assert len(paths) == 35

    for path in paths:
        document = parse_document(path)
        assert document.meta["doc_type"] in POLICY_DOC_TYPES
        assert document.product_id in {"STORE", "PLATFORM"}
        assert document.meta["effective_date"]
        assert document.meta["valid_until"]
        assert document.meta["policy_domain"]


def test_old_policy_versions_are_marked_deprecated():
    old = parse_document(POLICY_DIR / "POL-RET-002.md")
    new = parse_document(POLICY_DIR / "POL-RET-001.md")

    assert old.meta["deprecated"] is True
    assert old.meta["superseded_by"] == "POL-RET-001"
    assert new.meta["deprecated"] is False
    assert new.meta["supersedes"] == "POL-RET-002"


def test_policy_registry_tracks_parse_status():
    with POLICY_REGISTRY.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    formats = {row["format"] for row in rows}
    assert {"MD", "PNG", "CSV", "XLSX", "PDF", "JPG", "DOCX", "HTML"} <= formats
    assert any(
        row["format"] in {"PDF", "JPG", "PNG"}
        and row["status"].startswith("已解析")
        for row in rows
    )
    assert not any(row["status"].startswith("待OCR") for row in rows)
    assert any(row["format"] == "MD" and row["status"] == "已纳入 RAG" for row in rows)
    assert any(row["status"] == "已入库" for row in rows)
    assert any(row["status"].startswith("已解析") for row in rows)


def test_all_raw_files_are_parsed():
    report = json.loads(PARSE_REPORT.read_text(encoding="utf-8"))
    totals = report["totals"]
    assert totals["files"] == 27
    assert totals["parsed"] == 27
    assert totals["skipped"] == 0
    assert totals["errors"] == 0


def test_parsed_docs_validate():
    paths = sorted(PARSED_DIR.glob("*.md"))
    assert len(paths) == 27
    for path in paths:
        document = parse_document(path)
        assert document.product_id in {"STORE", "PLATFORM"}
        assert document.meta["doc_type"] in POLICY_DOC_TYPES
        assert document.meta["source_file"]
        assert document.meta["parser"]


def test_selected_docs_validate():
    paths = [
        path
        for path in sorted(SELECTED_DIR.glob("*.md"))
        if path.name.lower() != "readme.md"
    ]
    assert len(paths) == 7
    for path in paths:
        document = parse_document(path)
        assert document.product_id in {"STORE", "PLATFORM"}
        assert document.meta["doc_type"] in POLICY_DOC_TYPES
        assert document.meta["source_file"]
