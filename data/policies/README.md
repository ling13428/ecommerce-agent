# 店铺政策与平台规则知识库

> 品牌：烬狐 EMBERFOX　平台：星潮商城　版本：v1
> 生成日期：2026-01-01

## 目录结构

```
data/policies/
├─ docs/                  # 可直接进入 RAG 的 Markdown 政策文档
├─ raw/
│  ├─ images/             # 流程图、信息图（PNG）
│  ├─ tables/             # 运费、时效、价保、估价、发票表（CSV/XLSX）
│  ├─ pdf/                # 文本型 PDF 政策全文
│  ├─ scans/              # 扫描件（JPG + 图片型 PDF，无文本层）
│  ├─ docx/               # Word 政策文档
│  └─ html/               # 网页表格
├─ parsed/                # 原始文件解析结果（Markdown，尚未入库）
├─ registry.csv           # 全部文件清单、有效期、入库状态、所需工具
└─ README.md              # 本文件
```

## 当前状态

- Markdown 政策文档：35 篇，已纳入 RAG 切片。
- 非 Markdown 原始文件：27 个，已在 `registry.csv` 标注所需工具。
- 两批解析：27/27 个文件已解析，重复 8 个，待 OCR 0 个，失败 0 个；解析结果在 `parsed/`，尚未入库。
- CSV：5 个
- DOCX：2 个
- HTML：1 个
- JPG：2 个
- PDF：7 个
- PNG：5 个
- XLSX：5 个

## 覆盖领域

- 退换货：总则、无理由条件、质量问题、运费、退款、换货、FAQ、旧版政策
- 发票：类型、流程、电子发票、专票、FAQ
- 物流：发货、时效、节假日、异常、自提/加急、FAQ
- 价格保护：总则、例外、补差、FAQ、旧版规则
- 以旧换新：总则、估价、回收流程、补贴、FAQ
- 安全边界：他人订单、赔付承诺、敏感信息
- 平台规则：争议处理、平台介入、规则变更公告

## 待解析文件与建议工具

| 格式 | 建议工具 | 处理方式 |
|---|---|---|
| PDF（文本型） | pdfplumber / pypdf | 提取文本后按标题切片 |
| PDF（扫描件） | qwen-vl-ocr / RapidOCR | OCR 后转 Markdown |
| JPG/PNG | qwen-vl-ocr / RapidOCR / 多模态模型 | OCR 或图片理解后转 Markdown |
| CSV/XLSX | csv / openpyxl / pandas | 按行转 Markdown 表格或结构化入库 |
| DOCX | python-docx | 提取段落和表格 |
| HTML | BeautifulSoup / trafilatura | 提取正文和表格 |

当前实际使用：`qwen-vl-ocr`（DashScope OpenAI 兼容接口），配置项为 `OCR_MODEL`、`OCR_API_KEY`、`OCR_BASE_URL`、`OCR_TIMEOUT`。

## 入库约定

- `docs/` 下的 Markdown 由 `scripts/build_chunks.py` 直接切片。
- `parsed/` 下的解析结果由 `scripts/parse_policy_raw.py` 生成，确认无重复后再决定是否加入切片目录。
- `raw/` 下的文件不自动入库，避免把无文本层扫描件或图片当成空文档。
- 引入解析工具后，把解析结果写入 `parsed/` 或 `docs/`，保留 `doc_id`、`effective_date`、`valid_until`、`deprecated`、`source_file`、`parser` 等元数据，再重新切片。
- 新旧版本冲突时，保留旧版文档并标记 `deprecated: true`，回答时优先使用 `effective_date` 最新且未废弃的版本。
