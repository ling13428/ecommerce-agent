from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import psycopg

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import get_settings  # noqa: E402
from rag.embedding import EmbeddingError  # noqa: E402
from rag.search import (  # noqa: E402
    DEFAULT_MIN_SCORE,
    DEFAULT_TOP_K,
    SearchError,
    SearchHit,
    SearchResult,
    search_knowledge,
)

DEFAULT_GOLD = ROOT / "data" / "eval" / "retrieval_gold.jsonl"
DEFAULT_KS = (1, 3, 5)

GOLD_FORMAT = """gold 文件格式（JSONL，每行一个对象）：
{"id": "q001", "query": "VK75 Pro 的触发键程", "expected_parent_ids": ["P2001-01_P001"]}
{"id": "q002", "query": "VK75 Pro 怎么连接", "expected_doc_ids": ["P2001-03"]}
{"id": "q003", "query": "今天天气怎么样", "should_abstain": true}

字段说明：
  id                  必填，题目唯一标识
  query               必填，检索问题
  expected_parent_ids 选填，期望命中的父块 ID
  expected_doc_ids    选填，期望命中的文档 ID
  should_abstain      选填，true 表示该问题知识库没有答案，应低分拒答
  note                选填，备注
expected_parent_ids / expected_doc_ids / should_abstain 至少要有一项。"""


class GoldError(RuntimeError):
    pass


@dataclass(frozen=True)
class GoldItem:
    item_id: str
    query: str
    expected_parent_ids: tuple[str, ...] = ()
    expected_doc_ids: tuple[str, ...] = ()
    should_abstain: bool = False
    include_deprecated: bool = False
    note: str | None = None

    @property
    def target_count(self) -> int:
        return len(self.expected_parent_ids) + len(self.expected_doc_ids)


@dataclass
class Outcome:
    item: GoldItem
    hits: list[SearchHit]
    abstained: bool
    reason: str | None
    top_score: float | None
    latency: float
    first_rank: int | None
    recall: dict[int, float] = field(default_factory=dict)


@dataclass
class Report:
    outcomes: list[Outcome]
    ks: tuple[int, ...]
    recall: dict[int, float]
    hit_rate: dict[int, float]
    mrr: float
    abstain_accuracy: float | None
    false_abstain_rate: float
    answerable: int
    no_answer: int
    avg_latency: float
    min_score: float
    top_k: int

    def failures(self) -> list[Outcome]:
        result: list[Outcome] = []
        for outcome in self.outcomes:
            if outcome.item.should_abstain:
                if not outcome.abstained:
                    result.append(outcome)
            elif outcome.abstained or outcome.first_rank is None:
                result.append(outcome)
        return result


def _as_id_list(value: Any, label: str, item_id: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise GoldError(f"{item_id} 的 {label} 必须是非空字符串数组")
    return tuple(item.strip() for item in value)


def _parse_gold(record: dict[str, Any], line_no: int) -> GoldItem:
    item_id = str(record.get("id") or f"line{line_no}").strip()
    query = str(record.get("query") or "").strip()
    if not query:
        raise GoldError(f"{item_id} 缺少 query")

    parents = _as_id_list(
        record.get("expected_parent_ids"), "expected_parent_ids", item_id
    )
    docs = _as_id_list(record.get("expected_doc_ids"), "expected_doc_ids", item_id)
    should_abstain = record.get("should_abstain")
    if should_abstain is None:
        should_abstain = not parents and not docs
    if not isinstance(should_abstain, bool):
        raise GoldError(f"{item_id} 的 should_abstain 必须是布尔值")
    if should_abstain and (parents or docs):
        raise GoldError(f"{item_id} 同时声明了应拒答和期望结果")
    if not should_abstain and not parents and not docs:
        raise GoldError(f"{item_id} 缺少 expected_parent_ids / expected_doc_ids")

    include_deprecated = record.get("include_deprecated", False)
    if not isinstance(include_deprecated, bool):
        raise GoldError(f"{item_id} 的 include_deprecated 必须是布尔值")

    note = record.get("note")
    return GoldItem(
        item_id=item_id,
        query=query,
        expected_parent_ids=parents,
        expected_doc_ids=docs,
        should_abstain=should_abstain,
        include_deprecated=include_deprecated,
        note=str(note) if note is not None else None,
    )


def load_gold(path: Path) -> list[GoldItem]:
    if not path.exists():
        raise FileNotFoundError(f"未找到 gold 文件：{path}")

    items: list[GoldItem] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise GoldError(f"第 {line_no} 行不是合法 JSON") from exc
            if not isinstance(record, dict):
                raise GoldError(f"第 {line_no} 行必须是 JSON 对象")
            item = _parse_gold(record, line_no)
            if item.item_id in seen:
                raise GoldError(f"id 重复：{item.item_id}")
            seen.add(item.item_id)
            items.append(item)

    if not items:
        raise GoldError("gold 文件里没有题目")
    return items


def _match(
    item: GoldItem, hits: list[SearchHit]
) -> tuple[int, int | None]:
    matched: set[tuple[str, str]] = set()
    first_rank: int | None = None
    for index, hit in enumerate(hits, 1):
        if hit.parent_id in item.expected_parent_ids:
            matched.add(("parent", hit.parent_id))
            if first_rank is None:
                first_rank = index
        elif hit.doc_id in item.expected_doc_ids:
            matched.add(("doc", hit.doc_id))
            if first_rank is None:
                first_rank = index
    return len(matched), first_rank


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def evaluate(
    items: list[GoldItem],
    search_fn: Callable[..., SearchResult],
    ks: tuple[int, ...] = DEFAULT_KS,
    top_k: int = DEFAULT_TOP_K,
    min_score: float = DEFAULT_MIN_SCORE,
    force_include_deprecated: bool = False,
) -> Report:
    active_ks = tuple(sorted({k for k in ks if 1 <= k <= top_k}))
    outcomes: list[Outcome] = []

    for item in items:
        started = time.perf_counter()
        result = search_fn(
            item.query,
            include_deprecated=(
                force_include_deprecated or item.include_deprecated
            ),
        )
        latency = time.perf_counter() - started

        _, first_rank = _match(item, result.hits[:top_k])
        recall: dict[int, float] = {}
        for k in active_ks:
            matched_at_k, _ = _match(item, result.hits[:k])
            recall[k] = (
                matched_at_k / item.target_count if item.target_count else 0.0
            )

        outcomes.append(
            Outcome(
                item=item,
                hits=result.hits,
                abstained=result.abstained,
                reason=result.reason,
                top_score=result.top_score,
                latency=latency,
                first_rank=first_rank,
                recall=recall,
            )
        )

    answerable = [o for o in outcomes if not o.item.should_abstain]
    no_answer = [o for o in outcomes if o.item.should_abstain]

    recall_metrics = {
        k: _mean([o.recall[k] for o in answerable]) for k in active_ks
    }
    hit_rate = {
        k: _mean([1.0 if o.recall[k] > 0 else 0.0 for o in answerable])
        for k in active_ks
    }
    mrr = _mean(
        [1.0 / o.first_rank if o.first_rank else 0.0 for o in answerable]
    )
    abstain_accuracy = (
        _mean([1.0 if o.abstained else 0.0 for o in no_answer])
        if no_answer
        else None
    )
    false_abstain_rate = _mean(
        [1.0 if o.abstained else 0.0 for o in answerable]
    )

    return Report(
        outcomes=outcomes,
        ks=active_ks,
        recall=recall_metrics,
        hit_rate=hit_rate,
        mrr=mrr,
        abstain_accuracy=abstain_accuracy,
        false_abstain_rate=false_abstain_rate,
        answerable=len(answerable),
        no_answer=len(no_answer),
        avg_latency=_mean([o.latency for o in outcomes]),
        min_score=min_score,
        top_k=top_k,
    )


def _short(text: str, limit: int = 42) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _hit_ids(outcome: Outcome, limit: int = 3) -> str:
    return ", ".join(
        f"{hit.parent_id}({hit.score:.3f})" for hit in outcome.hits[:limit]
    ) or "-"


def format_report(report: Report, gold_path: Path) -> str:
    lines = [
        "=== 检索评测 ===",
        f"gold: {gold_path}（{len(report.outcomes)} 条："
        f"可回答 {report.answerable} / 应拒答 {report.no_answer}）",
        f"top_k={report.top_k}  min_score={report.min_score:.2f}",
        "  ".join(
            f"Recall@{k}={report.recall[k]:.3f}" for k in report.ks
        ),
        "  ".join(
            f"Hit@{k}={report.hit_rate[k]:.3f}" for k in report.ks
        ),
        f"MRR@{report.top_k}={report.mrr:.3f}",
        f"误拒率(可回答问题)={report.false_abstain_rate:.3f}",
    ]
    if report.abstain_accuracy is not None:
        correct = round(report.abstain_accuracy * report.no_answer)
        lines.append(
            f"拒答准确率(应拒答问题)={report.abstain_accuracy:.3f} "
            f"({correct}/{report.no_answer})"
        )
    lines.append(f"平均耗时={report.avg_latency:.3f}s（embedding + 检索）")

    failures = report.failures()
    if not failures:
        lines.append("全部通过")
        return "\n".join(lines)

    lines.append(f"失败 {len(failures)} 条：")
    for outcome in failures:
        if outcome.item.should_abstain:
            label = "应拒答但未拒答"
        elif outcome.abstained:
            label = "误拒答"
        else:
            label = "未命中"
        top = f"{outcome.top_score:.3f}" if outcome.top_score is not None else "-"
        lines.append(
            f"  [{outcome.item.item_id}] {label} top={top}"
            f"  \"{_short(outcome.item.query)}\""
            f"\n      hits: {_hit_ids(outcome)}"
        )
    return "\n".join(lines)


def _report_to_dict(report: Report, gold_path: Path) -> dict[str, Any]:
    return {
        "gold": str(gold_path),
        "top_k": report.top_k,
        "min_score": report.min_score,
        "counts": {
            "total": len(report.outcomes),
            "answerable": report.answerable,
            "no_answer": report.no_answer,
        },
        "metrics": {
            "recall": {str(k): v for k, v in report.recall.items()},
            "hit_rate": {str(k): v for k, v in report.hit_rate.items()},
            "mrr": report.mrr,
            "abstain_accuracy": report.abstain_accuracy,
            "false_abstain_rate": report.false_abstain_rate,
            "avg_latency": report.avg_latency,
        },
        "items": [
            {
                "id": outcome.item.item_id,
                "query": outcome.item.query,
                "should_abstain": outcome.item.should_abstain,
                "include_deprecated": outcome.item.include_deprecated,
                "abstained": outcome.abstained,
                "reason": outcome.reason,
                "top_score": outcome.top_score,
                "first_rank": outcome.first_rank,
                "recall": {str(k): v for k, v in outcome.recall.items()},
                "latency": outcome.latency,
                "hits": [
                    {
                        "parent_id": hit.parent_id,
                        "doc_id": hit.doc_id,
                        "score": hit.score,
                    }
                    for hit in outcome.hits
                ],
            }
            for outcome in report.outcomes
        ],
    }


def _print_query_result(result: SearchResult) -> None:
    status = "拒答" if result.abstained else "命中"
    print(
        f"query: {result.query}\n"
        f"状态: {status}"
        + (f"（{result.reason}）" if result.reason else "")
    )
    if not result.hits:
        return
    for index, hit in enumerate(result.hits, 1):
        print(
            f"  {index}. {hit.score:.4f}  {hit.parent_id}  "
            f"{hit.doc_id}  {_short(hit.section_path, 60)}"
        )
        print(f"     {_short(hit.text.split('\n\n', 1)[-1], 100)}")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="RAG 检索评测：Recall@k / MRR / 低分拒答"
    )
    parser.add_argument(
        "--gold",
        type=Path,
        default=DEFAULT_GOLD,
        help=f"gold JSONL 路径，默认 {DEFAULT_GOLD}",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help=f"返回条数，默认 {DEFAULT_TOP_K}",
    )
    parser.add_argument(
        "--candidate-k",
        type=int,
        default=None,
        help="父块去重前的候选子块数，默认 max(top_k*4, 20)",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        help="低分拒答阈值，默认读取 RAG_MIN_SCORE",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="默认读取 DATABASE_URL",
    )
    parser.add_argument(
        "--query",
        default=None,
        help="不跑 gold，直接检索一条问题并打印结果",
    )
    parser.add_argument(
        "--include-deprecated",
        action="store_true",
        help="检索时包含已废弃的历史政策（gold 中的逐条设置也会生效）",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="把评测报告写入 JSON 文件",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    min_score = (
        settings.rag_min_score if args.min_score is None else args.min_score
    )
    if not settings.embedding_configured:
        print("EMBEDDING_API_KEY 未配置，无法生成查询向量")
        return 2

    def run_search(
        query: str, include_deprecated: bool = False
    ) -> SearchResult:
        return search_knowledge(
            query,
            top_k=args.top_k,
            candidate_k=args.candidate_k,
            min_score=min_score,
            include_deprecated=(
                args.include_deprecated or include_deprecated
            ),
            database_url=args.database_url,
        )

    try:
        if args.query:
            _print_query_result(run_search(args.query))
            return 0

        items = load_gold(args.gold)
        report = evaluate(
            items,
            run_search,
            ks=DEFAULT_KS,
            top_k=args.top_k,
            min_score=min_score,
            force_include_deprecated=args.include_deprecated,
        )
    except FileNotFoundError as exc:
        print(f"{exc}\n\n{GOLD_FORMAT}")
        return 2
    except (GoldError, SearchError, EmbeddingError, psycopg.Error) as exc:
        print(f"失败：{type(exc).__name__}: {exc}")
        return 1

    print(format_report(report, args.gold))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(
                _report_to_dict(report, args.gold),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"报告已写入：{args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
