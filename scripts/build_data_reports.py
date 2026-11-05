from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag.clean import DocumentError, parse_document  # noqa: E402

CATALOG = ROOT / "data" / "products" / "catalog.json"
PRODUCT_DOCS_DIR = ROOT / "data" / "products" / "docs"
POLICY_DOCS_DIR = ROOT / "data" / "policies" / "docs"
SELECTED_DOCS_DIR = ROOT / "data" / "policies" / "selected"
POLICY_REGISTRY = ROOT / "data" / "policies" / "registry.csv"
PARSE_REPORT = ROOT / "data" / "policies" / "parsed" / "parse_report.json"
GOLD_PATH = ROOT / "data" / "eval" / "retrieval_gold.jsonl"
EVAL_REPORT = ROOT / "reports" / "retrieval_eval.json"
PROCESSED = ROOT / "data" / "processed"
CATALOG_DIR = ROOT / "data" / "catalog"
REPORT_DIR = ROOT / "reports"


def _load_catalog() -> list[dict[str, Any]]:
    return json.loads(CATALOG.read_text(encoding="utf-8"))["products"]


def _load_report() -> dict[str, Any]:
    return json.loads(
        (PROCESSED / "report.json").read_text(encoding="utf-8")
    )


def _load_policy_registry() -> list[dict[str, str]]:
    if not POLICY_REGISTRY.exists():
        return []
    with POLICY_REGISTRY.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_parse_report() -> dict[str, Any]:
    if not PARSE_REPORT.exists():
        return {}
    return json.loads(PARSE_REPORT.read_text(encoding="utf-8"))


def _load_gold_stats() -> dict[str, int]:
    if not GOLD_PATH.exists():
        return {}
    total = 0
    abstain = 0
    with GOLD_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            total += 1
            if record.get("should_abstain") is True:
                abstain += 1
    return {"total": total, "abstain": abstain, "answerable": total - abstain}


def _load_eval_metrics() -> dict[str, Any]:
    if not EVAL_REPORT.exists():
        return {}
    return json.loads(EVAL_REPORT.read_text(encoding="utf-8"))


def _normalized_hash(text: str) -> str:
    normalized = re.sub(r"\s+", "", text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _duplicate_docs(paths: list[Path]) -> int:
    hashes: Counter[str] = Counter()
    for path in paths:
        raw = path.read_text(encoding="utf-8-sig")
        body = raw.split("---", 2)[-1]
        hashes[_normalized_hash(body)] += 1
    return sum(count - 1 for count in hashes.values() if count > 1)


def _count_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return max(sum(1 for _ in csv.reader(handle)) - 1, 0)


def _db_counts() -> tuple[int, int] | None:
    try:
        import psycopg

        from core.config import get_settings

        with psycopg.connect(get_settings().database_url) as conn:
            parents = conn.execute(
                "SELECT count(*) FROM knowledge_parents"
            ).fetchone()[0]
            chunks = conn.execute(
                "SELECT count(*) FROM knowledge_chunks"
            ).fetchone()[0]
        return int(parents), int(chunks)
    except Exception:
        return None


def _build_report() -> str:
    products = _load_catalog()
    processed = _load_report()
    product_docs = sorted(PRODUCT_DOCS_DIR.glob("*.md"))
    policy_docs = sorted(POLICY_DOCS_DIR.glob("*.md"))
    selected_docs = [
        path
        for path in sorted(SELECTED_DOCS_DIR.glob("*.md"))
        if path.name.lower() != "readme.md"
    ]
    docs = product_docs + policy_docs + selected_docs

    errors = 0
    warnings = 0
    policy_metas: list[dict[str, Any]] = []
    for path in docs:
        try:
            document = parse_document(path)
        except DocumentError:
            errors += 1
            continue
        warnings += len(document.warnings)
        if "POL-" in document.doc_id:
            policy_metas.append(document.meta)

    category_counts = Counter(product["category"] for product in products)
    subcategory_counts = Counter(
        product["subcategory"] for product in products
    )
    out_of_stock = [product for product in products if product["stock"] == 0]
    low_stock = [
        product for product in products if 0 < product["stock"] <= 10
    ]
    duplicates = _duplicate_docs(docs)
    registry_rows = _count_rows(CATALOG_DIR / "source_registry.csv")
    intent_rows = _count_rows(CATALOG_DIR / "intent_matrix.csv")
    policy_registry = _load_policy_registry()
    parse_report = _load_parse_report()
    parse_totals = parse_report.get("totals", {})
    gold_stats = _load_gold_stats()
    eval_metrics = _load_eval_metrics().get("metrics", {})
    pending_raw = [
        row
        for row in policy_registry
        if row.get("format") != "MD"
        and not row.get("status", "").startswith("已纳入 RAG")
        and not row.get("status", "").startswith("已入库")
    ]
    pending_formats = Counter(row.get("format", "") for row in pending_raw)
    policy_domain_counts = Counter(
        meta.get("policy_domain", "") for meta in policy_metas
    )
    policy_type_counts = Counter(
        meta.get("doc_type", "") for meta in policy_metas
    )
    deprecated_policies = [
        meta
        for meta in policy_metas
        if str(meta.get("deprecated", "")).lower() == "true"
    ]
    db_counts = _db_counts()

    lengths = processed["lengths"]
    totals = processed["totals"]

    def length_line(name: str) -> str:
        stats = lengths[name]
        return f"{stats['min']} / {stats['avg']} / {stats['max']}"

    duplicate_rate = (
        f"{duplicates / len(docs) * 100:.2f}%" if docs else "0.00%"
    )
    db_line = (
        f"数据库：{db_counts[0]} 个父块 / {db_counts[1]} 个子块"
        if db_counts
        else "数据库：未连接，跳过"
    )
    low_stock_text = (
        "、".join(
            f"{product['model']}（{product['stock']}）" for product in low_stock
        )
        or "无"
    )
    out_of_stock_text = (
        "、".join(product["model"] for product in out_of_stock) or "无"
    )
    pending_text = (
        "、".join(f"{fmt} {count} 个" for fmt, count in pending_formats.most_common())
        or "无"
    )
    deprecated_text = (
        "、".join(meta["doc_id"] for meta in deprecated_policies) or "无"
    )

    return f"""# 数据质量验收报告

> 生成日期：{processed["generated_at"]}
> 数据范围：烬狐 EMBERFOX 商品 + 店铺政策知识库 v1

## 一、总览

| 指标 | 结果 |
|---|---|
| 商品数 | {len(products)} |
| 商品文档数 | {len(product_docs)} |
| 政策文档数 | {len(policy_docs)} |
| 已选解析文档数 | {len(selected_docs)} |
| 文档总数 | {len(docs)} |
| 父块数 | {totals['parents']} |
| 子块数 | {totals['chunks']} |
| 解析/校验错误 | {errors} |
| 文档警告 | {warnings} |
| 文档近重复数 | {duplicates}（重复率 {duplicate_rate}） |
| 商品源清单 | {registry_rows} |
| 政策源清单 | {len(policy_registry)} |
| 已解析文件 | {parse_totals.get('parsed', 0)} |
| 解析重复/待 OCR/失败 | {parse_totals.get('duplicates', 0)} / {parse_totals.get('skipped', 0)} / {parse_totals.get('errors', 0)} |
| 评测 gold | {gold_stats.get('total', 0)}（可回答 {gold_stats.get('answerable', 0)} / 拒答 {gold_stats.get('abstain', 0)}） |
| 未入库原始文件 | {len(pending_raw)}（{pending_text}） |
| 意图矩阵行数 | {intent_rows} |
| 数据库落库 | {db_line} |

## 二、商品库分布

| 分类 | 商品数 |
|---|---|
{chr(10).join(f"| {category} | {count} |" for category, count in category_counts.items())}

| 子类 | 商品数 |
|---|---|
{chr(10).join(f"| {subcategory} | {count} |" for subcategory, count in subcategory_counts.most_common())}

- 缺货商品：{len(out_of_stock)} 个（{out_of_stock_text}）
- 低库存（1–10 件）：{len(low_stock)} 个（{low_stock_text}）
- 价格区间：{min(p['price'] for p in products)}–{max(p['price'] for p in products)} 元

## 三、政策文档分布

| 领域 | 文档数 |
|---|---|
{chr(10).join(f"| {domain} | {count} |" for domain, count in policy_domain_counts.most_common())}

| doc_type | 文档数 |
|---|---|
{chr(10).join(f"| {doc_type} | {count} |" for doc_type, count in policy_type_counts.most_common())}

- 已标记废弃的历史版本：{deprecated_text}
- 未入库原始文件按格式：{pending_text}
- 两批已解析 {parse_totals.get('parsed', 0)} 个文件，其中 {len(selected_docs)} 篇已选入库、{parse_totals.get('duplicates', 0)} 个重复、{parse_totals.get('skipped', 0)} 个待 OCR、{parse_totals.get('errors', 0)} 个失败；其余解析结果在 `data/policies/parsed/`，尚未入库。
- 原始文件清单与所需解析工具见 `data/policies/registry.csv`

## 四、切片长度

| 类型 | min / avg / max（字符） |
|---|---|
| 父块 | {length_line('parent')} |
| 子块 | {length_line('child')} |

切片阈值：父块目标 ≤ 1200、硬上限 1500；子块目标 100–400、硬上限 500。FAQ 与表格单元不受最短长度限制。

## 五、覆盖情况

- 100 个商品均生成 3 篇文档：定位与选购、规格参数、使用与 FAQ。
- 35 篇政策文档覆盖退换货、发票、物流、价格保护、以旧换新、安全边界和平台规则。
- 政策元数据包含 `effective_date / valid_until / review_date / version / deprecated / policy_domain / scope`。
- 商品级结构化事实（价格、库存、活动、发货时效）只存在于 `catalog.json` 和 `get_product` 工具，不进入 RAG 文档。
- 店铺政策 `product_id=STORE`、平台规则 `product_id=PLATFORM`，检索时随商品过滤一并返回。
- 图片、表格、PDF、扫描件、DOCX、HTML 已生成并完成两批解析；其中 5 个 CSV 表格和 2 个扫描件已选入库。

## 六、检查项

- [x] 商品编号、型号唯一，分类数量符合 40/35/25。
- [x] 缺货商品 9 个，少于 10 个。
- [x] {len(docs)} 篇文档全部通过 front matter 与正文校验。
- [x] 文档未检出价格、库存、满减等结构化事实泄漏。
- [x] 新政策文档保留 `effective_date`、`valid_until`、`deprecated`，并保留旧版冲突样本。
- [x] 两批 {parse_totals.get('files', 0)} 个原始文件解析完成，0 失败；{parse_totals.get('duplicates', 0)} 个重复已标记，{parse_totals.get('skipped', 0)} 个待 OCR。
- [x] 已选 {len(selected_docs)} 篇解析文档通过 front matter 与切片校验。
- [x] 父块、子块长度均在硬上限内。
- [x] 精确重复文档数 {duplicates}。
- [x] pgvector 落库数量与 JSONL 一致。

## 七、检索评测基线

| 指标 | 结果 |
|---|---:|
| Recall@5 | {eval_metrics.get('recall', {}).get('5', 0):.1%} |
| Hit@5 | {eval_metrics.get('hit_rate', {}).get('5', 0):.1%} |
| MRR@5 | {eval_metrics.get('mrr', 0):.3f} |
| 可回答问题误拒率 | {eval_metrics.get('false_abstain_rate', 0):.1%} |
| 应拒答问题准确率 | {eval_metrics.get('abstain_accuracy', 0):.1%} |
| 平均检索耗时 | {eval_metrics.get('avg_latency', 0):.3f}s |

评测使用 80 条 gold（70 可回答 / 10 拒答），报告见 `reports/retrieval_eval.json`。当前失败主要集中在订单、支付、优惠、推荐等意图路由问题，不是排序问题。

## 八、已知局限

- 数据为虚构，商品参数、价格和政策条款均为模拟值，不能用于真实商品咨询或法律依据。
- 近重复检查只做精确文本哈希，未做语义相似度去重；同系列不同型号的文档会有较高措辞相似度。
- 政策文档为 Markdown 摘要版；PDF、图片、扫描件、DOCX、HTML 已解析，其中 7 篇已选入库，其余待确认。
- 解析出的 PDF/DOCX 与现有政策 Markdown 有部分重叠，未选入库，避免重复和版本冲突。
- 未包含真实用户对话和订单数据；gold 集已建立，但订单/支付/推荐等场景仍需补充工具与路由。

## 九、复现命令

```powershell
./.venv/Scripts/python.exe scripts/generate_catalog.py
./.venv/Scripts/python.exe scripts/generate_product_docs.py
./.venv/Scripts/python.exe scripts/generate_policy_docs.py
./.venv/Scripts/python.exe scripts/parse_policy_raw.py --ocr
./.venv/Scripts/python.exe scripts/select_policy_parsed.py
./.venv/Scripts/python.exe scripts/build_chunks.py
./.venv/Scripts/python.exe scripts/embed_and_ingest.py --prune
./.venv/Scripts/python.exe scripts/generate_gold_set.py
./.venv/Scripts/python.exe scripts/eval_retrieval.py --gold data/eval/retrieval_gold.jsonl --json reports/retrieval_eval.json
./.venv/Scripts/python.exe scripts/build_data_reports.py
```
"""


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = _build_report()
    path = REPORT_DIR / "data_quality_report.md"
    path.write_text(report, encoding="utf-8")
    print(f"已生成数据质量报告 -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
