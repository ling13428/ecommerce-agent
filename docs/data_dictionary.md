# 数据字典

> 适用范围：烬狐 EMBERFOX 虚构商品知识库 v1。
> 本文件只定义字段口径，不进入 RAG 检索库。

## 一、文档元数据

每篇 Markdown 文档的 YAML front matter 必须包含以下字段：

| 字段 | 类型 | 必填 | 取值 / 说明 |
|---|---|---|---|
| `doc_id` | string | 是 | 文档唯一编号，格式 `P2001-01`、`P2001-02`、`P2001-03` |
| `product_id` | string | 是 | 商品编号，必须存在于 `data/products/catalog.json` |
| `title` | string | 是 | 文档标题，包含商品名和文档用途 |
| `doc_type` | enum | 是 | `product_overview` / `product_spec` / `product_faq` / `store_policy` / `platform_rule` / `policy_faq` / `refusal_boundary` / `policy_notice` |
| `category` | enum | 是 | `键盘` / `鼠标` / `耳机` |
| `source` | string | 是 | 来源说明，当前统一为 `烬狐官方商品资料（模拟）` |
| `authority_level` | enum | 是 | `高` / `中` / `低` |
| `version` | string | 是 | 文档版本，当前为 `v1` |
| `effective_date` | date | 是 | 生效日期，格式 `YYYY-MM-DD` |
| `deprecated` | bool | 是 | `true` 表示已废弃，检索时应降权或过滤 |

`doc_type` 与文档内容对应关系：

| doc_type | 文件后缀 | 内容 |
|---|---|---|
| `product_overview` | `01-overview.md` | 产品定位、核心卖点、适用场景、购买前确认 |
| `product_spec` | `02-specs.md` | 参数表、连接与兼容、使用环境、参数口径 |
| `product_faq` | `03-usage-faq.md` | 首次使用、日常保养、常见问题 |
| `store_policy` | `POL-xxx.md` | 店铺政策正文（退换货、发票、物流、价保、以旧换新等） |
| `platform_rule` | `POL-PLT-xxx.md` | 平台规则正文（争议处理、平台介入等） |
| `policy_faq` | `POL-xxx.md` | 政策常见问题 |
| `refusal_boundary` | `POL-BND-xxx.md` | 拒答与安全边界 |
| `policy_notice` | `POL-PLT-xxx.md` | 规则变更公告 |

## 二、商品字段

商品主数据位于 `data/products/catalog.json`，字段如下：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 商品编号，`P2001`–`P2100` |
| `brand` | string | 品牌名，固定 `烬狐 EMBERFOX` |
| `model` | string | 具体型号，如 `VK75 Pro`、`VM9 Ultra` |
| `name` | string | 商品全名，如 `烬狐 VK75 Pro 磁轴键盘` |
| `category` | enum | `键盘` / `鼠标` / `耳机` |
| `subcategory` | string | 子类，如 `磁轴键盘`、`无线游戏鼠标`、`头戴式游戏耳机` |
| `price` | int | 价格，单位元，仅用于商品工具 |
| `stock` | int | 库存件数，`0` 表示缺货 |
| `specs` | string | 一行规格摘要，供 `get_product` 快速返回 |
| `activity` | string | 活动文案，仅用于商品工具 |
| `shipping` | string | 发货时效，仅用于商品工具 |
| `colors` | string[] | 可选配色 |
| `params` | object | 分类相关参数，供文档生成使用 |

### 键盘参数（`params`）

`layout`、`connection`、`switch`、`polling`、`trigger`、`keycap`、`case`、`battery`、`weight`、`colors`、`compatibility`、`software`、`package`、`hotswap`。

### 鼠标参数（`params`）

`shape`、`connection`、`sensor`、`dpi`、`polling`、`weight`、`buttons`、`battery`、`switch`、`colors`、`compatibility`、`software`、`package`。

### 耳机参数（`params`）

`form`、`connection`、`driver`、`mic`、`battery`、`weight`、`surround`、`impedance`、`colors`、`compatibility`、`package`、`software`。

## 三、结构化事实边界

以下字段属于实时结构化事实，**不写入 RAG 文档**，只通过 `get_product` 工具返回：

- `price`
- `stock`
- `activity`
- `shipping`

文档只描述产品特性、参数、使用方法和常见问题。价格、库存、活动和发货时效以工具结果为准，避免两处数据不一致。

## 四、枚举值

| 字段 | 允许值 |
|---|---|
| `category` | `键盘`、`鼠标`、`耳机` |
| `doc_type` | `product_overview`、`product_spec`、`product_faq` |
| `authority_level` | `高`、`中`、`低` |
| `deprecated` | `true`、`false` |
| `policy_domain` | `退换货`、`发票`、`物流`、`价格保护`、`以旧换新`、`安全边界`、`平台规则` |
| `scope` | `店铺`、`平台` |
| `region` | `全国`（当前） |

新增枚举值时必须同步更新本文件、`rag/clean.py` 的校验规则和文档生成脚本。

## 五、政策文档元数据

政策文档（`doc_type` 以 `store_policy`、`platform_rule`、`policy_faq`、`refusal_boundary`、`policy_notice` 开头）在通用字段之外，还应包含：

| 字段 | 类型 | 说明 |
|---|---|---|
| `policy_domain` | enum | 政策领域：退换货/发票/物流/价格保护/以旧换新/安全边界/平台规则 |
| `region` | string | 适用区域，当前统一为 `全国` |
| `scope` | enum | `店铺` 或 `平台` |
| `valid_until` | date | 失效日期，格式 `YYYY-MM-DD`；长期有效可写 `长期` |
| `review_date` | date | 下次复核日期，可为空 |
| `supersedes` | string | 被本文档替代的旧文档编号 |
| `superseded_by` | string | 替代本文档的新文档编号 |
| `deprecated` | bool | 旧版本标记为 `true`，检索时降权或排除 |
| `source_file` | string | 原始文件路径，解析文档使用 |
| `source_format` | string | 原始格式：CSV/XLSX/PDF/DOCX/HTML/JPG/PNG |
| `parser` | string | 解析器：csv/openpyxl/pdfplumber/python-docx/BeautifulSoup/OCR |
| `parsed_at` | date | 解析日期 |
| `page_count` | int | PDF 页数，其他格式可为空 |
| `ocr_model` | string | 扫描件/图片 OCR 使用的模型，如 `qwen-vl-ocr` |
| `duplicate_of` | string | 解析结果与已有文档重复时，指向被重复的文档编号 |

政策文档的 `product_id` 使用范围值，而不是具体商品编号：

| 值 | 含义 |
|---|---|
| `STORE` | 店铺级政策，适用于所有商品 |
| `PLATFORM` | 平台级规则，适用于平台内所有店铺 |

政策文档可以包含运费、补差金额、补贴上限等政策数值；这些是规则本身，不属于商品实时价格/库存，因此不触发商品文档的价格泄漏检查。

## 六、非 Markdown 原始文件

`data/policies/raw/` 存放未入库的原始文件，清单见 `data/policies/registry.csv`：

| 格式 | 典型内容 | 建议解析工具 |
|---|---|---|
| PNG/JPG | 流程图、信息图、扫描件 | qwen-vl-ocr / 多模态模型 / OCR（PaddleOCR、Tesseract） |
| CSV/XLSX | 运费表、时效表、价保表、估价表、发票表 | csv / openpyxl / pandas |
| PDF（文本型） | 政策全文 | pdfplumber / pypdf |
| PDF（扫描型） | 扫描件，无文本层 | qwen-vl-ocr / OCR（PaddleOCR、Tesseract） |
| DOCX | Word 政策文档 | python-docx |
| HTML | 网页表格 | BeautifulSoup / trafilatura |

原始文件在解析前不进入 RAG，避免把无文本层扫描件或图片当成空文档。第一批解析结果写入 `data/policies/parsed/`，状态记录在 `parse_report.json` 和 `registry.csv`；重复文件标记 `duplicate_of`，不直接入库。
