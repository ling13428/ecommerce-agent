# 项目状态与记忆

> 本文件用于跨会话接续。每次新会话开始先读本文件，结束前更新。
> 只记录长期有用的信息：进度、决策、下一步、坑。不要粘贴大段代码或原始对话。
> 最后更新：2026-11-05

## 一、当前进度

- 当前里程碑：**M6 收尾 + M7 评测进行中**：真实数据只读/登录/审计/灰度已完成；Agent 场景集 60 条、首轮压测、运营看板已落地；M4 + 工具层 MCP 化已完成（CI 待推远端验证）
- 2026-10-31 新增：内部 MCP server（commerce / catalog / knowledge）、`TOOL_BACKEND=local|mcp`、工具上下文/写审批令牌、server 侧幂等；外部 MCP 暂缓
- 已完成：
  - 环境：Python 3.12（使用 `py -3.12`），项目根目录虚拟环境 `.venv`
  - M0 流式骨架：`/health`、自定义 `/docs`、`POST /api/chat/stream` SSE
  - 配置、安全、日志、限流（`core/`）
  - 工具白名单 + Pydantic 校验 + 写操作门禁/幂等（`tools/registry.py`）
  - LLM tool-calling 循环、超时、最大步数、转人工（`agent/llm_agent.py`）
  - 内存会话、多轮历史、待确认操作（`agent/session.py`）
  - mock 商品工具与规则版降级 Agent（`tools/products.py`、`agent/mock_agent.py`）
  - **真实模型冒烟**：DeepSeek `deepseek-chat`，9 轮 HTTP 验证通过；首字 0.2–0.8s，单轮 0.5–1.8s
  - **商品库**：虚构品牌「烬狐 EMBERFOX」，100 个商品（键盘 40 / 鼠标 35 / 耳机 25），全部为具体型号（VK75 Pro、VM9 Ultra、AH9 Pro 等）；9 个缺货、8 个低库存；商品主数据在 `data/products/catalog.json`
  - **商品文档**：100 个商品 × 3 篇（概述/参数/FAQ），共 300 篇；带 YAML 元数据，不含价格/库存/活动
  - **政策文档**：35 篇 Markdown，覆盖退换货、发票、物流、价格保护、以旧换新、安全边界、平台规则；含 2024/2026 新旧版本冲突样本
  - **未入库原始文件**：27 个，含 PNG 流程图、CSV/XLSX 表格、文本 PDF、扫描件 JPG/无文本层 PDF、DOCX、HTML；清单与解析工具见 `data/policies/registry.csv`
  - **两批 raw 解析**：27 个文件全部转 Markdown（18 个结构化格式 + 9 个 OCR），8 个重复（5 XLSX + 1 HTML + 2 JPG），0 待 OCR、0 失败；结果在 `data/policies/parsed/`
  - **已选入库**：5 个 CSV 表格 + 2 个扫描件（回收单、平台公告），共 7 篇，放在 `data/policies/selected/`
  - **清洗切片**：`rag/clean.py`、`rag/chunk.py`、`scripts/build_chunks.py`；结构感知 + 父子块；支持多目录输入；产出 342 父块 / 1504 子块
  - **Embedding**：千问 `text-embedding-v3`（DashScope OpenAI 兼容），1024 维；1504 条约 91s
  - **向量存储**：PostgreSQL 17 + pgvector 0.8.7（Docker，本机 5433）；`knowledge_parents` 342 行、`knowledge_chunks` 1504 行；HNSW 余弦索引
  - **入库**：`scripts/embed_and_ingest.py`；批量 10、重试、维度校验、`ON CONFLICT` 幂等；`--prune` 替换旧库，当前为 342/1504
  - **检索**：`rag/search.py`；查询 embedding → pgvector 候选 → 父块去重 → 引用 + 低分拒答；默认 `top_k=5`、`min_score=0.55`、候选 `max(top_k*4,20)`；支持 `product_id` 过滤
  - **评测脚本**：`scripts/eval_retrieval.py`；gold JSONL → Recall@k / Hit@k / MRR / 误拒率 / 拒答准确率；支持 `--query` 单条冒烟、`--json` 报告
  - **80 条 gold 集**：`data/eval/retrieval_gold.jsonl`（70 可回答 / 10 拒答）；baseline Recall@5 92.1%、Hit@5 98.6%、MRR 0.725、误拒率 0%、拒答准确率 40%
  - **RAG 接入 Agent**：`tools/knowledge.py` 与 `search_knowledge` 工具；返回父块正文 + `doc_id/section/source`；低分/空结果确定性转人工；工具在 `asyncio.to_thread` 中执行，不阻塞事件循环
  - **阈值校准**：`RAG_MIN_SCORE=0.55`；探针显示相关查询 0.57–0.77、无关查询 0.35–0.46
  - **体验修复**：写操作由模型直接调工具、服务端只确认一次；转人工时若模型已说“转接”，不再追加固定话术
  - **商品实体识别**：`tools/products.py` 改为从 `catalog.json` 加载；`detect_product_id` 支持 P 编号、型号正则（含 Pro/Ultra/SE/Plus/Mini/Wireless）、系列回退和全名匹配；`search_knowledge` 与 Agent 层在缺 `product_id` 时自动补全并过滤
  - **检索冒烟**：查询“VK75 Pro 的触发键程”top1 P2001-01（0.723）；工具层带产品过滤后命中 P2001-02/03；“今天天气怎么样”低分拒答
  - **前端单页**：`frontend/`（原生 HTML/CSS/JS，无 Node 依赖），FastAPI 托管于 `/web/`，支持买家端 / 商家工作台切换
  - **买家端**：SSE 流式聊天、工具调用提示、写操作确认按钮、转人工横幅、会话 ID 持久化（localStorage）、人工回复轮询
  - **商家工作台**：会话列表、会话详情、人工接管/转回机器人、人工回复实时同步到买家端；`#merchant` 可深链
  - **接管语义**：`handoff` 或商家接管后 `human_mode=true`，买家消息只入库不再触发 LLM，等待人工回复
  - **新增接口**：`GET /api/admin/sessions`、`GET /api/admin/sessions/{id}`、`POST /api/admin/sessions/{id}/takeover`、`POST /api/admin/sessions/{id}/reply`、`GET /api/chat/messages`
  - 消息改为带自增 `id` 与可选 `source=human`；`snapshot()` 仅输出 `role/content` 供模型使用
  - 真实 HTTP 冒烟：商品问答 → 工具调用成功 → 商家接管 → 人工回复 → 买家轮询可见
  - **数据配套**：`data/catalog/source_registry.csv`（300 条）、`products.csv`、`intent_matrix.csv`（32 行）、`data/policies/registry.csv`（62 条）、`data/policies/parsed/parse_report.json`、`data/policies/parsed/ocr_cache.json`、`data/policies/selected/manifest.json`、`data/eval/retrieval_gold.jsonl`（80 条）、`data/policies/README.md`、`docs/datasheet.md`、`reports/data_quality_report.md`、`reports/retrieval_eval.json`
  - **生成脚本**：`scripts/generate_catalog.py`、`scripts/generate_product_docs.py`、`scripts/generate_policy_docs.py`、`scripts/parse_policy_raw.py`、`scripts/select_policy_parsed.py`、`scripts/build_data_reports.py`；确定性生成，可重复执行
  - **Agent 运行轨迹（商家端）**：每轮用户消息生成结构化 trace（接收 → 模型轮次 → 工具调用 → RAG 召回 → 转人工/确认 → 最终回复）；`GET /api/admin/sessions/{id}` 返回 `traces`；商家工作台可点“运行轨迹”或每条机器人回复下方的链接查看，RAG 展示 `doc_id/标题/章节/来源/分数/旧版标记/召回原文`
  - trace 记录工具参数与结果、耗时、模型名、状态（完成/转人工/待确认/取消/降级/失败/人工接管）；**默认不限制轮次，全部保留**
  - **会话与轨迹持久化**：SQLite（`data/sessions/sessions.db`，默认开启）；会话、消息、trace、待确认操作、人工模式跨重启恢复；商家端会话列表显示轨迹轮数，轨迹面板提供历史轮次切换
  - 消息完整保留，LLM 上下文只取最近 `context_messages=20` 条
  - **RAG 元数据过滤**：默认排除 `deprecated=true`；`search_knowledge(..., include_deprecated=True)` 可查旧版；商品过滤同时返回 `STORE/PLATFORM`
  - **意图路由 P1（规则层）**：5 个路由 `knowledge/product/transaction/handoff/chat`；订单/物流/售后/支付/优惠/推荐不再进 RAG；工具白名单按路由裁剪；trace 记录 route/sub_intent/action/slots
  - **Mock 订单/物流/售后**：24 位买家、60 笔订单、47 条物流、13 条售后；`get_order`/`get_logistics`/`get_aftersale` 已注册；前端可登录买家；`/api/demo/buyers` 提供买家列表
  - **订单写操作 + 售后工单**：`cancel_order` / `update_address` / `intercept_parcel` / `create_aftersale`；SQLite 可变状态库、状态机校验、确认流程、幂等与操作审计
  - **支付/优惠/推荐工具**：`get_payment_methods` / `get_coupons` / `recommend_products`；48 张 mock 优惠券；推荐基于真实商品库
  - **鉴权**：`/api/admin/*` 要求 `ADMIN_TOKEN`；买家使用 `buyer_id + login_code` 登录换 HMAC Token；会话绑定买家，跨买家访问返回 403
  - **依赖与工具链**：`pyproject.toml` + `uv.lock`（137 包锁定）；`ruff`（E/F/I 规则）与 `mypy` 全绿；dev 组含 pytest/respx/pytest-asyncio
  - **容器化**：`Dockerfile`（python:3.12-slim + uv，不含 torch/rerank 可选依赖）；`docker-compose.yml` 扩为 api + postgres + redis，带健康检查；`docker compose up` 一键起
  - **CI**：`.github/workflows/ci.yml`，push/PR 执行 `uv sync --frozen` + ruff + mypy + pytest；本地已验证，未推远端
  - **Redis 热状态**：新增 `core/cache.py`；会话（`RedisSessionStore`）、限流（INCR+EXPIRE）、写操作幂等（`SET NX` 锁 + 结果键，24h）全部走 Redis，`CACHE_BACKEND=memory` 可回退
  - **多实例验证**：跨进程会话可见、限流共享、同一幂等键只执行一次；双 uvicorn worker 下会话读取一致（admin 详情 8 次请求均返回 2 条消息）
  - **业务数据迁 Postgres**：`services/orders.py` 双后端（`ORDERS_BACKEND=postgres|sqlite`），Postgres 走 `psycopg_pool`；占位符/事务/`INSERT` 方言适配；启动幂等建表 + 空库从 JSON seed；本地与容器均验证取消订单、跨买家隔离、物流查询
  - **checkpoint 迁 Postgres**：`agent/checkpoint.py` 增加 `AsyncPostgresSaver` 后端；容器内验证「创建待确认 → 重启 api → 确认」从 PG 断点恢复并只执行一次
  - **PG 连接池**：新增 `core/db.py`（`psycopg_pool`，可配置大小/超时），业务库复用连接
  - **消息/trace 落 Postgres**：`SESSION_STORE_BACKEND=postgres`；会话整段 payload（含消息与 trace）写 `chat_sessions` JSONB；Redis 仅作热缓存，miss 时自动从 PG 回源并回填
  - **会话清理**：`scripts/prune_sessions.py` 按 `SESSION_RETENTION_DAYS`（默认 30）删除过期会话；Redis 侧仍由 TTL 自动过期
  - **SSE 心跳**：`core/sse.py` 按 `SSE_HEARTBEAT_SECONDS` 注入 `: ping` 注释帧；客户端断开时取消任务
  - **可观测**：`core/logging.py` 支持 JSON 日志；`core/metrics.py` 记录请求、延迟、工具/转人工/LLM 错误；`GET /api/admin/metrics`；`core/alerts.py` 写 ERROR 日志并可 POST 到 `ALERT_WEBHOOK_URL`
  - **LLM 熔断/备用**：主模型连续失败达到阈值后进入冷却期，改用 `LLM_FALLBACK_*` 供应商；`resolve_llm()` 在 graph/legacy 两个引擎共用
  - **工具层 MCP 化**：新增 `mcp_servers/`（commerce 9 工具 / catalog 2 工具 / knowledge 1 工具），streamable HTTP + `/health`；`scripts/run_mcp_servers.py` 本地一键起，`scripts/smoke_mcp.py` 连通性检查
  - **Agent 侧路由**：`ToolSpec.server` 标记归属；`execute_tool_async` 按 `TOOL_BACKEND=mcp` 走 MCP，`transfer_to_human` 永远留在 Agent；graph/legacy/确认回退三条路径全部改成异步执行
  - **工具令牌**：`core/tool_auth.py` 签发上下文令牌与写审批令牌（HMAC、TTL、args 摘要、jti）；`buyer_id` 只存在于签名令牌中，不作为工具参数暴露给模型
  - **server 侧强制约束**：commerce 读工具必须带上下文令牌；写工具必须带审批令牌且参数摘要匹配；幂等（jti + 参数摘要）下沉到 server，Redis 不可用时回退进程内存
  - **知识工具策略上移**：`search_knowledge` 只返回 `abstained/score/hits`，低分转人工由 Agent 的 `_finalize_result` 统一决定，local/mcp 两个后端行为一致
  - **M6 商品只读接入 Saleor**：本地部署 Saleor 3.24（Windows 加 `resource` 兼容补丁）；100 个商品导入 `emberfox` 渠道（CNY）；`PRODUCT_PROVIDER=saleor` 时 `get_product` 走 GraphQL 取真实价格/库存，`mock` 可一键回退
  - **真实 HTTP 链路验证**：容器内 `TOOL_BACKEND=mcp` → `mcp-catalog` → `host.docker.internal:8001/graphql/`，回答中价格 969、库存 56 来自 Saleor
  - **契约与故障测试**：`tests/test_saleor_products.py`（字段映射、超时、500、商品不存在），HTTP 用 `respx` 模拟
  - **M6 订单只读接入 Saleor**：`orderBulkCreate` 导入 60 笔订单（externalReference = 订单号、metadata 存 buyer_id/legacy_status/tracking 等）；`ORDER_PROVIDER=saleor` 时 `get_order`/`list_orders` 走 GraphQL，按 metadata 校验买家归属
  - **验证**：本地 `get_order` 返回 delivered、1448 元、2 件、物流单号；跨买家返回 None；容器内 `TOOL_BACKEND=mcp` → mcp-commerce → Saleor，Agent 回答“查到 5 笔订单”
  - **M6 物流只读接入 Saleor**：从订单 `fulfillments` 取运单号/状态/明细；`get_logistics`/`list_shipments` 走 GraphQL，支持按订单号或运单号查询，并按 metadata 校验买家归属
  - **验证**：本地按订单/运单查询均命中；跨买家返回 None；容器内 `get_logistics` → mcp-commerce → Saleor，Agent 回答“5 条物流记录”
  - **M6 售后只读接入 Saleor**：新增 `scripts/sync_aftersales_to_saleor.py`，把 13 条售后写入订单 metadata；`get_aftersale`/`list_aftersales` 走 GraphQL 读取并映射
  - **验证**：`AS-930-0002` 返回退货退款/待商家处理/3197 元；跨买家 None；容器内 Agent 回答“3 条售后记录”
  - **M6 真实登录（手机号 + 验证码）**：新增 `core/otp.py`、`core/sms.py`；`POST /api/auth/buyer/send-code` 与 `POST /api/auth/buyer/otp/login`；OTP 存 Redis（memory 回退），TTL/尝试次数/发送冷却可配；旧 `buyer_id + login_code` 保留作演示回退
  - **买家手机号映射**：由脱敏手机号 + buyer_id 哈希生成稳定登录手机号，`/api/demo/buyers` 返回 `login_phone`；前端登录改为“手机号 + 验证码”
  - **验证**：容器内发送验证码 → 登录 → `/me` → 对话查订单（5 笔），全链路通过
  - **操作审计**：新增 `core/audit.py` 与 `audit_log` 表；写操作（含 confirm_required 尝试）和敏感读（订单/物流/售后）落库，记录 actor/session/tool/target/digest/ok/transport；`GET /api/admin/audit` 可查
  - **灰度/回滚**：`SALEOR_ROLLOUT_PERCENT` 按买家哈希放量，`SALEOR_ALLOWLIST` 白名单；`ORDER_PROVIDER=mock` 或 percent=0 立即回滚
  - **M7 评测启动**：新增 60 条 Agent 场景集（`data/eval/agent_gold.jsonl`）、`scripts/eval_agent.py`（路由 / 工具两种模式）、`scripts/load_test.py`（SSE/健康检查压测）
  - **首轮结果**：路由 L1 60/60（100%），工具合同 47/47（100%）；压测 50 req / 10 并发，66.4 RPS，p95 103ms（问候路径，不调 LLM）
  - **运营看板**：`GET /api/admin/dashboard` 聚合解决率、转人工率、首响均值/P95、路由分布、转人工原因；商家工作台新增 KPI 面板（15s 刷新）
  - **首响口径**：trace 记录 `first_response_ms`（从收到消息到第一个 `delta`），仅统计有文本回复的轮次
  - **工具执行硬化（2026-11-05）**：`tools/registry.py` 新增工具级超时、只读重试、每工具熔断、专用线程池与并发信号量；错误统一为 `error_code/retryable/side_effect_committed`；出站结果做信封校验、可选 `result_model` 校验与大小截断；写操作幂等锁改为 owner token（防误删）、心跳续租、不确定结果短 TTL 缓存，内存兜底条数可配；`core/metrics.py` 新增 per-tool 调用/失败/超时/延迟/错误码指标
  - 测试 186 个用例全部通过（新增工具运行时硬化测试）
  - Git 已初始化（`main` 分支），`.env`/`.venv`/`.idea` 已忽略；**未配置远程仓库**
- 进行中：**M7 评测闭环** — Agent 场景集 60 条、路由/工具评测、首轮压测、运营看板已完成；待扩到 200 条、补 LLM 端到端评测
- 下一步（按价值排序）：
  1. **M7**：检索 gold 80→200、Agent 场景集 60→200、补 LLM 端到端评测（真实模型）、把压测扩到带工具/LLM 的路径
  2. **M6 收尾**：等对方提供写 API 后接取消/改地址/拦截/售后；替换为 Saleor 原生 return/refund；接真实短信网关
  3. 表格类问题优先表格文档（`unit_kind=table`）；处理剩余 12 篇非重复解析文档
  4. 多租户/多店铺隔离；浏览器多标签/多端联调

## 二、关键决策

- 后端：Python + FastAPI，流式用 SSE（`text/event-stream`）
- 聊天请求用 `POST /api/chat/stream`，消息放请求体；暂不用 WebSocket
- 本地开发文档页使用 `fastly.jsdelivr.net` 镜像
- 模型协议：OpenAI 兼容，默认 DeepSeek 配置，可改 `.env` 切换供应商
- 密钥：`.env` 不入库；代码只通过 `pydantic-settings` 读取；日志不打印 Key
- 工具：只允许调用 `TOOLS` 中注册的工具，参数用 Pydantic 校验
- 工具分级：`read` 直接执行；`write` 必须确认且需要幂等键；`handoff` 触发转人工
- 会话：当前为**进程内内存**，重启即丢失；`session_id` 由服务端生成或客户端传入
- 写操作确认：LLM 只生成 `confirm_required`，下一轮用户回复“确认”才真正执行
- 失败降级：LLM 未配置或调用失败且尚未输出内容时，回退规则版 mock
- 前端只调用后端 `/api/chat/stream`，不直连模型、不持有 Key
- **前端形态**：零构建静态页（原生 JS），FastAPI `StaticFiles` 托管在 `/web`；不引入 Node/Next.js，等需要复杂后台再迁移
- **双端切换**：同一页面买家端 / 商家工作台，`#merchant` 可深链；商家端轮询会话列表与详情
- **人工接管**：`handoff` 事件或商家点“人工接管”后 `human_mode=true`；此后买家消息只落库、不再调用 LLM，商家回复以 `source=human` 写入
- **买家侧同步**：买家端轮询 `GET /api/chat/messages`，只返回 `source=human` 的新消息，避免与 SSE 流式消息重复
- **消息结构**：每条消息带自增 `id`；消息默认完整保留，`snapshot()` 只取最近 `context_messages=20` 条、只输出 `role/content` 给模型，`public_messages()` 过滤内部 `system` 备注
- **运行轨迹**：trace 与用户消息通过 `user_message_id` 关联，存在 `SessionState.traces`；**默认不限制轮次，全部保留**；工具结果按类型脱敏为 `rag/product/write/handoff/error` 细节，RAG 记录命中文档的 `doc_id/title/section/source/score/deprecated/content`
- **trace 采集方式**：`run_llm_agent` 额外产出 `llm_step` 事件并给 `tool_call` 附带 `detail`；`agent_stream` 消费这些内部字段后不转发给买家 SSE，只写入会话 trace
- **会话持久化**：`agent/session_store.py` 使用 SQLite（`SESSION_DB_PATH`，默认 `data/sessions/sessions.db`）保存每个会话的完整 JSON（消息、trace、待确认操作、人工模式、自增 ID）；启动时全量加载进内存，每次变更同步落库；关闭 `SESSION_PERSISTENCE` 可回到纯内存模式
- **持久化边界**：当前 SQLite 适合单进程本地演示，多 worker/多实例需要迁移 PostgreSQL/Redis；旧版本丢失的会话和 trace 无法恢复，只保证本次改动后的新数据
- SSE 事件（买家侧）：`start`、`tool_call`、`delta`、`confirm_required`、`confirmation_cancelled`、`handoff`、`fallback`、`error`、`done`
- 限流：按 `session_id` 每分钟请求数限制，默认 20
- 当前代码暂放项目根目录，后续再整理到 `backend/app/`
- **写操作确认主体**：买家确认即可，不建平台运营审批；高风险或超政策场景走转人工
- **产品定位**：分流器 + 答疑 + 异常处理 + 转人工；KPI 是首响、解决率、转人工率；常规取消/退款优先引导自助入口
- **写操作优先级**：真实价值在改地址、拦截快递、补发/换货、政策外补偿等无自助入口场景，常规取消不是重点
- **RAG 数据策略**：不使用真实客户对话/订单；公开法规与平台规则（改写 + 标来源和生效日期）+ 自建店铺知识 + 合成商品/订单；价格、库存、订单状态等结构化事实继续走工具，不进 RAG
- **RAG 目标规模**：当前已落地 **100 商品 / 300 商品文档 / 35 政策文档 / 7 篇已选解析文档 / 1504 子块**（键盘 40、鼠标 35、耳机 25，9 个缺货）；80 条 gold 已建立
- **RAG 质量要求**：回答带 `doc_id/section/source` 引用；低分拒答并转人工；记录检索命中与拒答原因
- **商品文档边界**：只写卖点、参数、场景、保养、FAQ；价格/库存/活动/发货时效仍由 `get_product` 工具返回，避免两处数据冲突
- **商品主数据**：`data/products/catalog.json` 由 `scripts/generate_catalog.py` 确定性生成；`tools/products.py` 启动时加载；不要直接改 JSON，改脚本后重新生成
- **文档生成**：300 篇商品文档由 `scripts/generate_product_docs.py` 生成；35 篇政策文档由 `scripts/generate_policy_docs.py` 生成；不要逐篇手改 `docs/` 下的 Markdown
- **政策文档类型**：`store_policy`、`platform_rule`、`policy_faq`、`refusal_boundary`、`policy_notice`；已扩展 `rag/clean.py` 校验
- **政策作用域**：店铺政策 `product_id=STORE`、平台规则 `product_id=PLATFORM`；检索带商品过滤时，SQL 同时返回该商品 + STORE + PLATFORM 文档
- **政策有效期**：front matter 记录 `effective_date`、`valid_until`、`review_date`、`version`、`deprecated`、`supersedes/superseded_by`；旧版保留并标记 `deprecated=true`
- **政策数值**：运费、补差、补贴上限等属于政策规则，允许出现在政策文档中，不触发商品价格泄漏检查
- **未入库原始文件**：图片、CSV/XLSX、PDF、扫描件、DOCX、HTML 暂不自动入库；`data/policies/registry.csv` 标注状态和所需解析工具
- **配套数据**：`data/catalog/source_registry.csv`、`products.csv`、`intent_matrix.csv`、`data/policies/registry.csv`、`docs/datasheet.md`、`reports/data_quality_report.md` 均不进 RAG
- **父块**：目标 600–1200 字（硬上限 1500），默认整篇或相邻小节合并；**子块**：目标 150–400 字（硬上限 500），FAQ 一组 Q&A、表格独立，最多合并 2 个 H2
- **向量方案**：千问 `text-embedding-v3`，1024 维，余弦距离；`knowledge_chunks.embedding vector(1024)` + HNSW
- **检索现状**：**单稠密索引**，未做 BM25/混合检索；先评测，出现编号/型号精确词漏召回再加第二路（RRF 融合）
- **检索实现**：子块召回 → 同父块只保留最高分子块 → 返回父块全文；`RAG_MIN_SCORE=0.55`，低于阈值确定性转人工；拒答时仍返回 hits 供评测/日志
- **元数据过滤**：默认 `deprecated=false`（SQL 层硬过滤，含父/子块 metadata），`include_deprecated=True` 放行历史版本；商品过滤 `product_id IN (该商品, 'STORE', 'PLATFORM')`；gold 中 g055/g056 逐条声明 `include_deprecated=true`
- **评测口径**：Recall@k 按期望目标覆盖率（父块或文档二选一），另报 Hit@k、MRR、可回答问题误拒率、应拒答问题准确率
- **知识工具边界**：`get_product` 管价格/库存/活动/发货时效；`search_knowledge` 管卖点/参数/使用保养/FAQ/政策；两者不交叉
- **Agent 工具执行**：同步工具统一放 `asyncio.to_thread`，避免 embedding/DB 阻塞事件循环
- **Agent 编排（2026-10-27 变更）**：引入 `langgraph` + `langchain-core`；`agent/graph_agent.py` 用 `StateGraph` 实现 `agent → tools → confirm/handoff → END`；`AGENT_ENGINE=graph`（默认）/ `legacy` 双轨，`agent/legacy_agent.py` 保留自研循环用于回退
- **LangGraph 使用边界**：工具仍走自研 `tools/registry.py`（Pydantic schema + 写操作门禁 + 幂等），不迁 LangChain Tool；模型仍用 `openai.AsyncOpenAI`，不引入 `langchain-openai`；共享 helper 在 `agent/agent_utils.py`
- **并行工具**：`tools` 节点用 `asyncio.gather` 并发执行同一轮的多个工具调用；写操作仍先返回 `confirm_required`，并修复了“批量调用中写操作导致后续调用被丢弃”的问题
- **写操作中断恢复（2026-10-27）**：`tools` 节点检测到写操作时只记录待确认信息并路由到 `confirm` 节点，由 `interrupt()` 暂停图；用户确认/取消后通过 `Command(resume=...)` 从断点继续——确认走 `write` 节点执行（带幂等键），取消走 `cancelled` 节点（回填一条 tool 消息后仍由模型生成回复）
- **checkpoint 存储**：`AsyncSqliteSaver`（`AGENT_CHECKPOINT_BACKEND=sqlite`，`AGENT_CHECKPOINT_DB_PATH=data/sessions/checkpoints.db`），`thread_id=session_id`；测试用 `memory`；按事件循环缓存 saver 实例
- **会话真源**：`SessionState` 仍负责消息、轨迹、人工模式、买家绑定；LangGraph checkpoint 只保存图内状态（messages/step/pending/decision），每轮新消息以 `session.snapshot()` 覆盖图 state
- **意图路由 L2（2026-10-27）**：`route_message` 仍是规则层（L1）；`route_message_l2` 仅在规则不确定时调用 LLM 结构化分类（`response_format=json_object`，`temperature=0`）。触发条件：`action=clarify` 或通用 `knowledge`（政策题、已识别商品的知识题不触发）
- **L2 合并策略**：置信度 ≥ `ROUTER_LLM_MIN_CONFIDENCE`（默认 0.7）才覆盖 L1；超时、JSON 非法、未知路由一律保留 L1；槽位仍由正则提取，不采信模型编造的编号
- **L2 边界**：只做分类（route/sub_intent/confidence/reason），不生成回复、不执行工具；`chat` 路由 `action=agent`，内容仍由 Agent 生成
- **Redis 热状态（2026-10-28）**：`CACHE_BACKEND=memory|redis`；Redis 可用时会话、限流、幂等全部走 Redis，不可用时自动回退（会话回 SQLite、限流/幂等回进程内存）
- **会话共享存储**：Redis 下 `get_session` / `get_existing_session` 每次从 Redis 重新加载，`list_sessions` 全量刷新；本地 `_sessions` 只作对象缓存，避免多 worker 读到旧数据
- **写操作幂等键**：Redis 用 `idempotency:lock:<key>`（`SET NX EX 60`）+ `idempotency:result:<key>`（24h）；拿不到锁且暂无结果时返回“处理中”，避免并发重复执行
- **依赖策略**：核心依赖不含 torch；rerank 放 `[project.optional-dependencies].rerank`，Docker 镜像默认不装，符合“rerank 默认关闭”
- **业务库双后端（2026-10-28）**：`ORDERS_BACKEND=postgres|sqlite`；Postgres 用 `psycopg_pool` + 事务，SQLite 只作本地/测试回退；占位符与 `BEGIN IMMEDIATE` 在适配层转换
- **checkpoint 后端（2026-10-28）**：`AGENT_CHECKPOINT_BACKEND=sqlite|postgres|memory`；容器内用 `AsyncPostgresSaver`；Windows 本地因 ProactorEventLoop 不支持异步 psycopg，仍用 sqlite
- **数据初始化**：订单库在空表时从 `data/orders/*.json` seed；`scripts/generate_orders.py` 重新生成后会 reset 当前后端（Postgres `TRUNCATE` / SQLite 删文件）
- **会话分层（2026-10-28）**：`SESSION_STORE_BACKEND=postgres|sqlite` + `CACHE_BACKEND=redis`；写操作先落 PG 再更新 Redis，读优先 Redis、miss 回源 PG 并回填；PG 是唯一真源，Redis 只做热缓存
- **会话数据形态**：`chat_sessions(session_id TEXT PK, payload JSONB, updated_at DOUBLE PRECISION)`；消息与 trace 存在 payload 内，未拆规范表；可用 `payload->'messages'` / `payload->'traces'` 查询
- **保留策略**：Postgres 由 `scripts/prune_sessions.py` 按 `SESSION_RETENTION_DAYS` 清理；Redis 由 `SESSION_TTL_SECONDS` 自动过期
- **SSE 心跳**：`with_heartbeat` 用独立 pump 任务 + 队列，间隔发 `: ping` 注释帧；避免用 `wait_for` 直接取消异步生成器（会导致生成器关闭）
- **指标口径**：`core/metrics.py` 进程内计数（请求、2xx/4xx/5xx、错误、工具、转人工、LLM 失败）与延迟均值/最大值；`GET /api/admin/metrics` 需管理 Token；多 worker 各自计数，未聚合
- **告警**：`send_alert` 固定写 ERROR 日志；配置 `ALERT_WEBHOOK_URL` 时异步 POST，失败只告警不阻断主流程
- **LLM 熔断**：进程内连续失败计数，达到 `LLM_CIRCUIT_FAILURES` 后冷却 `LLM_CIRCUIT_COOLDOWN` 秒；冷却期内 `resolve_llm()` 使用 `LLM_FALLBACK_*`；不做请求内中途重试（已输出内容时不重放）
- **低分处理（2026-10-31 调整）**：`search_knowledge` 本身只返回 `abstained/score/hits`；低分转人工由 Agent 侧 `_finalize_result` 统一判定，保证 local/mcp 两个后端行为一致
- **商品过滤**：`search_knowledge` 在 `product_id` 缺失时，由 `detect_product_id`（P 编号 + 型号正则 + 型号索引 + 系列回退 + 全名匹配）从用户输入自动补全；仅识别到具体型号/编号时才过滤，泛化品类词（如“耳机”“键盘”）不过滤
- **工具分层（2026-10-31）**：Agent 保留策略/确认/会话/信任边界；业务能力拆到内部 MCP server。`transfer_to_human` 永远在 Agent 内；`ToolSpec.server` 标记所属 server，`TOOL_BACKEND=mcp` 时才走 MCP，默认 local
- **MCP 传输**：streamable HTTP（`/mcp`），每个 server 独立进程/容器；`mcp-commerce` 9 工具、`mcp-catalog` 2 工具、`mcp-knowledge` 1 工具
- **工具令牌（2026-10-31）**：`core/tool_auth.py` 用 HMAC 签发 `tool_context`（sub=buyer_id、sid、scopes）与 `write_approval`（tool、args_digest、jti、exp）；`buyer_id` 不进模型可见参数，由 Agent 注入
- **写入安全边界**：确认流程留在 Agent（LangGraph `interrupt()`）；确认后 Agent 才签发审批令牌，MCP server 校验工具名、参数摘要和有效期；幂等（jti + 参数摘要）在 server 侧执行，Agent 侧保留本地回退
- **已验证模型**：DeepSeek `deepseek-chat`，OpenAI 兼容流式 tool calling；千问 embedding API 0.36s/次（单条）
- **商品 Provider 双轨（2026-11-04）**：`PRODUCT_PROVIDER=mock|saleor`；`mock` 读本地 `catalog.json`，`saleor` 走 GraphQL；工具签名与返回结构不变
- **Saleor 接入方式**：商品通过 `productVariant(sku:)` 定位 slug，再查 `product(slug:)` 取库存与渠道价；库存必须用不带 `channel` 的查询（带 channel 会返回空 stocks）
- **Saleor 数据边界**：价格/库存/名称来自 Saleor；规格、活动、发货时效等描述字段仍从本地目录补齐，后续可写进 Saleor metadata
- **Saleor 运行方式**：本地 Python venv + Postgres `saleor` 库 + Redis db3，`manage.py runserver 127.0.0.1:8001`；容器通过 `host.docker.internal:8001` 访问
- **Windows 兼容**：Saleor 依赖 Unix `resource` 模块，已在 `saleor/core/rlimit.py` 加 `ImportError` 兼容分支；这是本地运行补丁，不影响 Agent 代码
- **订单 Provider 双轨（2026-11-04）**：`ORDER_PROVIDER=mock|saleor`；`get_order`/`list_orders` 走 Saleor GraphQL，写操作仍走本地 mock
- **Saleor 订单映射**：`externalReference` = 订单号；metadata 存 `buyer_id`、`legacy_status`、`legacy_status_label`、物流单号等；工具返回优先读 metadata 的旧状态，保证与现有状态机一致
- **orderBulkCreate 兼容**：Saleor 3.24 的 `variantSku` 查询有 bug（内部把 SKU 存成 id 键），导入改用全局 `variantId`；行输入必须带 `undiscountedTotalPrice/createdAt/isShippingRequired/isGiftCard`，订单级必须带 `languageCode`，行必须带 `taxClassId`
- **物流映射（2026-11-04）**：Saleor `fulfillments` → 本地 `shipment` 结构；运单号取 `trackingNumber`，承运商/状态取订单 metadata；按运单号查询时先按买家邮箱拉订单再扫描 fulfillment
- **物流事件限制**：导入的订单只有一条合成事件（创建时间/状态），没有真实轨迹；接真实快递 API（快递100/快递鸟）后再补 `events`
- **售后映射（2026-11-04）**：Saleor 原生退款需要 `transactionId`，当前导入订单没有支付流水；因此售后数据写入订单 metadata（`aftersale_*`），Provider 读取 metadata 并映射为本地 `aftersale` 结构
- **售后边界**：metadata 是只读阶段的桥接方案；接真实退款/退货 API 后应替换为 Saleor 原生 return/refund
- **真实登录（2026-11-05）**：手机号 + 6 位验证码；OTP 存 Redis（memory 回退），TTL 300s、最多 5 次、发送冷却 60s；单次使用、常量时间比较；不暴露手机号是否存在
- **短信通道**：`SMS_PROVIDER=console` 只打印日志；`SMS_DEBUG=true` 时发送接口返回 `debug_code` 供本地演示，生产必须关闭并接真实短信网关
- **手机号映射**：由脱敏手机号（前 3 后 4）+ buyer_id 哈希生成稳定 11 位登录号；旧 `buyer_id + login_code` 保留作回退
- **操作审计（2026-11-05）**：在工具执行边界记录写操作与敏感读；表 `audit_log` 存 actor/session/tool/action/target/args_digest/ok/transport；只存 ID 与参数摘要，不存地址等 PII；写入 best-effort，失败只告警
- **灰度/回滚（2026-11-05）**：`SALEOR_ROLLOUT_PERCENT` 按 `buyer_id` 哈希稳定分桶；`SALEOR_ALLOWLIST` 非空时只放行名单；`ORDER_PROVIDER=mock` 或 percent=0 立即回滚。商品 Provider 没有买家上下文，仍按 `PRODUCT_PROVIDER` 全量切换
- **评测分层（2026-11-05）**：路由评测（L1/L2）、工具合同评测（脚本化参数）、LLM 端到端评测（待做）分开报告，不合并成一个“准确率”
- **场景集来源**：基于当前商品/订单数据人工编写；60 条为基线，扩充时需引入独立样本，避免与规则过拟合
- **压测口径**：问候路由不调 LLM，只测 SSE/鉴权/持久化；带工具/LLM 的压测另算，不混报
- **看板口径（2026-11-05）**：解决率 = `status=ok` 的 trace / 总 trace；转人工率 = `status=handoff` / 总 trace；首响 = 从收到消息到第一个 `delta` 的毫秒数；默认 7 天窗口，商家 Token 访问
- **看板刷新**：商家工作台每 15s 拉一次 `/api/admin/dashboard`；聚合在应用进程内读取会话与 trace

## 三、环境与版本

- 项目根目录：`D:\workspace\电商客服`
- 虚拟环境：`D:\workspace\电商客服\.venv`（Python 3.12）
- 启动：在项目根目录执行 `fastapi dev main.py`
- 测试：`.\.venv\Scripts\python.exe -m pytest tests -q`（不要用裸 `pytest`，根目录 `test_stream.py` 会在收集时连服务）
- 文档：`http://127.0.0.1:8000/docs`
- 前端：`http://127.0.0.1:8000/web/`（商家工作台 `#merchant`，`/` 会 307 跳转）
- 健康检查：`http://127.0.0.1:8000/health`（`llm` 字段显示 `configured` / `mock`）
- 系统默认 `python` 是 3.14.0a1 预览版，**不要使用**；用 `py -3.12`
- Node.js 未安装；当前前端为零构建静态页，不需要 Node
- Docker、Git 已安装；**Docker Desktop 未设开机自启**，每次开机需手动启动并等 Engine running
- 数据库：`docker compose up -d` 启动 `ecommerce-rag-postgres`（`pgvector/pgvector:pg17`，本机 5433，数据在 `ecommerce-rag_pgdata`）
- 数据库检查：`docker compose ps`、`docker compose exec postgres psql -U rag -d ecommerce_rag`
- Docker 镜像源：`docker.m.daocloud.io`（Docker Hub 直连超时）；Docker Desktop 代理已从失效的 `127.0.0.1:7897` 改为 No proxy
- `.env` 关键项：`LLM_*`、`LLM_FALLBACK_*`、`LLM_CIRCUIT_*`、`AGENT_ENGINE`、`AGENT_CHECKPOINT_BACKEND`、`AGENT_CHECKPOINT_DB_PATH`、`ROUTER_LLM_*`、`CACHE_BACKEND`、`REDIS_URL`、`SESSION_TTL_SECONDS`、`SESSION_STORE_BACKEND`、`SESSION_RETENTION_DAYS`、`LOG_FORMAT`、`ALERT_WEBHOOK_URL`、`SSE_HEARTBEAT_SECONDS`、`EMBEDDING_*`、`OCR_*`、`ADMIN_TOKEN`、`AUTH_SECRET`、`BUYER_TOKEN_TTL_HOURS`、`DATABASE_URL`、`RAG_*`、`RERANK_*`、`RATE_LIMIT_PER_MINUTE`、`MAX_MESSAGE_CHARS`、`FRONTEND_ORIGINS`、`TOOL_BACKEND`、`TOOL_SECRET`、`TOOL_CONTEXT_TTL_SECONDS`、`TOOL_APPROVAL_TTL_SECONDS`、`MCP_TIMEOUT`、`MCP_COMMERCE_URL`、`MCP_CATALOG_URL`、`MCP_KNOWLEDGE_URL`、`TOOL_TIMEOUT`、`TOOL_MAX_WORKERS`、`TOOL_MAX_CONCURRENCY_PER_TOOL`、`TOOL_RETRY_*`、`TOOL_CIRCUIT_*`、`TOOL_RESULT_*`、`TOOL_IDEMPOTENCY_*`、`PRODUCT_PROVIDER`、`ORDER_PROVIDER`、`SALEOR_ROLLOUT_PERCENT`、`SALEOR_ALLOWLIST`、`SALEOR_API_URL`、`SMS_PROVIDER`、`SMS_DEBUG`、`OTP_TTL_SECONDS`、`OTP_MAX_ATTEMPTS`、`OTP_SEND_COOLDOWN`、`SALEOR_CHANNEL`、`SALEOR_TOKEN`、`SALEOR_EMAIL`、`SALEOR_PASSWORD`、`SALEOR_TIMEOUT`
- 真实 `LLM_API_KEY`、`EMBEDDING_API_KEY` 已配置（值不记录）；`/health` 显示 `configured`
- 已安装 Python 依赖：`openai`、`psycopg[binary] 3.3.6`、`pgvector 0.5.1`、`pillow`、`reportlab`、`openpyxl`、`python-docx`、`pypdf`、`pdfplumber`、`pypdfium2`、`beautifulsoup4`
- 编排依赖：`langgraph 1.2.18`、`langchain-core 1.7.0`、`langgraph-checkpoint 4.3.1`、`langgraph-checkpoint-sqlite 3.1.2`、`aiosqlite 0.22.1`、`langgraph-prebuilt 1.1.1`（`langchain-openai` 未装，模型仍走原生 SDK）
- 工程工具：`uv 0.11.26`（`pyproject.toml` + `uv.lock`，138 包）、`ruff 0.17.3`、`mypy 1.20.2`、`redis 6.4.0`、`respx 0.23.1`、`pytest-asyncio 1.4.1`
- 数据层依赖：`psycopg-pool 3.3.3`、`langgraph-checkpoint-postgres 3.2.0`；`ORDERS_BACKEND`、`DATABASE_POOL_MAX_SIZE`、`DATABASE_POOL_TIMEOUT`
- 常用命令：`uv lock` 更新锁文件；`uv run ruff check .`；`uv run mypy`；`.\.venv\Scripts\python.exe -m pytest tests -q`
- 本地 MCP：`python scripts/run_mcp_servers.py` 起 9101/9102/9103；`python scripts/smoke_mcp.py` 做连通性检查；Agent 侧用 `TOOL_BACKEND=mcp` 才走 MCP
- Docker：`docker compose up -d` 起 api(8000) + mcp-commerce(9101) + mcp-catalog(9102) + mcp-knowledge(9103) + postgres(5433) + redis(6379)；api 健康检查 `/health` 含 `tools=mcp`；构建参数 `UV_DEFAULT_INDEX`、`PYTHON_IMAGE` 可切国内镜像
- 混合检索依赖：`jieba 0.42.1`、`sentence-transformers 6.2.0`、`torch 2.14.1`、`numpy 2.5.4`；模型在 `data/models/bge-reranker-base`
- 向量维度：`EMBEDDING_DIM=1024`，必须与 `knowledge_chunks.embedding vector(1024)` 一致

## 四、文件地图

- `AGENTS.md`：项目目标、范围、原则、约定（唯一目标来源）
- `main.py`：FastAPI 应用、SSE 接口、确认流程、运行轨迹采集、CORS、限流、商家端接口、静态页托管
- `core/config.py`：环境变量配置与启动校验
- `core/auth.py`：HMAC Token 签发/校验、Bearer 解析
- `core/security.py`：系统提示词、脱敏、工具结果隔离、确认/取消识别
- `core/logging.py`：日志初始化与脱敏异常日志
- `core/ratelimit.py`：单会话滑动窗口限流
- `agent/router.py`：意图路由 L1（规则层）+ L2（LLM 结构化分类兜底），5 个路由 + sub_intent、槽位、工具白名单、路由提示
- `agent/llm_agent.py`：编排入口，按 `AGENT_ENGINE` 分发到 graph / legacy
- `agent/graph_agent.py`：LangGraph `StateGraph`（agent/tools/confirm/write/cancelled/handoff/empty/max_steps/finish），工具并行执行，`interrupt()` 暂停写操作、`Command(resume=...)` 恢复；`stream_mode="custom"` 输出与旧 SSE 契约一致
- `agent/checkpoint.py`：LangGraph checkpointer（`sqlite` / `postgres` 持久、`memory` 测试），按事件循环缓存，支持删除线程
- `core/db.py`：PostgreSQL 连接池（`psycopg_pool`，大小/超时可配），业务库复用
- `agent/legacy_agent.py`：自研 tool-calling 循环（回退路径，行为与旧版一致）
- `agent/agent_utils.py`：两个引擎共享的 LLM 客户端、工具调用累加、参数解析、trace detail、转人工话术等 helper
- `agent/mock_agent.py`：规则版 Agent（降级路径），工具调用附带商品结果
- `agent/session.py`：会话状态、完整历史、消息 ID、人工接管、待确认操作、全量运行轨迹（`traces`）、启动加载与变更落库
- `agent/session_store.py`：会话持久化分层——Redis 热缓存 + Postgres/SQLite 持久层（`CompositeSessionStore`）；Redis miss 自动回源并回填
- `core/cache.py`：Redis 客户端（`CACHE_BACKEND=redis`）、连接失败自动回退内存、测试可注入假客户端
- `core/sse.py`：SSE 心跳包装器（队列 + 定时 `: ping`），避免代理空闲超时
- `core/metrics.py`：进程内请求/错误/工具/转人工/LLM 指标与延迟快照
- `core/alerts.py`：告警日志 + 可选 Webhook（异步、失败不阻断）
- `core/otp.py`：验证码签发/校验（Redis 优先、memory 回退），TTL/尝试次数/发送冷却
- `core/sms.py`：短信通道抽象；当前 `console` provider 只打印日志
- `core/audit.py`：工具审计（写操作/敏感读）落 `audit_log`；支持测试注入 sink
- `core/features.py`：按买家灰度（percent + allowlist），用于 Saleor 订单 Provider 切换
- `services/dashboard.py`：运营看板聚合（解决率/转人工率/首响/路由/转人工原因）
- `frontend/` 商家工作台：KPI 面板（5 个指标卡 + 路由/转人工原因条形图，15s 刷新）
- `pyproject.toml`、`uv.lock`：依赖声明与锁定；core 依赖不含 torch，rerank 为可选 extra
- `Dockerfile`、`.dockerignore`、`docker-compose.yml`：应用镜像 + api + 3 个 MCP server + postgres/redis + 健康检查
- `mcp_servers/common.py`：MCP server 公共层——工具令牌校验、写审批校验、server 侧幂等、`/health`
- `mcp_servers/commerce.py`、`catalog.py`、`knowledge.py`：三类内部 MCP server（9 / 2 / 1 个工具）
- `mcp_servers/idempotency.py`：server 侧写操作幂等（Redis 优先，进程内存回退）
- `mcp_servers/run.py`：`python -m mcp_servers.run <commerce|catalog|knowledge>`
- `tools/mcp_client.py`：streamable HTTP MCP 客户端、结果解析、`MCPToolError`
- `core/tool_auth.py`：工具上下文令牌 / 写审批令牌的签发与校验（HMAC、TTL、args 摘要）
- `.github/workflows/ci.yml`：ruff + mypy + pytest
- `frontend/index.html`、`app.js`、`styles.css`：零构建单页，买家端 / 商家工作台 + Agent 运行轨迹面板、历史轮次切换
- `tests/test_admin_api.py`：会话公开消息、商家接管/回复、买家轮询、人工模式闸门、trace 采集
- `tests/test_session_persistence.py`：序列化往返、全量 trace 保留、上下文窗口、SQLite 存取
- `tests/test_graph_agent.py`：只读工具并行耗时、批量调用中写操作不丢后续调用、legacy 引擎分发、中断恢复（确认/取消/无断点）
- `tests/test_router_l2.py`：L2 触发条件、低置信度/非法 JSON/超时回退、JSON 代码块解析、未知 sub_intent 映射
- `tests/test_saleor_products.py`：Saleor 字段映射、超时、500、商品不存在（`respx` 模拟 HTTP）
- `tests/test_saleor_orders.py`：订单映射、买家归属校验、列表、超时
- `tests/test_otp_auth.py`：手机号映射、验证码登录、单次使用、发送冷却、错误验证码、旧登录回退
- `tests/test_audit.py`：写操作确认/执行审计、敏感读审计、非敏感读不审计
- `tests/test_features.py`：灰度 percent/allowlist/mock 回滚、分桶稳定性
- `tests/test_dashboard.py`：解决率/转人工率/首响/路由/原因聚合、窗口过滤、空数据
- `tests/test_redis_backends.py`：Redis 限流共享、写操作幂等去重、会话读写与清空（假 Redis 客户端）
- `tests/test_sse.py`：心跳帧插入、关闭心跳、上游异常结束
- `tests/test_metrics.py`：指标计数/延迟快照、JSON 日志脱敏
- `tests/test_tool_auth.py`：工具上下文/审批令牌、篡改/过期、参数摘要绑定
- `tests/test_tool_runtime.py`：工具超时/重试/熔断、类型化错误、结果截断与 schema 校验、不确定写结果缓存
- `tests/test_mcp_servers.py`：catalog/commerce/knowledge 工具、令牌校验、写审批、server 侧幂等
- `tests/test_mcp_client.py`：local/mcp 路由、令牌注入、确认门禁、失败降级、知识拒答转人工
- `tests/test_llm_breaker.py`：连续失败熔断、备用供应商切换、无备用时保留主模型
- `tests/conftest.py`：测试时关闭会话持久化，避免污染本地会话库
- `tools/registry.py`：工具白名单、Schema、参数校验、写操作门禁与幂等
- `tools/products.py`：从 `catalog.json` 加载 100 个商品、`get_product`、`detect_product_id`（P 编号/型号/系列/全名识别）
- `tools/knowledge.py`：`search_knowledge` 工具包装、引用字段、低分转人工
- `rag/clean.py`：front matter 校验、正文清洗、事实泄漏检测、剔除运营性内容
- `rag/chunk.py`：结构感知 + 父子块切片
- `rag/embedding.py`：千问 embedding 客户端、分批、重试、维度校验
- `rag/search.py`：查询 embedding、pgvector 检索、父块去重、引用与低分拒答
- `rag/store.py`：JSONL 读取、父子校验、pgvector 幂等写入
- `services/orders.py`：Mock 订单 Provider；`ORDERS_BACKEND=postgres|sqlite` 可变状态库（JSON 首次 seed），按买家归属校验；Postgres 走连接池与事务
- `services/saleor_products.py`：Saleor GraphQL 商品 Provider（SKU → 商品 → 渠道价/库存），超时与 5xx 返回转人工提示
- `services/saleor_client.py`：Saleor GraphQL 客户端（登录/令牌缓存/401 重登/超时）
- `services/saleor_orders.py`：Saleor 订单 Provider（externalReference 查询、metadata 校验买家归属、状态映射）
- `tools/orders.py`：`get_order` / `get_logistics` / `get_aftersale` + 4 个写工具
- `tools/commerce.py`：`get_payment_methods` / `get_coupons`
- `tools/recommend.py`：`recommend_products` 工具包装
- `services/recommend.py`：按预算/品类/场景从真实商品库筛选推荐
- `tools/context.py`：工具执行上下文（`buyer_id` / `session_id`）
- `scripts/generate_orders.py`：确定性生成买家、订单、物流、售后数据
- `data/orders/`：`buyers.json`、`orders.json`、`logistics.json`、`aftersales.json`、`coupons.json`
- `scripts/generate_catalog.py`：生成 100 个商品的 `catalog.json`
- `scripts/generate_product_docs.py`：生成 300 篇商品文档、源清单、商品表、意图矩阵、数据卡
- `scripts/generate_policy_docs.py`：生成 35 篇政策文档、27 个 raw 原始文件、政策源清单与 README
- `scripts/parse_policy_raw.py`：两批解析 CSV/XLSX/DOCX/HTML/PDF/图片，输出去重报告与 `parsed/`
- `scripts/select_policy_parsed.py`：选择确认入库的解析文档，写入 `selected/` 并更新 registry
- `scripts/build_chunks.py`：批量清洗切片，支持商品 + 政策 + 已选解析文档多目录，输出 `data/processed/`
- `scripts/embed_and_ingest.py`：批量 embedding 并写入 pgvector
- `scripts/build_data_reports.py`：生成 `reports/data_quality_report.md`
- `scripts/eval_retrieval.py`：检索评测（Recall@k / MRR / 拒答）、`--query` 冒烟、`--json` 报告
- `scripts/import_catalog_to_saleor.py`：把本地 100 个商品导入 Saleor（渠道/仓库/类型/分类/变体/价格/库存，幂等）
- `scripts/import_orders_to_saleor.py`：把本地 60 笔订单通过 `orderBulkCreate` 导入 Saleor（metadata、履约/物流单号、税类）
- `scripts/sync_aftersales_to_saleor.py`：把 13 条售后写入对应订单的 `aftersale_*` metadata
- `scripts/prune_sessions.py`：按 `SESSION_RETENTION_DAYS` 清理 Postgres 会话（支持 `--dry-run`）
- `scripts/prune_sessions.py`：按 `SESSION_RETENTION_DAYS` 清理 Postgres 会话（支持 `--dry-run`）
- `scripts/generate_gold_set.py`：生成 80 条 gold（70 可回答 / 10 拒答），校验期望 doc_id
- `data/eval/retrieval_gold.jsonl`、`retrieval_gold.csv`、`README.md`：评测集与说明
- `reports/retrieval_eval.json`：最近一次检索评测报告
- `data/products/catalog.json`：100 个商品主数据（价格、库存、参数）
- `data/products/docs/`：300 篇商品 Markdown 文档（P2001–P2100 × 3）
- `data/policies/docs/`：35 篇政策 Markdown 文档（POL-RET/INV/LOG/PRI/TRD/BND/PLT）
- `data/policies/raw/`：27 个未入库原始文件（PNG/CSV/XLSX/PDF/JPG/DOCX/HTML）
- `data/policies/parsed/`：两批解析出的 Markdown、`parse_report.json`、`parse_report.csv`、`ocr_cache.json`
- `data/policies/selected/`：7 篇已选入库的解析文档、`manifest.json`、`README.md`
- `data/policies/registry.csv`：政策文件清单、有效期、入库状态、所需工具
- `data/policies/README.md`：政策库说明与待解析格式
- `data/processed/`：`parents.jsonl` 342 条、`chunks.jsonl` 1504 条、`report.json`
- `data/catalog/`：`source_registry.csv`、`products.csv`、`intent_matrix.csv`
- `docs/datasheet.md`、`docs/data_dictionary.md`、`docs/conventions.md`：数据卡、字段说明、命名规范
- `reports/data_quality_report.md`：数据质量验收报告
- `docker-compose.yml`：PostgreSQL 17 + pgvector，端口 5433
- `docker/initdb/001_extensions.sql`、`002_knowledge.sql`：扩展、表、HNSW 索引
- `tests/`：配置、安全、工具、LLM 循环、确认流程、切片、embedding、入库、检索、评测、政策文档校验
- `.env`：本机密钥（已忽略，不提交）
- `.env.example`：可提交的配置模板
- `.gitignore`：忽略密钥、虚拟环境、缓存、IDE
- `test_stream.py` / `test_tool.py`：旧的手工联调脚本
- `docs/PROJECT_STATE.md`：本文件，跨会话进度记忆
- 冒烟脚本在 `%TEMP%\opencode\smoke_llm.py`，临时文件，不入库
- `data/eval/`：`retrieval_gold.jsonl` 80 条、`retrieval_gold.csv`、`README.md`

## 五、已知问题与注意事项

- `cdn.jsdelivr.net` 在本机不可达，`/docs` 必须使用镜像或本地静态资源
- PowerShell 直接打印中文可能乱码，属终端编码问题；PyCharm 控制台一般正常
- `main.py` 不能用 PyCharm 绿色三角直接运行，需 `fastapi dev main.py`
- 流式响应必须用 `httpx.stream` + `iter_lines()`；`httpx.post` 会等全部内容收完
- 响应头含 `transfer-encoding: chunked`，没有 `content-length`，属正常现象
- 写操作确认改为“模型直接调工具、服务端只确认一次”；已用真实模型验证首轮 `confirm_required`、确认后仅执行一次
- 转人工话术已去重：模型本轮已输出“转接/人工客服”时，不再追加固定文案
- 模型可能先流式输出一段话再调工具，`tool_call` 事件会出现在部分 `delta` 之后，前端需兼容此顺序
- 多轮追问依赖历史中的事实，不会重新查工具；价格/库存可能过期，接真实数据后关键事实需强制重查
- `session_id` 没有鉴权，工具也没有买家身份，**订单归属校验缺失**；生产前必须绑定用户
- 暂无真实写业务工具（取消订单/退款/改地址）；冒烟用的 `cancel_order` 只在临时脚本内存中注册
- RAG 目前覆盖 100 个 mock 商品 + 35 篇店铺/平台政策；图片、表格、PDF、扫描件、DOCX、HTML 共 27 个原始文件尚未入库，需后续引入解析工具
- 政策旧版本（如 POL-RET-002、POL-PRI-002）仍在库中并标记 `deprecated=true`；默认在 SQL 层硬过滤，只有显式 `include_deprecated=True` 或历史年份题才会召回
- `deprecated` 过滤依赖 JSONB 里的布尔值，旧数据或手工入库文档若用字符串 `"true"` 也能被 `::boolean` 正确转换；若字段缺失按 `false` 处理
- 两批 raw 解析结果在 `data/policies/parsed/`；7 篇已选入 `data/policies/selected/` 并进入 RAG，12 篇非重复解析文档待确认，8 个重复已标记
- 解析出的 PDF/DOCX 与现有政策 Markdown 有部分重叠，未选入库，避免重复和版本冲突
- 政策文档是 Markdown 摘要版，PDF/扫描件中的细则可能更完整；解析原始文件后需要去重和版本对齐
- 政策文档允许出现运费、补差、补贴等金额，这些是政策规则，不是商品实时价格；回答时不要与 `get_product` 的价格混淆
- 检索已改为**稠密 + 纯 Python BM25 + RRF + 可选 CrossEncoder rerank**；依赖缺失时自动降级（无 jieba 二元组切分、无 sentence-transformers 退回 RRF），当前依赖已装但效果未评测
- BM25 为进程内内存索引，每个 worker 各自持有；通过 `knowledge_state.version` 即时感知入库，多进程无需重启；启动后台预热，首次请求不再承担加载开销
- 模型权重在 `data/models/`，不提交 Git；换机器需重新下载或拷贝，并把 `.env` 的 `RERANK_MODEL` 指向本地目录
- 商品实体识别靠 P 编号 + 型号正则 + 型号索引 + 系列回退；用户同时提多个商品时只取第一个匹配，接真实商品库需换检索/精确查询
- `RAG_MIN_SCORE=0.55` 基于旧 4 商品 14 条探针校准（相关 0.57–0.77、无关 0.35–0.46），扩到 100 商品 + 35 政策文档后需重新复核
- `search_knowledge` 每次调用新建 psycopg 连接；QPS 上来后换连接池
- gold 集已建立（80 条）；baseline Recall@5 92.1%、Hit@5 98.6%、MRR 0.725；拒答准确率仅 40%，失败集中在订单/支付/优惠/推荐等意图路由
- 原始稠密检索下同系列型号仍可能串款（如“VK75 无线模式”命中 VK75 Pro 的 FAQ）；Agent 层的商品过滤可缓解，但评测脚本走的是未过滤的 `rag.search`
- 同系列不同型号的文档措辞相似度较高；已用型号过滤降低串款风险，但跨商品泛化查询仍可能返回同系列结果
- FAQ 子块最短约 78 字，低于 100 字目标，属“一组 Q&A 不合并”的刻意例外
- `knowledge_chunks.embedding` 是 `vector(1024)`，换 embedding 模型/维度需重建列或整表
- `docker/initdb/*.sql` 只在数据卷首次初始化时执行；改表结构要手动执行 SQL 或重建 volume
- Docker Desktop 代理已关闭（原 `127.0.0.1:7897` 无服务），拉镜像走 `docker.m.daocloud.io`
- PowerShell 5.1 的 `Get-Content` 按 ANSI 读 UTF-8 的 `.env` 会误判，检查配置用 Python 或 `-Encoding UTF8`
- 数据库账号 `rag/rag` 仅本地开发用，上线前必须更换
- `pytest -q` 会误收集根目录 `test_stream.py` 并因连不上服务失败；只跑 `pytest tests -q`
- 冒烟调试时终端曾打印 `.env` 内容；若会话记录导出或分享，需轮换 API Key
- 会话与限流都在进程内存，多 worker/多实例不共享，生产前要换 Redis
- 幂等缓存也在进程内存，最长 24 小时；生产写接口仍需业务侧幂等键
- 商品别名匹配以型号索引为主，接真实商品库时换成检索或精确查询；mock 只有总库存，无按颜色/规格库存
- 已有 80 条 gold；订单/支付/优惠/推荐工具与路由已接入；业务订单数据仍为 mock
- 商品库和文档都是脚本生成的，改价格/库存/文案要改 `scripts/` 后重新生成，不要手改 JSON 或 `docs/` 下的 Markdown
- 9 个缺货商品：VK68 Ultra、VK98 Ultra、SL98、VM8 Ultra、VM10、TM9、EM7、AH5 Wireless、EH7
- `.env.example` 里的 Key 是占位符，复制后必须替换，不能直接使用
- `/api/admin/*` 已要求 `ADMIN_TOKEN`；买家登录使用 `AUTH_SECRET` 签名的 Token；两者都未配置时分别返回 503
- 买家登录码存在 `data/orders/buyers.json`，仅用于本地 mock 演示；真实系统必须接短信/账号登录
- Token 是无状态 HMAC，暂不支持主动吊销；修改 `AUTH_SECRET` 会让所有买家 Token 失效
- 商家端靠浏览器轮询（会话 4s、买家人工回复 3s），不是推送；多标签页可同时打开
- 会话与 trace 现为全量保留并落 SQLite；长时间运行后详情接口会变大，后续可改为分页/单独 trace 接口
- 运行轨迹只在每轮结束后写入会话，流式过程中商家端看不到进行中的步骤
- SQLite 为单文件单进程写入，多 worker/多实例会互相覆盖；生产需换 PostgreSQL/Redis 或加分布式锁
- 本次改动之前的内存会话与 trace 没有落库，无法恢复；只保证之后的对话
- trace 的 RAG 原文会随 `GET /api/admin/sessions/{id}` 一起返回，5 篇父块可能较大；后续可拆分独立分页接口
- 买家会话 ID 存在 `localStorage`，换浏览器/清缓存会开新会话；没有买家身份绑定
- 转人工后 `human_mode=true` 会一直持续，直到商家在后台点“转回机器人”
- 静态页无构建流程；改 `frontend/` 文件后刷新即可，注意浏览器缓存（可强制刷新）
- `启动客服.bat` 启动的 uvicorn 没加 `--reload`，改后端 Python 代码后必须重启服务，否则接口继续运行旧代码（表现为商家端拿不到 `traces`）；`/web` 已加 `Cache-Control: no-store` 和资源版本号，仍建议 Ctrl+F5

- **写操作确认已改为图原生中断恢复**：`interrupt()` 暂停、`Command(resume=...)` 继续；断点存 `data/sessions/checkpoints.db`，服务重启后仍可恢复（已用真实 HTTP 验证）
- 有 pending 时用户直接问新问题：服务端删除该线程断点并取消待确认操作，再按新消息正常处理
- `agent/session.py` 仍是消息、轨迹、人工模式的真源；checkpoint 只保存图内状态，不复用为会话存储
- checkpoint 每轮写入完整 messages，长期会话会让 `checkpoints.db` 持续增大；M4 迁 Postgres 时一并加清理策略
- `AsyncSqliteSaver` 按事件循环缓存连接；多 worker 各自持有连接写同一文件，存在 SQLite 写锁竞争，M4 迁 Postgres
- `graph` 引擎每次请求都会 `_build_graph(...).compile()`，有少量构图开销；稳定后可缓存编译结果或改为单例 + config 注入 session
- `legacy` 引擎保留但不再维护，仅用于回滚（`AGENT_ENGINE=legacy`）；graph 稳定后应删除
- 并行工具使用 `asyncio.to_thread` 的默认线程池，工具内部仍为同步实现；并发数未调优，压测前需评估
- LangGraph 事件通过 `stream_mode="custom"` 透传，买家 SSE 事件契约未变；trace 采集不受影响
- `langgraph 1.2.18` / `langchain-core 1.7.0` 为当前版本，尚未锁定；M4 引入 `uv.lock` 后固定
- 路由 L2 触发时会多一次 LLM 调用（约 0.3–1s）；只对 `clarify` 和通用 `knowledge` 触发，暂未加缓存
- L2 只输出单意图，`secondary_routes` 多意图仍未使用
- 路由准确率尚无评测集，L1 与 L1+L2 的对比待 M7 补
- L2 返回未知 `sub_intent` 时，`transaction` 会退回 `order_query`，可能调用 `get_order`；比 RAG 猜测安全，但不够精确
- L2 结果依赖模型稳定性；`response_format=json_object` 不被支持时会走失败回退，保留 L1

- Redis 不可用时会**静默回退**到进程内存/SQLite；此时多实例的幂等与限流不再全局有效，生产需监控日志并告警
- Redis 会话是“整段 JSON 覆盖写”，同一会话的并发请求仍可能后写覆盖先写（last-write-wins）；需要严格串行时应加会话级锁
- `sessions:index` 是 zset；会话 key 过期后索引里可能残留 id，读取时 `mget` 会跳过，暂未做主动清理
- Redis 客户端为同步实现（socket 超时 1s），在异步 handler 中会短暂阻塞；压测前评估是否换 `redis.asyncio`
- `docker-compose.yml` 把 `./data/sessions`、`./data/orders` 挂进容器；`CACHE_BACKEND=redis` 时 `sessions.db` 只作回退
- CI 工作流尚未推远端验证；`uv.lock` 在本机用清华镜像生成，CI 默认走 PyPI
- Docker 构建默认 `pypi.org` 与 `python:3.12-slim`；国内构建需传 `UV_DEFAULT_INDEX`、`PYTHON_IMAGE` 参数
- 业务订单、售后、会话、checkpoint 在容器内均已走 Postgres；SQLite 只作本地/测试回退
- 镜像不含 `torch`/`sentence-transformers`；rerank 在容器内不可用（默认关闭，符合预期）

- **Windows 上不能用异步 psycopg**：默认 `ProactorEventLoop` 会直接报错，`AsyncPostgresSaver` 与 async 连接池都受影响；本地 checkpoint 用 `sqlite`，容器（Linux）用 `postgres`
- `ORDERS_BACKEND=postgres` 时连接失败会直接抛错，不会静默回退 SQLite；测试与 CI 用 `sqlite`
- `scripts/generate_orders.py` 会 reset **当前后端**：`postgres` 时 `TRUNCATE` 业务表，`sqlite` 时删文件；重新生成后需等首次访问再 seed
- seed 逻辑在 orders 表为空时会先清空 buyers/shipments/aftersales/coupons 再插入；仅适用于 mock 数据
- Postgres checkpoint 连接池按事件循环缓存，进程退出前不主动关闭；压测时需关注连接数
- 会话/消息/trace 以整段 JSONB 存在 `chat_sessions.payload`，未拆 `messages`/`traces` 规范表；会话量大时商家列表与查询会变慢，M7 若做质检看板再拆表
- 会话写路径是“先写 PG 再写 Redis”；Redis 写失败不会影响持久性，但读会回源 PG（延迟略高）
- `uv.lock` 现为 139 包（新增 `psycopg-pool`、`langgraph-checkpoint-postgres`）

- 指标与熔断状态都在**进程内**：多 worker 各自计数、各自熔断，未做跨进程聚合；需要全局口径时再接 Prometheus/Redis
- 熔断只在请求开始时选择供应商，不做请求内中途重试；已流式输出部分内容后失败会直接报错，避免重复输出
- SSE 心跳是注释帧（`: ping`），前端忽略非 `data:` 行；心跳间隔过小会增加带宽
- `LOG_FORMAT=json` 只作用于 `ecommerce_agent` 日志；uvicorn access log 仍是文本，完整 JSON 采集需改 uvicorn log config
- 告警 Webhook 为“尽力而为”异步发送，没有重试队列；Webhook 失败只写 WARNING 日志

- **MCP 客户端每次调用新建 streamable HTTP 会话**（initialize → call → terminate），多 2–3 次往返；本地/容器内延迟可接受，高 QPS 前应改成连接复用或常驻 session
- `context_token` / `approval_token` 作为 MCP 工具参数传入（不在模型可见 schema 中，由 Agent 注入）；FastMCP 默认不打印参数，但若开 DEBUG 仍需注意日志脱敏
- 写操作审批令牌默认 5 分钟有效；`interrupt()` 待确认跨重启恢复时，若用户超过 TTL 再确认，server 会拒绝，需要重新走确认
- `transfer_to_human`、确认门禁、trace、工具结果隔离仍留在 Agent；MCP server 只承载业务能力，不要往里塞会话状态
- MCP server 侧幂等依赖同一 `jti + args_digest`；Agent 重试必须复用 pending 里的幂等键，不能重新生成
- 外部 MCP（平台客服、物流、支付、ERP）尚未接入；当前只有内部 server，外部能力仍需 Provider 抽象 + 薄 adapter
- MCP server 只应部署在内网/容器网络，不直接暴露公网；令牌只做调用方身份与审批绑定，不替代 mTLS/网关鉴权
- 容器内 `uv.lock` 已含 `mcp 1.30.0`，并把 `starlette` 升到 1.10.0；本地测试全绿，后续升级需回归 FastAPI
- Compose 构建仍需 `PYTHON_IMAGE`/`UV_DEFAULT_INDEX` 指向国内镜像，否则 Docker Hub 拉取超时

- Saleor 是本地开发服务器（`manage.py runserver 127.0.0.1:8001`），不是常驻服务；它停止后 `get_product` 会返回“商品服务响应超时/不可用”，Agent 会转人工，不会编造
- Saleor 已导入商品与订单；买家、物流、售后仍是本地 mock；取消/改地址/拦截/工单等写操作仍走 mock，M6 尚未完成
- 订单列表按 `buy-xxxx@example.com` 过滤；接入真实系统时需要维护 buyer_id ↔ 账号映射
- 订单状态优先读 metadata 的 `legacy_status`；直接改 Saleor 后台状态不会同步回 Agent
- `orderBulkCreate` 的 `variantSku` 在 Saleor 3.24 有 bug，导入必须用 `variantId`；行还必须带 `undiscountedTotalPrice/createdAt/isShippingRequired/isGiftCard/taxClassId`
- `get_logistics` 与 `get_aftersale` 均已接 Saleor（售后读订单 metadata）；Saleor 原生 return/refund 未接
- 售后状态不会随 Saleor 后台变化；metadata 只在 `sync_aftersales_to_saleor.py` 运行时写入
- 售后单号、类型、金额、时间线来自本地 `aftersales.json`，经 metadata 透传，不是 Saleor 原生售后对象
- Saleor 物流只有 fulfillment 记录，没有真实轨迹节点；`events` 是合成的一条，承运商来自 metadata
- Windows 上 Saleor 需要 `saleor/core/rlimit.py` 的 `resource` 兼容补丁；重新拉取 Saleor 源码会丢失该补丁
- Saleor 的库存查询有坑：`productVariant(..., channel:)` 和 `product(..., channel:)` 可能返回空 `stocks`；Provider 用不带 channel 的 `product(slug:)` 取库存，再按 `channel.slug` 过滤渠道价
- 容器内通过 `host.docker.internal:8001` 访问宿主机 Saleor；Docker Desktop 不可用时需改成局域网 IP
- `PRODUCT_PROVIDER=saleor` 需要 `.env` 中的 Saleor 凭据；测试通过 conftest 强制 `mock`，不会依赖外部服务
- 目前只有价格/库存/名称/分类来自 Saleor；规格、活动、发货时效等描述字段仍从本地目录补齐，后续可写入 Saleor metadata

- 短信通道目前只有 `console`，没有接真实短信网关；`SMS_DEBUG=true` 会在接口返回 `debug_code`，生产必须关闭
- 登录手机号由脱敏手机号 + buyer_id 哈希派生，不是真实手机号；接真实账号体系时需替换映射
- 旧 `buyer_id + login_code` 登录仍保留，生产应删除或仅限演示环境
- OTP 在 Redis 不可用时回退进程内存，多 worker/多实例下验证码不共享
- 容器访问宿主机 Saleor 时，Saleor 的 `ALLOWED_HOSTS` 必须包含 `host.docker.internal`，否则返回 400 `DisallowedHost`
- 本机 Docker 镜像源偶发 401/EOF，正常 `docker compose build` 可能失败；本地可用 `Dockerfile.local`（`FROM ecommerce-agent:local` + `COPY .`）做增量构建，CI/正常环境仍用 `Dockerfile`
- `Dockerfile.local` 依赖本地已有 `ecommerce-agent:local`，不能用于干净环境

- 审计在 Agent 工具边界记录；直接调用 MCP server（绕过 Agent）不会产生审计，后续可在 server 侧补
- 审计写入是 best-effort：Postgres 不可用时只写 WARNING 日志，不阻塞工具
- 灰度只作用于订单/物流/售后；商品无买家上下文，仍按 `PRODUCT_PROVIDER` 全量切换
- `audit_log` 目前没有清理脚本，长期运行需要按保留期归档/删除

- M7 场景集 60 条是按当前规则与数据人工编写的，路由 L1 100% 有过拟合风险；扩充时必须加入独立样本
- 工具评测用脚本化参数（不走 LLM），证明工具合同与数据通路，不等同于 Agent 端到端质量
- 压测只覆盖问候路由（不调 LLM、不调工具），66.4 RPS / p95 103ms 不能代表带模型链路的性能
- 评测脚本未接入 CI；报告在 `reports/` 本地生成
- 看板通过 `all_sessions()` 读取全部会话，会话量大时会变慢；后续应改成 Postgres JSONB 聚合或预计算
- 首响对问候/规则回复接近 0ms，只有 LLM 路径的数据才具参考意义
- 满意度尚未实现（前端没有评价入口）
- 解决率只按 trace `status=ok` 统计，不等同于“用户问题真正解决”
- 看板聚合在各 API 实例内完成；多 worker 下每个实例都会算一遍，但数据源一致

## 六、会话摘要

### 2026-10-19：项目初始化与 M0 流式骨架

- 确认项目目标并写入 `AGENTS.md`
- 完成 Python 3.12 虚拟环境与 FastAPI 安装
- 跑通 `/docs`、`/health`
- 排查 `/docs` 空白：CDN 不可达，切换至 `fastly.jsdelivr.net`
- 实现 `/api/chat/stream` SSE 假流式接口并用 `test_stream.py` 验证
- 建立本记忆文件与 `/save-memory` 命令

### 2026-10-19：mock 商品工具与工具调用链路

- 新增 `tools/products.py`：4 个 mock 商品与 `get_product`
- 新增 `agent/mock_agent.py`：规则版商品识别、意图判断、回复生成与工具调用轨迹
- 改造 `main.py`：流式输出前先发 `tool_call` 事件，新增商品列表/详情接口
- 新增 `test_tool.py`，验证工具直连与流式工具调用（59 个事件）
- 明确下一步：接真实模型，用 LLM tool calling 替换规则版 Agent

### 2026-10-19：真实模型安全接入

- 新增 `.env` / `.env.example` / `.gitignore`，并在项目目录单独 `git init`
- 新增 `core/`：配置、安全、日志、限流
- 新增 `tools/registry.py`：工具白名单、参数校验、写操作确认与幂等
- 新增 `agent/llm_agent.py`：OpenAI 兼容流式 tool calling、超时、最大步数、转人工
- 新增 `agent/session.py`：内存多轮会话与待确认操作
- 改造 `main.py`：真实模型 + mock 降级、确认流程、CORS、错误事件、限流
- 新增 `tests/` 17 个用例并全部通过
- 待用户填 Key 后执行真实模型冒烟

### 2026-10-21：真实模型冒烟与场景收敛

- 用临时脚本启动 uvicorn 跑 9 轮真实请求，未改源码；`git status` 干净
- 通过：商品查价/库存、多轮追问、负面情绪转人工、注入拒绝、写操作确认后仅执行一次
- 发现：写操作双重确认、转人工话术重复、多轮事实依赖历史、无订单归属校验
- 确认写操作由买家确认，不做平台运营审批；高风险或超政策场景走转人工
- 场景收敛：以售前 + 订单/物流查询 + 售后政策/工单 + 转人工为主；写操作优先做无自助入口的场景
- RAG 数据策略与规模：公开政策 + 自建合成语料，80–120 篇 / 600–1200 块 / 150–300 评测
- 下一步：先修确认流程与转人工去重，再做知识库 RAG

### 2026-10-23：商品文档、切片、pgvector 入库

- 规模决策改为 **150 篇 MVP + 80 条 gold，后续扩到 300 篇**
- 生成 4 个 mock 商品 × 3 篇文档（概述/参数/FAQ），只写描述性知识，不含价格/库存
- 新增 `rag/clean.py` 与 `rag/chunk.py`：结构感知 + 父子块；父 600–1200、子 150–400，FAQ/表格独立
- 清洗规则：front matter 校验、去免责声明、剔除“关于价格与库存”、价格/库存泄漏检测
- 产出 12 父块 / 47 子块；子块长度 72–312，FAQ 短块为刻意例外
- 接入千问 `text-embedding-v3`，1024 维；单条约 0.36s，47 条约 1.5–2s
- Docker 拉起 PostgreSQL 17 + pgvector 0.8.7（5433），建 `knowledge_parents` / `knowledge_chunks` + HNSW
- `scripts/embed_and_ingest.py` 幂等入库：12 父块 / 47 子块；重复执行不重复
- 检索冒烟通过：“耳机续航多久” top-5 全命中 P1001
- 排查 Docker 失效代理（127.0.0.1:7897），改为 No proxy，镜像走 `docker.m.daocloud.io`
- 测试从 17 增至 39，全部通过
- 下一步：`rag/search.py` + 20–30 条评测 + Agent `search_knowledge` 工具

### 2026-10-23：检索与评测脚本

- 新增 `rag/search.py`：子块向量召回 → 父块去重保留最高分子块 → 返回父块全文与 `doc_id/section/source` 引用
- 默认 `top_k=5`、`min_score=0.35`、候选 `max(top_k*4,20)`；低分/空结果标记拒答，但仍返回 hits 供日志与评测
- 支持 `product_id` 过滤、外部连接注入（便于测试与后续连接池）
- 新增 `scripts/eval_retrieval.py`：gold JSONL、Recall@k / Hit@k / MRR / 误拒率 / 拒答准确率、失败明细、`--query` 冒烟、`--json` 报告
- gold 集暂缓，脚本默认找 `data/eval/retrieval_gold.jsonl`，缺失时打印格式示例并退出 2
- 实测 `--query "无线蓝牙耳机续航多久"`：top1 0.695（P1001-02），top-5 全部 P1001
- 新增检索/评测测试 12 个，总数增至 51，全部通过
- 下一步：建 20–30 条 gold，跑评测校准阈值与切片

### 2026-10-23：RAG 接入 Agent 与交互修复

- 用户决定跳过 gold 评测，先接通 Agent；评测脚本保留备用
- 新增 `tools/knowledge.py` 与 `search_knowledge` 工具：父块正文 + `doc_id/section/source` 引用；低分/空结果直接返回 `status=handoff`
- 系统提示词拆分实时数据（`get_product`）与描述性知识（`search_knowledge`），要求标注来源、拒答不编造
- 工具执行统一改为 `asyncio.to_thread`，避免 embedding/DB 阻塞事件循环
- 写操作双重确认修复：模型直接调写工具，服务端只弹一次确认；真实模型验证仅执行一次
- 转人工话术去重：本轮已流式输出“转接/人工客服”时不再追加固定文案
- 用 14 条探针校准阈值，`RAG_MIN_SCORE` 从 0.35 调到 0.55，并加入 `Settings`
- 真实模型冒烟：知识库问答带引用、无关问题低分转人工、写操作单次确认、显式转人工无重复
- 测试增至 58 个，全部通过
- 下一步：商品实体自动识别 + 订单/物流只读工具

### 2026-10-24：前端双端页面与人工接管

- 新增 `frontend/` 零构建单页：买家端聊天 + 商家工作台，同页切换，`#merchant` 深链；FastAPI `/web` 托管，`/` 307 跳转
- 买家端：SSE 流式、工具调用提示、确认/取消按钮、转人工横幅、人工回复轮询、会话持久化、新会话
- 商家端：会话列表（人工/机器人、未读数）、会话详情、接管/转回、人工回复；买家端 3s 轮询可见
- 会话增加自增消息 `id`、`human_mode`、`source=human`；`snapshot()` 与公开消息分离
- 新增 `/api/admin/sessions*`、`/api/chat/messages`；`handoff` 自动置 `human_mode`
- 商家端沿用买家端会话内存存储，暂无鉴权；上线前需加登录与租户隔离
- 真实 HTTP 冒烟通过：商品问答 → 工具调用 → 接管 → 人工回复 → 买家轮询；新增 8 个测试，总数 66
- 下一步：管理接口鉴权 + 商品实体识别 + 订单/物流工具

### 2026-10-24：商品实体自动识别

- 新增 `tools/products.py` 的 `detect_product_id`：编号正则（Pxxxx）+ 别名表（耳机/充电宝/手表/键盘）
- `search_knowledge` 在 `product_id` 缺失时自动从 query 识别；Agent 层再依据最近一条用户消息补全，避免 LLM 漏传导致跨商品结果
- 显式传入的 `product_id` 优先于自动识别；识别不到时不强制过滤（跨商品政策类问题）
- 冒烟验证：耳机/充电宝查询只返回对应商品文档；退货政策等跨商品查询不过滤、低分转人工
- 测试增至 73，全部通过
- 下一步：管理接口鉴权 + 订单/物流只读工具

### 2026-10-24：替换为 100 商品 / 300 文档知识库

- 虚构品牌「烬狐 EMBERFOX」，100 个商品：键盘 40、鼠标 35、耳机 25；全部为具体型号（VK75 Pro、VM9 Ultra、AH9 Pro 等）
- 9 个缺货：VK68 Ultra、VK98 Ultra、SL98、VM8 Ultra、VM10、TM9、EM7、AH5 Wireless、EH7；另有 8 个低库存（≤10 件）
- 新增 `scripts/generate_catalog.py` 生成 `data/products/catalog.json`；`tools/products.py` 改为启动时加载，`detect_product_id` 支持 P 编号、型号正则、系列回退和全名匹配
- 新增 `scripts/generate_product_docs.py`：每个商品 3 篇文档，共 300 篇；同时生成 `source_registry.csv`、`products.csv`、`intent_matrix.csv`、`docs/datasheet.md`
- 切片：300 父块 / 1392 子块；父块 477–851 字，子块 78–387 字；0 校验错误、0 警告、0 精确重复
- pgvector 使用 `--prune` 替换旧库：`knowledge_parents` 300 行、`knowledge_chunks` 1392 行
- 检索冒烟：VK75 Pro 触发键程 top1 P2001-01（0.723），产品过滤后命中 P2001-02/03；VM9 Pro 重量、AH9 Pro 续航均命中对应商品；无关天气问题低分拒答
- 新增 `docs/data_dictionary.md`、`docs/conventions.md`、`reports/data_quality_report.md`
- 测试更新为新商品编号，75 个用例全部通过
- 下一步：80 条 gold 集 + 店铺政策/售后/物流文档 + 管理接口鉴权

### 2026-10-24：补店铺政策与平台规则知识库

- 新增 35 篇 Markdown 政策文档，覆盖退换货 8、发票 5、物流 6、价格保护 5、以旧换新 5、安全边界 3、平台规则 3
- 包含 2024/2026 新旧版本冲突样本：POL-RET-001/002、POL-PRI-001/002；旧版标记 `deprecated=true` 与 `superseded_by`
- 扩展 `rag/clean.py` 的 `DOC_TYPES`：`store_policy`、`platform_rule`、`policy_faq`、`refusal_boundary`、`policy_notice`
- 政策作用域：店铺政策 `product_id=STORE`、平台规则 `product_id=PLATFORM`；检索带商品过滤时同时返回 STORE/PLATFORM 文档
- 政策元数据新增 `valid_until`、`review_date`、`policy_domain`、`region`、`scope`、`supersedes/superseded_by`，并随 chunk 进入 pgvector
- 新增 27 个未入库原始文件：5 张 PNG 流程图、5 组 CSV/XLSX 表格、5 个文本 PDF、2 组扫描件 JPG + 无文本层 PDF、2 个 DOCX、1 个 HTML；`data/policies/registry.csv` 标注所需解析工具
- `scripts/build_chunks.py` 改为多目录输入，默认同时读取商品和政策文档；切片 335 父块 / 1491 子块，0 错误、0 警告、0 精确重复
- pgvector `--prune` 后为 `knowledge_parents` 335 行、`knowledge_chunks` 1491 行
- 政策检索冒烟：七天无理由、退货运费、退款时效、发票、发货、价保、以旧换新、隐私边界、平台介入均命中对应政策；带商品过滤的“VK75 Pro 可以七天无理由退货吗”也能返回 STORE 政策
- 新增 `tests/test_policy_docs.py`，测试总数 78，全部通过
- 下一步：用 OCR/PDF/表格工具解析 raw 文件并补入库 + 80 条 gold 集 + 管理接口鉴权

### 2026-10-25：第一批 raw 文件解析

- 新增 `scripts/parse_policy_raw.py`，第一批解析 CSV/XLSX/DOCX/HTML/文本 PDF
- 安装 `pdfplumber`、`beautifulsoup4`；复用已装的 `openpyxl`、`python-docx`、`lxml`
- 共解析 18 个文件：5 CSV、5 XLSX、2 DOCX、1 HTML、5 文本 PDF；0 失败
- 去重：6 个重复（5 个 XLSX 与 CSV 内容一致，1 个 HTML 与物流时效 CSV 内容一致）；标记 `duplicate_of`
- 9 个文件留待第二批 OCR：5 PNG、2 JPG、2 扫描 PDF（无文本层）
- 解析结果在 `data/policies/parsed/`，含 `parse_report.json`、`parse_report.csv`；`registry.csv` 已更新状态、解析器、重复来源
- 解析结果**尚未加入 RAG**；下一步先人工比对 PDF/DOCX 与现有政策 Markdown，合并或替换后再切片
- 测试 78 个仍全部通过

### 2026-10-25：第二批 OCR 解析

- 为 `scripts/parse_policy_raw.py` 增加 `--ocr`，第二批处理 PNG/JPG/扫描 PDF
- OCR 使用 DashScope `qwen-vl-ocr`（OpenAI 兼容接口），默认复用 `EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL`；新增 `OCR_API_KEY`、`OCR_BASE_URL`、`OCR_MODEL`、`OCR_TIMEOUT` 配置
- 扫描 PDF 用 `pypdfium2` 渲染为图片后再 OCR；结果写入 `data/policies/parsed/`
- 9 个 OCR 文件全部成功：5 PNG、2 扫描 PDF、2 JPG；2 个 JPG 与对应扫描 PDF 内容重复，已标记 `duplicate_of`
- 两批合计 27/27 个文件解析完成，8 个重复（5 XLSX + 1 HTML + 2 JPG），0 待 OCR、0 失败
- OCR 结果带 `source_file`、`source_format`、`parser`、`ocr_model`、`page_count`、`parsed_at`
- 增加 OCR 缓存 `data/policies/parsed/ocr_cache.json`，重复运行不重复调用 API
- 全部 27 篇解析文档通过 front matter 和切片校验，0 错误、0 警告
- 解析结果仍未入库；下一步确认重复/合并策略后，把选中的解析文档加入 `build_chunks` 输入再 `--prune` 入库
- 测试增至 80 个，全部通过

### 2026-10-25：入库 7 篇已选解析文档

- 新增 `scripts/select_policy_parsed.py`，从 `parsed/` 选择 5 个 CSV 表格 + 2 个扫描件，复制到 `data/policies/selected/` 并生成 `manifest.json`、README
- 选择原则：CSV 作为表格规范版本，跳过 XLSX；扫描 PDF 作为扫描件规范版本，跳过 JPG；HTML 与 CSV 重复时跳过
- 已选 7 篇：退货运费表、配送时效表、价保期限表、以旧换新估价表、发票类型表、以旧换新回收单、平台规则变更公告
- `scripts/build_chunks.py` 默认输入加入 `data/policies/selected/`，并跳过目录内 README
- 切片：342 父块 / 1504 子块；父块 232–851 字，子块 59–490 字；0 错误、0 警告
- pgvector `--prune` 后为 `knowledge_parents` 342 行、`knowledge_chunks` 1504 行
- 检索冒烟：退货运费、配送时效、发票类型、以旧换新估价、回收单号、平台规则变更均命中对应解析文档；价保期限表进入 top-k
- `registry.csv` 中 7 篇状态改为“已入库”，其余 12 篇非重复解析文档仍为“已解析（待入库）”，8 篇重复仍为“未入库”
- 测试增至 81 个，全部通过
- 下一步：处理剩余 12 篇非重复解析文档（优先合并 PDF/DOCX）+ 80 条 gold 集 + 管理接口鉴权

### 2026-10-25：建立 80 条检索 gold 集

- 新增 `scripts/generate_gold_set.py`，确定性生成 80 条 gold（70 可回答 / 10 拒答），并校验期望 doc_id 是否存在
- 覆盖：商品参数 19、商品概述 8、商品 FAQ 8、型号对比 6、退货 5、发票 3、物流 3、价保 2、以旧换新 2、旧版政策 2、安全边界 3、平台规则 3、表格 5、扫描件 1、拒答 10
- 产出 `data/eval/retrieval_gold.jsonl`、`retrieval_gold.csv`、`README.md`；新增 `tests/test_gold_set.py`
- baseline（top_k=5、min_score=0.55）：Recall@5 92.1%、Hit@5 98.6%、MRR 0.725、可回答问题误拒率 0%、拒答准确率 40%
- 唯一可回答失败：`VK75 无线模式怎么切换` 命中 VK75 Pro 的 FAQ；Agent 层商品过滤可缓解，裸检索仍会串同系列
- 拒答失败集中在订单/物流/支付/优惠/推荐：RAG 召回了政策文档而不是转人工，说明需要意图路由与工具边界，不是排序问题
- 依据该基线，判断 rerank 当前必要性偏低；优先做 gold 回归、deprecated 过滤、意图路由和混合检索
- 测试增至 83 个，全部通过

### 2026-10-25：商家端 Agent 运行轨迹

- 新增每轮 trace：接收消息 → LLM 轮次 → 工具调用（参数/结果）→ RAG 召回（文档/分数/原文）→ 转人工/确认/降级/异常 → 最终回复，附耗时与状态
- `agent/llm_agent.py` 新增内部 `llm_step` 事件和 `tool_call.detail`；`agent_stream` 消费后不转发买家，只写入 `SessionState.traces`
- `GET /api/admin/sessions/{id}` 新增 `traces`；商家端新增“运行轨迹”面板，每条机器人回复下方可直达对应轮次
- mock 降级路径也补齐商品工具结果，保证无模型时轨迹仍可读
- 新增 4 个测试（RAG detail、agent_stream 内部事件不外泄、admin traces、trace 容量/过滤），总数 87，全部通过
- 此时 trace 仍在内存，每轮结束后才可见；详情接口会携带 RAG 原文

### 2026-10-25：会话与 trace 持久化

- 新增 `agent/session_store.py`：SQLite `chat_sessions` 表，每个会话保存完整 JSON（消息、trace、待确认操作、人工模式、自增 ID）
- 启动时全量加载持久化会话；`add_message`/`add_trace`/人工接管/待确认变更加载后立即落库，重启不丢
- 取消消息 20 条与 trace 30 轮截断：消息全量保留，LLM 上下文仍只取最近 20 条；trace 默认全部保留
- 商家端会话列表显示轨迹轮数，轨迹面板增加历史轮次切换；每条机器人回复下方仍可直接打开对应轮次
- 测试时通过 `tests/conftest.py` 关闭持久化，避免污染本地会话库；新增 3 个测试（序列化往返、全量保留/上下文窗口、SQLite 存取），总数 90
- 本次改动之前的会话与 trace 未落库，无法恢复；之后的新对话全部保留

### 2026-10-25：RAG 元数据过滤（deprecated + 作用域）

- `rag/search.py` 新增 `include_deprecated`（默认 `False`）：SQL 条件 `COALESCE((c.metadata->>'deprecated')::boolean, (p.metadata->>'deprecated')::boolean, false) = false`，父子块 metadata 都兼容
- 商品过滤保持 `WHERE (c.product_id = %s OR c.product_id IN ('STORE', 'PLATFORM'))`；与 deprecated 条件用 `AND` 组合，无商品时不加作用域条件
- `SearchResult`、`search_knowledge` 工具、`SearchKnowledgeArgs` schema、trace payload 均透出 `include_deprecated`；模型仅在用户明确问旧版/历史年份时传 `true`
- `scripts/eval_retrieval.py`：`GoldItem` 支持逐条 `include_deprecated`，新增 `--include-deprecated` 全局开关；`generate_gold_set.py` 给 g055/g056 标记 `include_deprecated=true`，CSV 增加对应列
- 真实检索验证：默认“退货政策是几天”top1 为 POL-RET-001（新版），`include_deprecated=true` 时 POL-RET-002 回到 top1；商品过滤“VK75 Pro 七天无理由”返回 STORE 政策
- 评测结果（默认过滤）：Recall@5 0.921、Hit@5 0.986、MRR 0.725、误拒率 0；拒答准确率从 40% 降到 30%（g074 花呗分期 top=0.551 卡阈值），属意图路由问题
- 新增/更新测试 7 个，总数 97，全部通过

### 2026-10-25：scope_kind 拆分 + 混合检索 + CrossEncoder rerank

- 新增 `scope_kind` 生成列（`product` / `store` / `platform`）到父子表，配 `(scope_kind, product_id)` 索引；`docker/initdb/002_knowledge.sql` 和 `scripts/migrate_scope_kind.py` 均已更新，本地库已迁移（342 父块 / 1504 子块）
- `rag/search.py` 商品过滤改为 `c.product_id = %s OR c.scope_kind IN ('store','platform')`
- 新增 `rag/tokenize.py`：jieba 可选，未装时中文按二元组切分；型号/编号会额外拆出字母与数字
- 新增 `rag/bm25.py`：纯 Python BM25（无 numpy 依赖），内存索引，TTL 默认 300s，支持商品/STORE/PLATFORM 与 deprecated 过滤
- 检索流程：稠密 top-k + BM25 top-k → RRF（k=60）→ 父块去重 → 可选 CrossEncoder rerank → top_k；拒答仍只看稠密最高分
- 新增 `rag/rerank.py`：`sentence-transformers` CrossEncoder 懒加载；未安装/加载失败/打分失败时自动保留 RRF 排序并记录警告
- 配置新增 `RAG_HYBRID_ENABLED`、`RAG_SPARSE_CANDIDATES`、`RAG_RRF_K`、`RAG_BM25_INDEX_TTL`、`RERANK_*`，模板见 `.env.example`
- 依赖已安装：`jieba 0.42.1`、`sentence-transformers 6.2.0`、`torch 2.14.1`（pip 走清华镜像）
- rerank 模型已从 `hf-mirror.com` 下载到 `data/models/bge-reranker-base`（约 1.1 GB，已加入 `.gitignore`）；`.env` 的 `RERANK_MODEL` 指向该本地目录，`RERANK_DEVICE=cpu`
- 已验证：CrossEncoder 本地加载成功，相关句得分 0.251、无关句 0.00004；BM25 索引加载 1504 条、`available=True`
- 启动时后台线程预热 BM25；新增 `knowledge_state` 单行版本表，`upsert_knowledge` 每次入库后 `version+1`
- BM25 每次检索都会校验版本号，入库后下一次查询立即重建（不再等 TTL）；`knowledge_state` 缺失时退回 TTL 300s
- 20 条抽样评测（16 可回答 / 4 拒答；覆盖商品参数/概述/FAQ/对比、退货、旧版、平台、表格、扫描件、拒答）：
  - 纯稠密：Recall@5 0.875、Hit@5 0.938、MRR 0.781、平均 0.26s
  - 混合检索：Recall@5 **0.943**、Hit@5 **1.000**、MRR 0.734、平均 0.25s
  - 混合+rerank(child)：Recall@5 0.906、Hit@5 0.938、MRR 0.705、平均 2.61s
  - 混合+rerank(parent)：Recall@5 0.901、Hit@5 0.938、MRR 0.745、平均 5.44s
  - 结论：混合检索提升覆盖率且不增延迟；rerank 仍不如不 rerank，且 CPU 延迟不可接受，暂保持关闭
  - 拒答准确率仍为 0.25：g074 花呗、g078 查订单、g080 推荐商品均被 RAG 误答，需意图路由

### 2026-10-25：意图路由 P1（规则层）

- 新增 `agent/router.py`：5 个一级路由 `knowledge` / `product` / `transaction` / `handoff` / `chat`，二级 `sub_intent` 用于统计与后续拆分
- 规则覆盖：提示词注入、转人工、投诉、订单号/物流单号、订单/物流/售后、支付、优惠券、推荐、发票、商品实时数据、政策知识、隐私边界、寒暄、超范围
- `transaction` 通过 `SUB_INTENT_TOOLS` 自动选择工具；订单/物流/售后/支付/优惠/推荐工具后续均已注册
- 工具白名单：`openai_tools(allowed=...)` 按路由裁剪；`run_llm_agent(session, route=...)` 追加路由提示
- `main.py` 在调用模型前路由；`handoff/clarify/reply` 直接确定性回复，不额外调模型；trace 新增 `route/routes/sub_intent/route_action/confidence/source/slots`
- 商家端 trace 增加“路由”步骤，展示意图、动作、置信度、可用工具、槽位
- 未跑测试/评测；已用 20 条样例手工核对路由结果，关键路径符合预期
- 当前限制：规则层，无 LLM 兜底；支付/优惠/推荐当时仍先转人工，后续工具注册后已改走工具；可加 L2 结构化分类

### 2026-10-25：Mock 订单/物流/售后与买家切换

- 新增 `scripts/generate_orders.py`：确定性生成 24 位买家、60 笔订单、40 条物流、8 条售后，覆盖待付款/待发货/运输中/签收/异常/取消/退款中等状态
- 数据在 `data/orders/`：`buyers.json`、`orders.json`、`logistics.json`、`aftersales.json`；地址和手机号已脱敏，商品来自现有 catalog
- 新增 `services/orders.py`：读取数据、按 `buyer_id` 过滤；所有订单/物流/售后查询都校验归属，Cross-buyer 访问返回未找到
- 新增 `tools/orders.py` 与 `tools/context.py`：`get_order` / `get_logistics` / `get_aftersale`，缺少订单号时返回最近列表
- `tools/registry.py`：`ToolContext` 注入、`uses_context`、`openai_tools(allowed=...)`；写操作幂等摘要纳入 `buyer_id`
- `SessionState` 增加 `buyer_id` 并持久化；`ChatRequest` 支持 `buyer_id`；`/api/demo/buyers` 提供 24 位买家
- 前端买家端增加“当前买家”输入框 + datalist，可输入/切换买家 ID；切换后自动开新会话；请求携带 `buyer_id`
- 订单路由已自动从 `handoff` 切到 `tool`；`我的订单`/`我的订单到哪了`/`退款进度` 会命中对应工具
- 回归：`pytest tests -q` 97 通过；手工验证买家列表、订单查询、物流查询、售后查询、跨买家隔离、前端买家输入框与 `buyer_id` 请求字段
- 当前限制：当时 `buyer_id` 由前端传入，不是真实登录鉴权；后续已改为买家登录 Token（见 2026-10-25 鉴权记录）

### 2026-10-25：订单写操作与售后工单

- 新增写工具：`cancel_order`、`update_address`、`intercept_parcel`、`create_aftersale`，均为 `kind="write"`，走确认 + 幂等
- `services/orders.py` 改为 SQLite 可变状态库（`data/orders/orders.db`）：首次从 JSON seeding，之后读写都走库；`scripts/generate_orders.py` 重新生成时会删除 DB
- 状态机：待付款/已付款可取消；发货前可改地址；运输中可拦截；签收后 7 天内可创建售后
- 售后工单写入 `aftersales` 表，生成 `AS-xxxx` 编号与时间线；重复申请返回已有工单
- 路由新增写子意图：`cancel_order` / `update_address` / `intercept` / `create_aftersale`，自动放行对应工具
- `resolve_pending_confirmation` 确认执行时携带 `ToolContext`，写操作幂等摘要包含 `buyer_id`
- `data/orders/orders.db` 已加入 `.gitignore`
- 回归：`pytest tests -q` 97 通过；手工验证取消、改地址、拦截、创建售后、重复取消/重复售后、确认流程
- 当前限制：写操作只改 mock 状态，不接真实支付/退款；拦截结果为模拟；`buyer_id` 仍非真实鉴权

### 2026-10-25：支付/优惠/推荐工具与真实模型端到端验证

- 新增 `get_payment_methods`：支付宝/微信/花呗分期/银行卡/货到付款（货到付款不可用），可带订单号返回当前支付方式
- 新增 `get_coupons`：读取当前买家的可用优惠券；生成器新增 48 张 mock 优惠券，写入 `coupons.json` 与 SQLite `coupons` 表
- 新增 `recommend_products`：按预算/品类/场景从真实商品库筛选，过滤缺货，返回价格、库存、活动，禁止模型编造
- 路由 `payment/coupon/recommend` 自动从 `handoff` 切到 `tool`；系统提示新增规则 12
- 真实模型端到端验证（DeepSeek `deepseek-chat`）：
  - 取消订单：模型直接调 `cancel_order` → 确认 → 状态 `canceled`
  - 售后：直接调 `create_aftersale` → 确认 → 工单创建成功
  - 支付/优惠/推荐：分别调 `get_payment_methods` / `get_coupons` / `recommend_products`，无转人工
- 修复：写操作路由提示明确“直接调用写工具，不要先用查询工具确认”；否则模型会先查订单再口头询问
- 回归：`pytest tests -q` 97 通过；数据已重置
- 注意：用 TestClient 连续流式请求时出现 `Event loop is closed`，是测试客户端跨事件循环的问题；直接 `asyncio.run` 调 `run_llm_agent` 已验证正常。真实 uvicorn 单事件循环不受影响

### 2026-10-25：管理接口鉴权与买家登录

- 新增 `core/auth.py`：无状态 HMAC Token（payload + 签名，含过期时间），支持签发/校验/Bearer 解析
- `ADMIN_TOKEN`：`/api/admin/*` 全部要求 `X-Admin-Token`（或 `Authorization: Bearer`）；未配置返回 503，错误返回 401
- 买家登录：`POST /api/auth/buyer/login`，用 `buyer_id + login_code` 换 Token；`GET /api/auth/buyer/me` 校验身份
- `data/orders/buyers.json` 新增 6 位 `login_code`；`/api/demo/buyers` 不返回登录码
- 会话绑定：登录买家访问已绑定其他买家的会话返回 403；已绑定会话未带 Token 返回 401
- `/api/chat/stream` 与 `/api/chat/messages` 从 Token 推导 `buyer_id`，**不再信任前端传入的 buyer_id**；`ChatRequest` 已移除该字段
- 前端买家端改为“买家 ID + 登录码”登录，Token 存 sessionStorage；聊天/轮询自动带 Bearer Token
- 前端商家端新增管理 Token 输入框，所有管理请求带 `X-Admin-Token`；未登录/失效时显示登录提示
- `.env` 已生成 `ADMIN_TOKEN`、`AUTH_SECRET`（值不记录）；`.env.example` 已更新
- 回归：`pytest tests -q` 99 通过；手工验证管理接口 401/200、买家登录/校验、跨买家会话 403、无 Token 访问 401、买家列表不泄露登录码
- 当前限制：Token 无状态，无法主动吊销；登录码是 mock 凭据，真实系统必须接短信/账号登录；管理 Token 是单账号共享 Token

### 2026-10-25：关闭 rerank + HTTP 端到端验收

- `RERANK_ENABLED` 默认改为 `false`，`.env` 与 `.env.example` 同步；模型和依赖保留，后续换更强模型可再开
- 用真实 uvicorn（随机端口）+ httpx 做 HTTP 端到端验收，避免 TestClient 跨事件循环问题；**13 项全部通过**：
  - rerank 已关闭、管理接口无 Token 401 / 正确 Token 200
  - 3 个买家登录成功
  - “我的订单”命中 `get_order` 且不转人工
  - 取消订单 → `confirm_required` → 确认 → 状态 `canceled`
  - 申请退货退款 → `confirm_required` → 确认 → 售后工单创建
  - 商家接管 + 人工回复 → 买家轮询可见
  - 其他买家访问该会话 → 403
- 验收后已重新生成 mock 数据，DB 重置
- 回归：`pytest tests -q` 99 通过
- 验收脚本为临时文件，未入库；真实模型调用约 5 轮

### 2026-10-27：项目重定位与 LangGraph 接入

- 重写 `AGENTS.md`：定位改为“个人开发 / 对标生产 / Mock Provider / 不声称生产验证”，技术栈表、运行时拓扑、生产化验收标准、M4–M7 路线图定稿
- 两个待定项定稿：Redis 存热状态（会话缓存/限流/幂等），PostgreSQL 存持久状态（消息/trace/checkpoint/业务单据）；rerank 保留但默认关闭
- 安装 `langgraph 1.2.18` + `langchain-core 1.7.0`（未装 `langchain-openai`）
- 新增 `agent/graph_agent.py`：`StateGraph`（agent/tools/confirm/handoff/empty/max_steps/finish），`stream_mode="custom"` 保持原 SSE 事件契约；工具节点用 `asyncio.gather` **并行执行**
- 新增 `agent/legacy_agent.py`（原自研循环）与 `agent/agent_utils.py`（共享 helper）；`agent/llm_agent.py` 改为按 `AGENT_ENGINE` 分发，默认 `graph`
- 修复批量工具调用中写操作导致后续调用被丢弃的问题（写操作确认后不再丢掉同批次的只读调用事件）
- `core/config.py` 新增 `agent_engine` 与启动校验；`.env` / `.env.example` 增加 `AGENT_ENGINE=graph`
- 新增 3 个测试（并行耗时、批量写不丢调用、legacy 分发），总数 102，全部通过
- 真实模型冒烟：graph 引擎下纯问答与 `get_product` 工具调用均正常，事件为 `llm_step` / `delta` / `tool_call`
- 未做：checkpointer + `interrupt()` 中断恢复、路由 L2、Redis/Postgres 迁移（按路线图留到 M4/M5 收尾）

### 2026-10-27：checkpointer + interrupt() 中断恢复

- 安装 `langgraph-checkpoint-sqlite 3.1.2`（带入 `aiosqlite 0.22.1`）
- 新增 `agent/checkpoint.py`：`AsyncSqliteSaver`（持久）/ `MemorySaver`（测试）按事件循环缓存，支持 `delete_thread`
- `agent/graph_agent.py` 新增 `confirm`（只调用 `interrupt()`，无副作用）、`write`、`cancelled` 节点；`tools` 节点发现写操作只记录 pending 并路由到 `confirm`
- 确认：`Command(resume={"approved": True})` → `write` 节点执行（幂等键沿用 pending 或请求传入）→ 回填 tool 消息 → 模型生成最终回复
- 取消：`Command(resume={"approved": False})` → `cancelled` 节点回填拒绝消息 → 模型回复；写操作不执行
- `main.py` 有 pending 时优先走 `run_graph_agent_resume`；断点缺失回退到旧的 `resolve_pending_confirmation`；用户转向新问题时删除该线程断点并继续正常处理
- `core/config.py` 新增 `agent_checkpoint_backend`（sqlite/memory）与 `agent_checkpoint_db_path`；测试 `conftest.py` 强制 memory
- 真实 HTTP 验证：创建待确认 → **杀掉服务重启** → 发“确认” → 从 SQLite 断点恢复并只执行一次，订单状态变为 `canceled`；“算了”路径返回 `confirmation_cancelled`，订单保持 `pending_payment`
- 新增 3 个测试（确认/取消/无断点），总数 105，全部通过
- 未做：路由 L2；checkpoint 迁 Postgres 与清理策略（M4）

### 2026-10-27：路由 L2（LLM 结构化分类兜底）

- `agent/router.py` 新增 `route_message_l2`：先跑规则层 L1，仅在 `action=clarify` 或通用 `knowledge` 时调用 LLM 分类
- 分类输出 `route/sub_intent/confidence/reason`，`temperature=0`、`response_format=json_object`、超时 `ROUTER_LLM_TIMEOUT`
- 合并策略：置信度 ≥ `ROUTER_LLM_MIN_CONFIDENCE`（0.7）才覆盖 L1；超时/JSON 非法/未知路由保留 L1
- 政策题、已识别 `product_id` 的知识题不触发 L2，避免无谓调用
- `main.py` 改用 `await route_message_l2(...)`；trace 新增 `route_reason`，路由步骤记录 `source=llm/rule`
- `core/config.py` 新增 `ROUTER_LLM_ENABLED/MIN_CONFIDENCE/TIMEOUT/MAX_TOKENS`；`.env.example` 同步
- 新增 10 个测试，总数 115，全部通过
- 真实模型冒烟：「我的东西怎么还没到」→ transaction/logistics（llm，0.9）；「钱什么时候能退回来」→ transaction/aftersale（0.85）；「今天天气不错」→ chat/smalltalk
- M5 编排升级完成；下一步 M4 生产底座

### 2026-10-28：M4 前半（依赖锁定 / 容器 / CI / Redis）

- 新增 `pyproject.toml` + `uv.lock`（137 包锁定）；核心依赖不含 torch，rerank 改为可选 extra
- 配置 ruff（E/F/I，line-length 100）与 mypy（检查 main/agent/core/tools/rag/services）；修复 33 个 mypy 问题，`ruff`、`mypy` 全绿
- 新增 `Dockerfile`（python:3.12-slim + uv，`pip install uv` 避免 ghcr.io 不可达）；`.dockerignore`
- `docker-compose.yml` 扩为 api + postgres + redis，带健康检查；`docker compose up -d` 起全栈，`/health` 返回 healthy
- 新增 `.github/workflows/ci.yml`：`uv sync --frozen` + ruff + mypy + pytest；本地通过，未推远端
- 新增 `core/cache.py`：`CACHE_BACKEND=memory|redis`，连接失败自动回退
- 限流改 Redis `INCR + EXPIRE`；写操作幂等改 `idempotency:lock`（SET NX EX 60）+ `idempotency:result`（24h）；会话新增 `RedisSessionStore`
- 跨进程验证：会话可见、限流共享、同一幂等键只执行一次；双 uvicorn worker 下 admin 详情连续 8 次均返回 2 条消息
- 容器内验证：`CACHE_BACKEND=redis`，发一条“你好”后 Redis 出现 `session:<id>`
- 新增 3 个 Redis 测试，总数 118，全部通过
- 未做：订单/会话/checkpoint 迁 Postgres、SSE 心跳、日志指标告警、LLM 熔断/备用、DB 连接池

### 2026-10-28：业务数据与 checkpoint 迁 Postgres

- `services/orders.py` 增加 `ORDERS_BACKEND=postgres|sqlite`；Postgres 通过 `psycopg_pool` 连接池执行，SQL `?` 与 `BEGIN IMMEDIATE` 在适配层转换
- 新增 `core/db.py`：连接池大小/超时可配；空表启动时从 `data/orders/*.json` 幂等 seed
- `scripts/generate_orders.py` 改为 reset 当前后端（PG `TRUNCATE` / SQLite 删文件）
- `agent/checkpoint.py` 增加 `AsyncPostgresSaver`（`AGENT_CHECKPOINT_BACKEND=postgres`）；Compose 设置 postgres，Windows 本地保留 sqlite（ProactorEventLoop 限制）
- 验证（容器内）：
  - 订单查询/取消/跨买家隔离/物流查询走 PG
  - 创建待确认 → **重启 api 容器** → 发“确认” → 从 PG 断点恢复并只执行一次，订单状态变为 `canceled`
- 新增依赖 `psycopg-pool 3.3.3`、`langgraph-checkpoint-postgres 3.2.0`；锁文件 138 包
- 118 个测试、ruff、mypy 全部通过
- 未做：消息/trace 持久化到 PG；SSE 心跳；日志指标告警；LLM 熔断/备用

### 2026-10-28：消息/trace 落 Postgres + 清理脚本

- `agent/session_store.py` 新增 `PostgresSessionStore` 与 `CompositeSessionStore`；`SESSION_STORE_BACKEND=postgres|sqlite`
- 写路径：先 upsert `chat_sessions`（payload JSONB），再更新 Redis 热缓存；读路径：Redis 命中直接返回，miss 时从 PG 回源并回填
- 表结构：`chat_sessions(session_id TEXT PK, payload JSONB, updated_at DOUBLE PRECISION)`；消息与 trace 存在 payload 内
- 新增 `scripts/prune_sessions.py`：按 `SESSION_RETENTION_DAYS` 删除过期会话，支持 `--dry-run`
- Compose 设置 `SESSION_STORE_BACKEND=postgres`；本地默认 sqlite，无需额外依赖
- 容器内验证：发“你好”后 PG 有 2 条消息、Redis 有热 key；删除 Redis key 后 admin 详情仍能从 PG 恢复并回填
- 清理脚本验证：插入 0 时间戳会话 → dry-run 1 → 删除 1 → dry-run 0
- 新增 1 个 Composite 测试，总数 119；ruff/mypy/pytest 全绿
- 未做：SSE 心跳、日志指标告警、LLM 熔断/备用

### 2026-10-28：SSE 心跳 + 可观测 + LLM 熔断（M4 完成）

- 新增 `core/sse.py`：独立 pump 任务 + 队列，按 `SSE_HEARTBEAT_SECONDS` 发 `: ping` 注释帧
- `core/logging.py` 支持 `LOG_FORMAT=json`；`core/metrics.py` 记录请求/延迟/工具/转人工/LLM 错误，新增 `GET /api/admin/metrics`
- 新增 `core/alerts.py`：固定 ERROR 日志，可选 `ALERT_WEBHOOK_URL` 异步 POST；LLM 失败与熔断打开时触发
- `agent/agent_utils.py` 新增 `resolve_llm()`、连续失败熔断与 `LLM_FALLBACK_*` 备用供应商；graph/legacy 共用
- Compose 设置 `LOG_FORMAT=json`
- 容器验证：`/api/admin/metrics` 返回请求计数与延迟；业务日志为 JSON 行
- 新增 7 个测试（SSE/指标/熔断），总数 127；ruff/mypy/pytest 全绿
- M4 完成；剩余 CI 推远端验证

### 2026-10-31：工具层 MCP 化（内部 server + 令牌 + server 侧幂等）

- 目标：把可复用业务能力从 Agent 进程解耦；控制面（转人工、确认门禁、trace、结果隔离）继续留在 Agent
- 新增 `mcp_servers/`：`mcp-commerce`（订单/物流/售后/支付/优惠 9 工具）、`mcp-catalog`（商品 + 推荐 2 工具）、`mcp-knowledge`（检索 1 工具）；streamable HTTP `/mcp` + `/health`
- 新增 `tools/mcp_client.py`：按 server 建短连接，结构化结果优先、文本 JSON 回退，错误统一抛 `MCPToolError`
- `ToolSpec` 增加 `server` 字段；新增 `execute_tool_async`，`TOOL_BACKEND=mcp` 时带 `server` 的工具走 MCP，其余与 `local` 一样走进程内实现；graph / legacy / 主流程确认回退全部改为异步执行
- 新增 `core/tool_auth.py`：`tool_context`（sub/sid/scopes/exp）与 `write_approval`（tool/args_digest/jti/exp）令牌；`buyer_id` 不进模型可见参数
- server 侧强制校验：commerce 读工具必须带上下文令牌；写工具必须带审批令牌且参数摘要匹配；幂等键为 `tool + jti + args_digest`，Redis 优先、内存回退
- 知识工具语义调整：`search_knowledge` 只返回 `abstained/score/hits`，低分转人工统一在 Agent 的 `_finalize_result` 判断，local/mcp 行为一致
- Compose 扩为 api + 3 个 MCP server + postgres/redis；api 环境 `TOOL_BACKEND=mcp` 并指向容器内地址，`/health` 返回 `tools=mcp`
- 新增 `scripts/run_mcp_servers.py`、`scripts/smoke_mcp.py`；本地不启动 server 时仍用 `TOOL_BACKEND=local`
- 验证：
  - 内存 MCP 会话：catalog/commerce/knowledge 工具、读令牌、写审批、参数篡改拒绝、同 jti 幂等
  - 真实 HTTP：本地三 server、Compose 三容器均通过 smoke；Agent 侧 `TOOL_BACKEND=mcp` 调 `get_product` / `get_order` / `search_knowledge` 成功，未确认写操作返回 `confirm_required`
  - 全栈：`docker compose up -d` 后 `/health` 为 `tools=mcp`，真实买家登录 + SSE 对话触发 `get_product`，mcp-catalog 日志出现 `CallToolRequest`
- 新增 20 个测试，总数 147；ruff/mypy/pytest 全绿；`docker compose config` 通过
- 未做：外部 MCP（平台/物流/支付/ERP）、MCP 连接复用、Agent 端到端评测

### 2026-11-04：M6 商品只读接入 Saleor

- 在 `D:\workspace\saleor-main\saleor-main` 部署 Saleor 3.24：独立 venv（`uv sync --frozen --no-dev` + pytest）、Postgres `saleor` 库、Redis db3、`manage.py migrate`、`populatedb --createsuperuser`
- 修复 Windows 兼容：`saleor/core/rlimit.py` 对 `resource` 缺失做降级
- 新增 `scripts/import_catalog_to_saleor.py`：建 CNY 渠道 `emberfox`、仓库、商品类型、分类；导入 100 个商品（SKU = P 编号、变体、渠道价、库存），幂等
- 新增 `services/saleor_products.py`：GraphQL 查询商品/变体/渠道价/库存，映射为现有 `get_product` 结构；超时与 5xx 返回转人工提示
- `tools/products.py` 增加 `PRODUCT_PROVIDER=mock|saleor` 分发；`detect_product_id` 仍用本地索引
- 配置新增 `PRODUCT_PROVIDER`、`SALEOR_*`；Compose 通过 `host.docker.internal:8001` 访问宿主 Saleor
- 验证：本地 `get_product` 返回价格 969/库存 56/`source=saleor`；容器内 `TOOL_BACKEND=mcp` → mcp-catalog → Saleor，Agent 回答价格 969、库存 56
- 新增 4 个契约/故障测试，总数 152；ruff/mypy/pytest 全绿
- **订单只读**：新增 `scripts/import_orders_to_saleor.py`，用 `orderBulkCreate` 导入 60 笔订单；`services/saleor_orders.py` + `ORDER_PROVIDER=saleor` 让 `get_order`/`list_orders` 走 GraphQL
- 订单映射：externalReference = 订单号，metadata 存 buyer_id/legacy_status/tracking；跨买家查询返回 None
- 验证：本地与容器内（mcp-commerce → Saleor）均能查到订单，回答金额/状态/物流单号正确
- **物流只读**：`services/saleor_orders.py` 增加 fulfillment 映射；`get_logistics`/`list_shipments` 走 Saleor，支持订单号/运单号查询与买家归属校验
- 验证：按订单号、运单号均命中；跨买家 None；容器内 Agent 回答“5 条物流记录”
- **售后只读**：新增 `scripts/sync_aftersales_to_saleor.py`，13 条售后写入订单 metadata；`get_aftersale`/`list_aftersales` 走 GraphQL 读取
- 验证：AS-930-0002 返回退货退款/待商家处理/3197 元；跨买家 None；容器内 Agent 回答“3 条售后记录”
- **真实登录**：新增 `core/otp.py`、`core/sms.py`；`send-code` + `otp/login` 接口；OTP 存 Redis/memory，TTL 300s、5 次尝试、60s 冷却
- **手机号映射**：`services.orders.buyer_login_phone` 由脱敏手机号 + buyer_id 哈希生成；`/api/demo/buyers` 返回 `login_phone`；前端改为手机号 + 验证码
- **验证**：容器内发送验证码 → 登录 → `/me` → 对话查订单（5 笔）；旧 `buyer_id + login_code` 仍可用
- **操作审计**：新增 `core/audit.py` + `audit_log` 表；写操作（含确认尝试）与敏感读落库；`GET /api/admin/audit` 查询
- **灰度/回滚**：`SALEOR_ROLLOUT_PERCENT` 按买家哈希放量，`SALEOR_ALLOWLIST` 白名单；`ORDER_PROVIDER=mock` 或 percent=0 立即回滚
- 验证：容器内 `get_order` 产生 `read_sensitive` 审计；admin 接口返回记录；175 个测试全绿
- 未做：Saleor 原生 return/refund、写操作、真实短信网关、CI 推远端

### 2026-11-05：M7 评测启动（Agent 场景集 + 压测）

- 新增 60 条 Agent 场景集（`data/eval/agent_gold.jsonl`），覆盖售前/知识/订单/物流/售后/支付优惠/转人工/闲聊/安全
- 新增 `scripts/eval_agent.py`：`router`（L1 或 L1+L2）与 `tools`（脚本化参数）两种模式，输出 `reports/agent_eval.json`
- 新增 `scripts/load_test.py`：SSE/健康检查并发压测，输出 `reports/load_test.json`
- 首轮结果：路由 L1 60/60（100%）；工具合同 47/47（100%）；50 req / 10 并发，66.4 RPS，p95 103ms（问候路径，不调 LLM）
- 路由评测发现并修复 6 个规则缺口：催发货、物流异常、退款到账、最近买了什么、修改订单地址、API Key 注入
- **运营看板**：新增 `services/dashboard.py` 与 `GET /api/admin/dashboard`；解决率/转人工率/首响/路由分布/转人工原因；商家工作台新增 KPI 面板
- **首响**：trace 新增 `first_response_ms`，从收到消息到第一个 `delta`
- 验证：容器内 6 个会话/6 轮，解决率 66.7%、转人工率 33.3%、首响均值 0.2ms（规则回复）
- 未做：场景集 60→200、LLM 端到端评测、带工具/LLM 的压测；评测脚本未接 CI
