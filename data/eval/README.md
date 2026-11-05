# 检索评测 Gold 集

> 规模：80 条
> 可回答：70 条
> 应拒答：10 条
> 生成方式：脚本 `scripts/generate_gold_set.py` 确定性生成

## 用法

```powershell
./.venv/Scripts/python.exe scripts/eval_retrieval.py --gold data/eval/retrieval_gold.jsonl
```

单条冒烟：

```powershell
./.venv/Scripts/python.exe scripts/eval_retrieval.py --query "VK75 Pro 的触发键程"
```

## 覆盖分布

| 类别 | 数量 |
|---|---:|
| abstain | 10 |
| policy_invoice | 3 |
| policy_logistics | 3 |
| policy_platform | 3 |
| policy_price | 2 |
| policy_return | 5 |
| policy_tradein | 2 |
| policy_version | 2 |
| product_compare | 6 |
| product_faq | 8 |
| product_overview | 8 |
| product_spec | 19 |
| safety_boundary | 3 |
| scan | 1 |
| table | 5 |

| 难度 | 数量 |
|---|---:|
| easy | 46 |
| hard | 13 |
| medium | 21 |

## 说明

- 期望命中使用 `expected_doc_ids`，便于跨父块调整。
- 多文档对比题使用多个期望文档，Recall 按覆盖率计算。
- 拒答题不设期望文档，正确行为是 `abstained=true` 或转人工。
- 旧版政策题（g055、g056）用于测试历史版本检索，标了 `include_deprecated=true`；其余题目默认排除 `deprecated=true` 的文档。
- 订单/物流实时状态题（g078、g079）当前没有订单工具，预期结果是拒答或转人工。
