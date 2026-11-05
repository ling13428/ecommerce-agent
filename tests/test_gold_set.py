import json
from pathlib import Path

from scripts.eval_retrieval import load_gold

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "data" / "eval" / "retrieval_gold.jsonl"
CHUNKS = ROOT / "data" / "processed" / "chunks.jsonl"


def test_gold_set_loads_with_expected_split():
    items = load_gold(GOLD)

    assert len(items) == 80
    assert len({item.item_id for item in items}) == 80
    assert sum(1 for item in items if item.should_abstain) == 10
    assert sum(1 for item in items if not item.should_abstain) == 70


def test_gold_expected_doc_ids_exist():
    doc_ids = set()
    with CHUNKS.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                doc_ids.add(str(json.loads(line)["doc_id"]))

    for item in load_gold(GOLD):
        missing = [doc_id for doc_id in item.expected_doc_ids if doc_id not in doc_ids]
        assert not missing, f"{item.item_id} 缺少文档：{missing}"
