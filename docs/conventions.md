# 目录与命名规范

> 适用范围：烬狐 EMBERFOX 虚构商品知识库 v1。

## 一、目录结构

```
data/
├─ products/
│  ├─ catalog.json          # 100 个商品的主数据（价格、库存、参数）
│  └─ docs/                 # 300 篇商品 Markdown 文档
├─ policies/
│  ├─ docs/                 # 35 篇政策 Markdown 文档
│  ├─ raw/
│  │  ├─ images/            # 流程图、信息图（PNG）
│  │  ├─ tables/            # 运费、时效、价保、估价、发票表（CSV/XLSX）
│  │  ├─ pdf/               # 文本型 PDF 政策全文
│  │  ├─ scans/             # 扫描件（JPG + 图片型 PDF，无文本层）
│  │  ├─ docx/              # Word 政策文档
│  │  └─ html/              # 网页表格
│  ├─ parsed/               # 两批解析结果（Markdown，待确认）
│  ├─ selected/             # 已确认入库的解析文档（默认参与切片）
│  ├─ registry.csv          # 政策文件清单、有效期、入库状态、所需工具
│  └─ README.md             # 政策库说明
├─ processed/
│  ├─ parents.jsonl         # 父块
│  ├─ chunks.jsonl          # 子块
│  └─ report.json           # 切片报告
├─ catalog/
│  ├─ source_registry.csv   # 300 篇商品文档的来源清单
│  ├─ products.csv          # 商品表，便于导入数据库或 Excel
│  └─ intent_matrix.csv     # 用户意图覆盖矩阵
└─ eval/                    # 评测集（当前为空，待补充）

docs/
├─ datasheet.md             # 数据卡
├─ data_dictionary.md       # 字段说明
└─ conventions.md           # 本文件

reports/
└─ data_quality_report.md   # 数据质量验收报告

scripts/
├─ generate_catalog.py      # 生成 catalog.json
├─ generate_product_docs.py # 生成 300 篇商品文档与目录 CSV
├─ generate_policy_docs.py  # 生成 35 篇政策文档与 raw 原始文件
├─ parse_policy_raw.py      # 两批解析 CSV/XLSX/DOCX/HTML/PDF/图片
├─ select_policy_parsed.py  # 选择确认入库的解析文档
├─ build_chunks.py          # 清洗、切片（支持多目录）
├─ embed_and_ingest.py      # embedding 并写入 pgvector
└─ build_data_reports.py    # 生成数据质量报告
```

## 二、编号规则

| 对象 | 格式 | 示例 |
|---|---|---|
| 商品编号 | `P` + 4 位数字 | `P2001` |
| 文档编号 | `{product_id}-{01/02/03}` | `P2001-02` |
| 政策编号 | `POL-{领域}-{序号}` | `POL-RET-001` |
| 父块编号 | `{doc_id}_P{序号}` | `P2001-02_P001` |
| 子块编号 | `{doc_id}_C{序号}` | `P2001-02_C003` |

- `01`：产品定位与选购指南
- `02`：规格参数与包装清单
- `03`：使用、保养与常见问题
- 政策领域缩写：`RET` 退换货、`INV` 发票、`LOG` 物流、`PRI` 价格保护、`TRD` 以旧换新、`BND` 安全边界、`PLT` 平台规则

## 三、文件命名

商品文档统一命名为：

```
{product_id}-01-overview.md
{product_id}-02-specs.md
{product_id}-03-usage-faq.md
```

示例：`P2001-01-overview.md`、`P2001-02-specs.md`、`P2001-03-usage-faq.md`。

不要手工修改 `data/products/docs/` 下的文件；修改商品或文档模板后，重新运行生成脚本，保证 300 篇文档一致。

## 四、哪些进 RAG，哪些不进

| 内容 | 进 RAG | 位置 |
|---|---|---|
| 300 篇商品文档 | 是 | `data/products/docs/` → 切片后入库 |
| 35 篇政策文档（Markdown） | 是 | `data/policies/docs/` → 切片后入库 |
| 商品价格、库存、活动、发货时效 | 否 | `catalog.json` + `get_product` 工具 |
| 图片、表格、PDF、扫描件、DOCX、HTML | 否（待解析） | `data/policies/raw/` |
| 第一批解析结果 | 否（待确认） | `data/policies/parsed/` |
| 已选解析文档 | 是 | `data/policies/selected/` |
| 商品来源清单 | 否 | `data/catalog/source_registry.csv` |
| 政策源清单 | 否 | `data/policies/registry.csv` |
| 商品表 | 否 | `data/catalog/products.csv` |
| 意图矩阵 | 否 | `data/catalog/intent_matrix.csv` |
| 数据卡 | 否 | `docs/datasheet.md` |
| 数据质量报告 | 否 | `reports/data_quality_report.md` |
| 生成脚本 | 否 | `scripts/` |

## 五、生成与更新流程

```powershell
./.venv/Scripts/python.exe scripts/generate_catalog.py
./.venv/Scripts/python.exe scripts/generate_product_docs.py
./.venv/Scripts/python.exe scripts/generate_policy_docs.py
./.venv/Scripts/python.exe scripts/parse_policy_raw.py --ocr
./.venv/Scripts/python.exe scripts/select_policy_parsed.py
./.venv/Scripts/python.exe scripts/build_chunks.py
./.venv/Scripts/python.exe scripts/embed_and_ingest.py --prune
./.venv/Scripts/python.exe scripts/build_data_reports.py
```

注意：

- `build_chunks.py` 默认同时读取 `data/products/docs`、`data/policies/docs` 和 `data/policies/selected`；也可以传多个 `--input` 目录。
- `embed_and_ingest.py --prune` 会删除数据库中不在本次输入里的旧父子块，替换知识库时使用；只切一个目录会裁掉另一个目录的数据。
- 修改商品价格或库存时，只改 `scripts/generate_catalog.py` 并重新生成，不要直接改 `catalog.json`，否则下次生成会被覆盖。
- 修改商品文档结构时，只改 `scripts/generate_product_docs.py`，不要在 `data/products/docs/` 里逐篇编辑。
- 修改政策文档时，只改 `scripts/generate_policy_docs.py`，不要在 `data/policies/docs/` 里逐篇编辑。
- `data/policies/raw/` 下的文件不自动入库；两批解析结果在 `data/policies/parsed/`，确认去重和合并方案后由 `scripts/select_policy_parsed.py` 放入 `selected/` 再切片。
- OCR 使用 `OCR_MODEL`（默认 `qwen-vl-ocr`），留空 `OCR_API_KEY`/`OCR_BASE_URL` 时复用 `EMBEDDING_*` 配置。
