import json

import pytest

from rag.search import SearchHit, SearchResult
from scripts.eval_retrieval import (
    GoldError,
    GoldItem,
    evaluate,
    load_gold,
)


def _hit(parent_id: str = "P1", doc_id: str = "D1", score: float = 0.9) -> SearchHit:
    return SearchHit(
        chunk_id=f"{parent_id}_C001",
        parent_id=parent_id,
        doc_id=doc_id,
        product_id="P2001",
        title="测试商品",
        section_path="测试商品 > 参数",
        unit_kind="section",
        text="子块内容",
        parent_text="父块内容",
        score=score,
        metadata={},
    )


def _result(
    query: str,
    hits: list[SearchHit],
    abstained: bool = False,
    reason: str | None = None,
) -> SearchResult:
    return SearchResult(
        query=query,
        hits=hits,
        abstained=abstained,
        reason=reason,
        min_score=0.35,
    )


def test_evaluate_computes_recall_mrr_and_abstain():
    items = [
        GoldItem(item_id="q1", query="q1", expected_parent_ids=("P1",)),
        GoldItem(item_id="q2", query="q2", expected_doc_ids=("D9",)),
        GoldItem(item_id="q3", query="q3", should_abstain=True),
        GoldItem(item_id="q4", query="q4", should_abstain=True),
    ]
    results = {
        "q1": _result("q1", [_hit("P2"), _hit("P1")]),
        "q2": _result("q2", [_hit("P3", "D9")]),
        "q3": _result("q3", [], abstained=True, reason="无检索结果"),
        "q4": _result("q4", [_hit("P4", score=0.8)]),
    }

    report = evaluate(
        items, lambda query, **kwargs: results[query], ks=(1, 3), top_k=3
    )

    assert report.answerable == 2
    assert report.no_answer == 2
    assert report.recall[1] == pytest.approx(0.5)
    assert report.recall[3] == pytest.approx(1.0)
    assert report.hit_rate[1] == pytest.approx(0.5)
    assert report.mrr == pytest.approx(0.75)
    assert report.abstain_accuracy == pytest.approx(0.5)
    assert report.false_abstain_rate == pytest.approx(0.0)
    assert len(report.failures()) == 1
    assert report.failures()[0].item.item_id == "q4"


def test_evaluate_counts_false_abstain():
    items = [GoldItem(item_id="q1", query="q1", expected_parent_ids=("P1",))]
    result = _result("q1", [_hit("P1")], abstained=True, reason="低分")

    report = evaluate(items, lambda query, **kwargs: result, ks=(5,), top_k=5)

    assert report.false_abstain_rate == 1.0
    assert report.failures()[0].item.item_id == "q1"


def test_evaluate_passes_include_deprecated_per_item():
    items = [
        GoldItem(
            item_id="q1",
            query="q1",
            expected_doc_ids=("D1",),
            include_deprecated=True,
        ),
        GoldItem(item_id="q2", query="q2", expected_doc_ids=("D2",)),
    ]
    calls: dict[str, bool] = {}

    def search(query, include_deprecated=False):
        calls[query] = include_deprecated
        return _result(query, [_hit(doc_id="D1" if query == "q1" else "D2")])

    evaluate(items, search, ks=(1,), top_k=1)

    assert calls == {"q1": True, "q2": False}


def test_evaluate_force_include_deprecated():
    items = [GoldItem(item_id="q1", query="q1", expected_doc_ids=("D1",))]
    calls: dict[str, bool] = {}

    def search(query, include_deprecated=False):
        calls[query] = include_deprecated
        return _result(query, [_hit(doc_id="D1")])

    evaluate(items, search, ks=(1,), top_k=1, force_include_deprecated=True)

    assert calls == {"q1": True}


def test_load_gold_reads_records_and_infers_abstain(tmp_path):
    path = tmp_path / "gold.jsonl"
    records = [
        {"id": "q1", "query": "问题一", "expected_parent_ids": ["P1"]},
        {"id": "q2", "query": "问题二", "expected_doc_ids": "D1"},
        {"id": "q3", "query": "问题三"},
    ]
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records),
        encoding="utf-8",
    )

    items = load_gold(path)

    assert [item.item_id for item in items] == ["q1", "q2", "q3"]
    assert items[1].expected_doc_ids == ("D1",)
    assert items[2].should_abstain is True


def test_load_gold_reads_include_deprecated_flag(tmp_path):
    path = tmp_path / "gold.jsonl"
    path.write_text(
        json.dumps(
            {
                "id": "q1",
                "query": "2024 年退货政策",
                "expected_doc_ids": ["D1"],
                "include_deprecated": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    items = load_gold(path)

    assert items[0].include_deprecated is True


def test_load_gold_rejects_conflicting_abstain(tmp_path):
    path = tmp_path / "gold.jsonl"
    path.write_text(
        json.dumps(
            {
                "id": "q1",
                "query": "问题",
                "expected_parent_ids": ["P1"],
                "should_abstain": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(GoldError, match="同时声明"):
        load_gold(path)


def test_load_gold_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="未找到 gold 文件"):
        load_gold(tmp_path / "missing.jsonl")
