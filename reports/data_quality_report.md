# 数据质量验收报告

> 生成日期：2026-10-25T13:05:19+00:00
> 数据范围：烬狐 EMBERFOX 商品 + 店铺政策知识库 v1

## 一、总览

| 指标 | 结果 |
|---|---|
| 商品数 | 100 |
| 商品文档数 | 300 |
| 政策文档数 | 35 |
| 已选解析文档数 | 7 |
| 文档总数 | 342 |
| 父块数 | 342 |
| 子块数 | 1504 |
| 解析/校验错误 | 0 |
| 文档警告 | 0 |
| 文档近重复数 | 0（重复率 0.00%） |
| 商品源清单 | 300 |
| 政策源清单 | 62 |
| 已解析文件 | 27 |
| 解析重复/待 OCR/失败 | 8 / 0 / 0 |
| 评测 gold | 80（可回答 70 / 拒答 10） |
| 未入库原始文件 | 20（PNG 5 个、XLSX 5 个、PDF 5 个、JPG 2 个、DOCX 2 个、HTML 1 个） |
| 意图矩阵行数 | 32 |
| 数据库落库 | 数据库：342 个父块 / 1504 个子块 |

## 二、商品库分布

| 分类 | 商品数 |
|---|---|
| 键盘 | 40 |
| 鼠标 | 35 |
| 耳机 | 25 |

| 子类 | 商品数 |
|---|---|
| 磁轴键盘 | 19 |
| 无线游戏鼠标 | 16 |
| 机械键盘 | 14 |
| 头戴式游戏耳机 | 13 |
| 入耳式游戏耳机 | 8 |
| 有线游戏鼠标 | 7 |
| 镁合金无线鼠标 | 6 |
| 入门游戏鼠标 | 6 |
| 矮轴键盘 | 5 |
| 头戴式蓝牙耳机 | 4 |
| 铝坨坨键盘 | 2 |

- 缺货商品：9 个（VK68 Ultra、VK98 Ultra、SL98、VM8 Ultra、VM10、TM9、EM7、AH5 Wireless、EH7）
- 低库存（1–10 件）：8 个（AL65（9）、AL75（7）、TM8 Pro（9）、TM9 Pro（6）、AH9 Pro（4）、AH9（9）、AH9 Wireless（7）、BH5 Pro（6））
- 价格区间：69–1599 元

## 三、政策文档分布

| 领域 | 文档数 |
|---|---|
| 退换货 | 8 |
| 物流 | 6 |
| 发票 | 5 |
| 价格保护 | 5 |
| 以旧换新 | 5 |
| 安全边界 | 3 |
| 平台规则 | 3 |

| doc_type | 文档数 |
|---|---|
| store_policy | 24 |
| policy_faq | 5 |
| refusal_boundary | 3 |
| platform_rule | 2 |
| policy_notice | 1 |

- 已标记废弃的历史版本：POL-PRI-002、POL-RET-002
- 未入库原始文件按格式：PNG 5 个、XLSX 5 个、PDF 5 个、JPG 2 个、DOCX 2 个、HTML 1 个
- 两批已解析 27 个文件，其中 7 篇已选入库、8 个重复、0 个待 OCR、0 个失败；其余解析结果在 `data/policies/parsed/`，尚未入库。
- 原始文件清单与所需解析工具见 `data/policies/registry.csv`

## 四、切片长度

| 类型 | min / avg / max（字符） |
|---|---|
| 父块 | 232 / 634.4 / 851 |
| 子块 | 59 / 175.1 / 490 |

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
- [x] 342 篇文档全部通过 front matter 与正文校验。
- [x] 文档未检出价格、库存、满减等结构化事实泄漏。
- [x] 新政策文档保留 `effective_date`、`valid_until`、`deprecated`，并保留旧版冲突样本。
- [x] 两批 27 个原始文件解析完成，0 失败；8 个重复已标记，0 个待 OCR。
- [x] 已选 7 篇解析文档通过 front matter 与切片校验。
- [x] 父块、子块长度均在硬上限内。
- [x] 精确重复文档数 0。
- [x] pgvector 落库数量与 JSONL 一致。

## 七、检索评测基线

| 指标 | 结果 |
|---|---:|
| Recall@5 | 92.1% |
| Hit@5 | 98.6% |
| MRR@5 | 0.725 |
| 可回答问题误拒率 | 0.0% |
| 应拒答问题准确率 | 40.0% |
| 平均检索耗时 | 0.759s |

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
