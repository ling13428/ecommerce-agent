# 项目状态与记忆

> 本文件用于跨会话接续。每次新会话开始先读本文件，结束前更新。
> 只记录长期有用的信息：进度、决策、下一步、坑。不要粘贴大段代码或原始对话。
> 最后更新：2026-10-19

## 一、当前进度

- 当前里程碑：**M1 售前起步 / 真实模型接入完成，待填 Key 冒烟**
- 已完成：
  - 环境：Python 3.12（使用 `py -3.12`），项目根目录虚拟环境 `.venv`
  - `fastapi[standard]`、`openai`、`pytest`、`pydantic-settings` 已安装
  - M0 流式骨架：`/health`、自定义 `/docs`、`POST /api/chat/stream` SSE
  - mock 商品工具与规则版 Agent（`tools/products.py`、`agent/mock_agent.py`）
  - **安全配置**：`.env`、`.env.example`、`.gitignore`；Key 只从环境变量读取
  - **配置层**：`core/config.py`，启动时校验 URL/模型，Key 用 `SecretStr` 掩码
  - **工具层**：`tools/registry.py`，JSON Schema 白名单、Pydantic 参数校验
  - **写操作门禁**：二次确认 + 幂等键 + 结果缓存，缺幂等键拒绝执行
  - **LLM Agent**：`agent/llm_agent.py`，OpenAI 兼容协议、流式 tool calling、超时、最大步数、转人工
  - **会话层**：`agent/session.py`，内存多轮历史、待确认操作、过期清理
  - **降级**：未配置 Key 或模型失败时回退到 `mock_agent`
  - **安全**：系统提示词防注入、工具结果隔离、日志脱敏、CORS 白名单、单会话限流
  - **测试**：`tests/` 共 17 个用例全部通过
  - Git 已在项目目录单独初始化（`main` 分支），`.env`/`.venv`/`.idea` 已忽略
- 进行中：无
- 下一步（建议顺序）：
  1. 在 `.env` 填入真实 Key，改好 `LLM_BASE_URL` / `LLM_MODEL`，重启做真实模型冒烟
  2. 补充多轮对话与真实工具调用的评测用例（订单/售后/转人工/安全）
  3. 做最小聊天页面（需安装 Node.js）
  4. 知识库 RAG 与引用来源
  5. 按 AGENTS.md 整理到 `backend/app/`

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
- SSE 事件：`start`、`tool_call`、`delta`、`confirm_required`、`confirmation_cancelled`、`handoff`、`fallback`、`error`、`done`
- 限流：按 `session_id` 每分钟请求数限制，默认 20
- 当前代码暂放项目根目录，后续再整理到 `backend/app/`

## 三、环境与版本

- 项目根目录：`D:\workspace\电商客服`
- 虚拟环境：`D:\workspace\电商客服\.venv`（Python 3.12）
- 启动：在项目根目录执行 `fastapi dev main.py`
- 测试：`.\.venv\Scripts\python.exe -m pytest -q`
- 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`（`llm` 字段显示 `configured` / `mock`）
- 系统默认 `python` 是 3.14.0a1 预览版，**不要使用**；用 `py -3.12`
- Node.js 未安装（做前端时再装）
- Docker、Git 已安装
- `.env` 关键项：`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`、`LLM_TIMEOUT`、`LLM_MAX_STEPS`、`LLM_MAX_TOKENS`、`RATE_LIMIT_PER_MINUTE`、`MAX_MESSAGE_CHARS`、`FRONTEND_ORIGINS`

## 四、文件地图

- `AGENTS.md`：项目目标、范围、原则、约定（唯一目标来源）
- `main.py`：FastAPI 应用、SSE 接口、确认流程、CORS、限流、商品调试接口
- `core/config.py`：环境变量配置与启动校验
- `core/security.py`：系统提示词、脱敏、工具结果隔离、确认/取消识别
- `core/logging.py`：日志初始化与脱敏异常日志
- `core/ratelimit.py`：单会话滑动窗口限流
- `agent/llm_agent.py`：真实模型 tool-calling 循环与流式输出
- `agent/mock_agent.py`：规则版 Agent（降级路径）
- `agent/session.py`：内存会话、历史、待确认操作
- `tools/registry.py`：工具白名单、Schema、参数校验、写操作门禁与幂等
- `tools/products.py`：mock 商品数据与 `get_product`
- `tests/`：配置、安全、工具、LLM 循环、确认流程测试
- `.env`：本机密钥（已忽略，不提交）
- `.env.example`：可提交的配置模板
- `.gitignore`：忽略密钥、虚拟环境、缓存、IDE
- `test_stream.py` / `test_tool.py`：旧的手工联调脚本
- `docs/PROJECT_STATE.md`：本文件，跨会话进度记忆

## 五、已知问题与注意事项

- `cdn.jsdelivr.net` 在本机不可达，`/docs` 必须使用镜像或本地静态资源
- PowerShell 直接打印中文可能乱码，属终端编码问题；PyCharm 控制台一般正常
- `main.py` 不能用 PyCharm 绿色三角直接运行，需 `fastapi dev main.py`
- 流式响应必须用 `httpx.stream` + `iter_lines()`；`httpx.post` 会等全部内容收完
- 响应头含 `transfer-encoding: chunked`，没有 `content-length`，属正常现象
- 当前 `.env` 的 `LLM_API_KEY` 为空，服务会走 mock；填入后需重启
- 会话与限流都在进程内存，多 worker/多实例不共享，生产前要换 Redis
- `session_id` 目前没有鉴权，知道 ID 就能接入同一会话；生产前需绑定用户身份
- 暂无真实写业务工具（取消订单/退款/改地址），门禁与幂等逻辑用测试工具验证
- 幂等缓存也在进程内存，最长 24 小时；生产写接口仍需业务侧幂等键
- 模型真实冒烟尚未执行（等用户填 Key）；工具循环用 Fake 客户端测试通过
- 商品别名匹配较简单，接真实商品库时换成检索或精确查询
- `.env.example` 里的 Key 是占位符，复制后必须替换，不能直接使用

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
