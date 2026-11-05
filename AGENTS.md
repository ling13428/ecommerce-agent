# 电商客服 Agent

> 本文件是本项目的唯一目标与约定来源。每次在该目录下开启新对话，先完整阅读本文件，再开始任何工作。
> 若需求与本文件冲突，先向用户确认并更新本文件，不要默默偏离。

## 一、项目定位与总目标

**定位**：个人独立开发的电商智能客服 Agent。功能对标生产场景，工程按生产标准设计；业务数据由可替换的 Mock Provider 承载，接口与 Schema 与真实系统对齐。目标是交付一个**可演示、可评测、可讲清技术决策**的接近生产形态系统，不声称已通过生产验证。

**总目标**：覆盖「售前咨询 — 售中订单服务 — 售后处理」全链路：

- 以**多轮对话 + 工具调用（Tool Calling）+ 知识库 RAG** 为核心；
- 能查真实业务数据（商品、库存、订单、物流、售后），而不是靠模型编造；
- 低置信度、用户要求或情绪负面时能**无缝转人工**；
- 配套运营后台、会话记录与效果评测，形成闭环；
- 量化目标：替代 70% 以上的常见重复咨询，首响 < 1 秒，业务问答准确率 ≥ 90%，关键写操作 100% 经用户确认，多实例部署下会话不丢、写操作不重复。

**三层目标**

| 层 | 目标 | 衡量方式 |
|---|---|---|
| 能力 | 能答、能查、能办、能兜底 | 场景评测集准确率 ≥ 90% |
| 工程 | 接近可上线形态 | 本文件「六、验收标准」工程项全绿 |
| 交付 | 可演示、可复述 | 一键启动 demo + 架构与决策文档 |

## 二、目标用户与场景

- 买家：咨询商品、查订单物流、申请退换货、投诉。
- 客服/运营：接管会话、维护知识库、查看会话与质检。
- 中小商家：希望低成本接入一个可配置的客服机器人。**v1 为单店铺**，不做多租户 SaaS，但数据模型预留店铺维度字段。

## 三、功能范围

### P0（必须完成）

| 场景 | 内容 |
|---|---|
| 会话接入 | Web 聊天窗口 + SSE 流式 API；多轮上下文与槽位补全（如缺订单号时追问） |
| 售前咨询 | 规格、价格、库存、活动、发货时效；参数/卖点/FAQ 知识问答 |
| 订单服务 | 订单查询、物流跟踪；取消订单、修改地址、拦截快递 |
| 售后服务 | 退换货政策问答、创建售后工单、查询处理进度 |
| 人机协同 | 低置信度/负面情绪/敏感操作转人工；坐席接管、会话摘要 |
| 安全合规 | 提示词注入防护、敏感信息脱敏、敏感词过滤、工具权限分级（只读/写） |
| 工程底座 | 鉴权、幂等、限流、会话与轨迹持久化、CI、容器化 |

### P1（MVP 之后）

- 运营看板：解决率、转人工率、首响、满意度、会话归档与质检。
- Agent 端到端评测集与压测报告。
- 个性化推荐与导购、催付/挽回。
- 多平台渠道接入（微信公众号/小程序、抖音、淘宝/京东客服开放平台）。
- 情绪识别、主动营销、坐席 Copilot、自动质检。
- 图片/语音理解（订单截图 OCR、商品图识别）。

### 明确不做（v1 范围外）

- 不自研大模型；不做完整 OMS/ERP/支付系统。
- 不做外呼与电话客服；不做真人坐席排班系统。
- 不做多租户 SaaS（单店铺；预留店铺维度字段）。
- 不做图片/语音理解（列 P1）。
- 不追求“高并发已验证”：只做可压测、可水平扩展的设计。

## 四、技术栈方案

**总览**：Python 单体服务 + 图编排 + PostgreSQL/pgvector + Redis，Docker Compose 三容器起步；不引入 K8s、消息队列、微服务。

### 选型

| 层 | 选型 | 状态 |
|---|---|---|
| 语言/运行时 | Python 3.12 | 已有 |
| Web 框架 | FastAPI + Uvicorn | 已有 |
| 数据校验/配置 | Pydantic v2 + pydantic-settings | 已有 |
| 流式协议 | SSE（`text/event-stream`，手写 + 心跳） | 已有（心跳可配） |
| Agent 编排 | **LangGraph**（StateGraph + checkpointer） | 已有（`graph` 默认，`legacy` 可回退）；`interrupt()` 中断恢复已接 |
| 模型接入 | OpenAI 兼容 SDK，默认 DeepSeek `deepseek-chat`，供应商可切 | 已有 + 熔断/备用 |
| 工具层 | 自研 `ToolSpec` 注册表 + Pydantic Schema；内部 MCP server（commerce / catalog / knowledge） | 已有（`TOOL_BACKEND=local|mcp`，默认 local 可回滚） |
| 意图路由 | 规则层 + LLM 结构化分类兜底 | 已有（L1 规则 + L2 LLM） |
| Embedding | 千问 `text-embedding-v3`，1024 维（DashScope） | 已有 |
| 向量库 | PostgreSQL 17 + pgvector（HNSW，余弦） | 已有 |
| 稀疏检索 | 纯 Python BM25 + jieba + RRF | 已有 |
| Rerank | bge-reranker-base（CrossEncoder） | 已有，**默认关闭** |
| 业务库 | PostgreSQL（订单/售后/工单/审计） | 已有（`ORDERS_BACKEND=postgres`，SQLite 可回退） |
| 热状态 | **Redis**：会话缓存、限流、幂等键 | 已有（`CACHE_BACKEND=redis`，memory 可回退） |
| 持久状态 | **PostgreSQL**：消息、trace、checkpoint、业务单据 | 已有（会话 payload + checkpoint） |
| 可观测 | JSON 日志 + 请求指标 + 告警 Webhook + 每轮 trace | 已有（OTLP 留 M7） |
| 评测 | 自研评测脚本 + pytest | 检索已有，M7 补 Agent E2E |
| 前端 | 零构建原生 HTML/CSS/JS，FastAPI 静态托管 `/web` | 已有，不迁移 |
| 容器 | Docker Compose：api + 3 个 MCP server + postgres + redis | 已有（`docker compose up`） |
| CI | GitHub Actions（ruff + mypy + pytest） | 已有（本地全绿，待推远端验证） |
| 依赖管理 | uv（`pyproject.toml` + `uv.lock`） | 已有 |
| 测试 | pytest + pytest-asyncio + httpx + respx | 已有 |

### 运行时拓扑

```
[浏览器]
   │ HTTPS
   ▼
[nginx / 反代]            ← M4（本地可省）
   ▼
[api: FastAPI + Uvicorn]  ← 无状态，可多实例
   ├── mcp-commerce   订单/物流/售后/支付/优惠（9 工具，写操作需审批令牌）
   ├── mcp-catalog    商品主数据 + 推荐（2 工具）
   ├── mcp-knowledge  知识库检索（1 工具，只返回检索结果）
   ├── Redis          会话缓存 / 限流 / 幂等键 / 路由缓存
   ├── PostgreSQL     pgvector 知识库 + 业务数据 + checkpoint + trace
   └── LLM Provider   DeepSeek（主）/ 备用供应商（熔断切换）
```

### 关键决策（已定）

1. **只引入 `langgraph` + `langchain-core`，不全盘用 LangChain**：需要状态图、并行工具、中断恢复，不需要 Chain/Memory 那套抽象；工具层继续用自研 registry，对 LangGraph 只做 adapter。
2. **工具层按能力拆内部 MCP server**：commerce / catalog / knowledge 三类工具走 MCP（streamable HTTP），Agent 只保留策略、确认、会话与信任边界；`TOOL_BACKEND=local|mcp` 一键回滚。工具令牌（上下文 + 写审批）用 HMAC 签名，`buyer_id` 不走工具参数；写操作在 server 侧强制校验审批令牌与幂等键。外部系统（平台客服、物流、支付、ERP）暂不接入。
3. **状态分层**：热状态（会话缓存、限流、幂等）放 Redis，利用 TTL 与原子操作；持久状态（消息、trace、checkpoint、业务单据）放 PostgreSQL，保证可查询、可审计。不把 Redis 当唯一存储。
4. **Rerank 保留但默认关闭**：`RERANK_ENABLED=false` 现状不变；M7 评测若在 Recall@5 上有稳定提升再开，且考虑拆独立进程，避免 torch 拖慢主服务。
5. **业务库双后端**：`ORDERS_BACKEND=postgres|sqlite`；Postgres 走连接池与事务，SQLite 仅作本地/测试回退。Windows 上异步 psycopg 不可用（ProactorEventLoop），本地 checkpoint 用 sqlite，容器内用 postgres。
6. **不上 Celery/Kafka/向量专用库**：当前无长任务与跨服务事件；pgvector 数据量小（342 父块 / 1504 子块），换库零收益。
7. **前端不迁 React/Next.js**：零构建页面已够用；等运营后台出现复杂交互再单独拆。

### 明确不引入

LangChain 全家桶、LlamaIndex、Milvus/Qdrant、Kafka/RabbitMQ、Kubernetes、Celery、Next.js/React、LangSmith（云端付费，改用 OpenTelemetry 留扩展口）。面试中须能说明“为什么不用”。

### 目录结构（当前实际）

```
电商客服/
├─ AGENTS.md
├─ pyproject.toml          # 依赖与工具配置（uv）
├─ uv.lock                 # 锁定依赖版本
├─ Dockerfile              # 应用镜像（不含可选 rerank 依赖）
├─ docker-compose.yml      # api + mcp-commerce/catalog/knowledge + postgres + redis
├─ .github/workflows/ci.yml
├─ .env.example
├─ main.py                 # FastAPI 应用、SSE、鉴权、管理接口
├─ agent/                  # 编排循环、路由、会话、持久化
├─ core/                   # 配置、安全、日志、限流、鉴权、Redis 客户端
├─ tools/                  # 工具实现、注册表、MCP 客户端与异步执行
├─ mcp_servers/            # 内部 MCP server：commerce / catalog / knowledge
├─ rag/                    # 清洗、切片、embedding、检索、rerank
├─ services/               # 订单等业务 Provider
├─ frontend/               # 零构建单页：买家端 / 商家工作台
├─ data/                   # 商品、政策、订单、评测集、会话库
├─ docker/                 # PostgreSQL 初始化 SQL
├─ scripts/                # 数据生成、解析、入库、评测
├─ tests/                  # pytest
├─ reports/                # 数据质量与检索评测报告
└─ docs/                   # 数据卡、约定、项目状态
```

## 五、核心设计原则

1. **数据必须来自工具**：订单号、物流、库存等事实性信息禁止模型编造；工具失败要如实告知。
2. **写操作必须确认**：取消订单、退款、改地址等先复述影响，用户明确确认后才执行；接口需幂等键。
3. **可转人工**：任何不确定场景都有兜底路径，转接时携带结构化会话摘要。
4. **Mock 优先但必须经 Provider 抽象**：Mock 与真实实现同签名，替换数据源不改工具层。
5. **可评测**：每个核心能力都要有可回归的测试用例，prompt 与模型变更必须跑评测。
6. **安全默认**：密钥只放 `.env`（不入库）；日志脱敏；防提示词注入与越权调用。
7. **中文优先**：界面、prompt、文档默认中文。
8. **服务无状态**：API 进程不持有跨请求状态，热状态进 Redis、持久状态进 Postgres，保证可水平扩展。
9. **每轮可复盘**：路由、模型轮次、工具参数与结果、RAG 命中、最终动作全部落库。

## 六、验收标准（Definition of Done）

**功能**

- 典型场景评测集 ≥ 200 条（售前/订单/售后/转人工/安全），整体准确率 ≥ 90%。
- 所有事实性回答均可追溯到工具结果或知识库引用。
- 写操作 100% 经过用户确认，且重复请求不会重复执行。
- 转人工判定覆盖：低置信度、用户要求、负面情绪、敏感操作。

**工程**

- 依赖锁定 + 一条命令可复现环境；`lint`、`typecheck`、`test` 全部通过。
- `docker compose up` 一键启动（api + postgres + redis）并完成一次完整对话演示。
- 双 worker 下：会话不丢、限流生效、写操作不重复。
- LLM 故障可切换备用或降级，不整站不可用。
- 日志可检索、关键指标可观测、异常有告警。

**对外表述红线**

- 未接入真实业务数据前，只说“按生产标准设计”，不说“已上线/已生产验证”。
- 未压测前，不写“高并发”。

## 七、路线图

**已完成**

- **M0 骨架**：FastAPI 脚手架、SSE 流式、配置与日志、限流。
- **M1 售前/RAG**：100 商品 / 300 商品文档 / 35 政策文档 / 1504 子块；pgvector + BM25 + RRF；引用与低分拒答。
- **M2 交易**：订单/物流/售后查询 + 取消/改地址/拦截/售后工单（确认 + 幂等 + 状态机）。
- **M3 人机协同**：转人工、商家接管、人工回复、每轮运行轨迹、SQLite 持久化、买卖家鉴权。
- **M5 编排升级**：LangGraph 双轨（`AGENT_ENGINE=graph|legacy`）、只读工具并行、批量工具丢调用修复、checkpointer + `interrupt()` 中断恢复、路由 L2 结构化分类。
- **M4 生产底座**：`pyproject`/`uv.lock`、ruff/mypy、Dockerfile、Compose（api + postgres + redis）、CI、会话/限流/幂等迁 Redis、业务数据/消息/trace/checkpoint 落 Postgres、PG 连接池、会话清理、SSE 心跳、JSON 日志与指标、告警 Webhook、LLM 熔断与备用供应商。

**待推进**（按每周 15–20 小时投入估算）
- **M6 真实数据（2–4 周）**：**进行中**。已完成：Saleor 本地部署、100 个商品与 60 笔订单/13 条售后导入、商品/订单/物流/售后只读接入（`PRODUCT_PROVIDER` / `ORDER_PROVIDER=saleor`，GraphQL）、手机号 + 短信验证码登录、操作审计、按买家灰度/回滚。待做：写操作接入（需对方 API）、Saleor 原生 return/refund、真实短信网关。
- **M7 评测闭环（持续）**：**进行中**。已完成：检索 gold 80 条、Agent 场景集 60 条（路由/工具评测）、压测脚本与首轮报告（50 req / 10 并发，66.4 RPS，p95 103ms，问候路径）、运营看板（解决率/转人工率/首响/路由分布）。待做：gold 80→200、Agent 场景集 60→200、LLM 端到端评测、带工具/LLM 的压测。

顺序约束：**M4 必须先于 M6**；M5 可与 M4 并行，但不得留下半迁移状态。每个里程碑交付后更新 `docs/PROJECT_STATE.md`。

## 八、给后续对话的工作约定

- 开始任务前先读本文件，确认当前处于哪个里程碑。
- 改动功能范围、技术选型或验收标准时，同步更新本文件，并在回复中说明变更。
- 不要一次性铺开所有功能：按里程碑推进，每个里程碑交付可运行、可演示的增量。
- 需要用户决策时（如接入哪个平台、用哪个模型供应商），先提问再实现。
- 不要提交任何密钥、真实客户数据或未脱敏日志。

## 九、项目记忆与跨会话接续

- **稳定目标与约定**记录在本文件；**当前进度、决策、下一步**记录在 `docs/PROJECT_STATE.md`。
- `opencode.json` 已将 `docs/PROJECT_STATE.md` 加入 `instructions`，新会话会自动加载。
- 每次开始任务前，先读 `docs/PROJECT_STATE.md`，确认已完成到哪里、下一步是什么。
- 每次会话结束前，执行 `/save-memory` 或手动更新 `docs/PROJECT_STATE.md`；只写摘要，不写原始对话和大段代码。
- 不要记录 API Key、密码、真实客户数据或未脱敏日志。
- 需要完整原始对话时，用 `opencode export <sessionID>` 导出到 `docs/transcripts/`，按需归档，不自动注入上下文。
- 想接着上一次会话继续聊，可用 `opencode -c`（最近一次）或 `opencode -s <sessionID>`。
