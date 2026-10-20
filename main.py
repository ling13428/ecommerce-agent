import asyncio
import json
import re
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent.llm_agent import run_llm_agent
from agent.mock_agent import run_mock_agent
from agent.session import SessionState, get_session
from core.config import get_settings
from core.logging import log_exception, logger, setup_logging
from core.ratelimit import allow_request
from core.security import is_affirmative, is_negative, redact, wrap_tool_result
from tools.products import PRODUCTS, get_product
from tools.registry import execute_tool

settings = get_settings()

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    try:
        settings.validate_startup()
    except ValueError as exc:
        logger.error("配置校验失败 | %s", redact(str(exc)))
        raise

    if settings.llm_configured:
        logger.info("LLM 已启用 | model=%s", settings.llm_model)
    else:
        logger.warning("未配置 LLM_API_KEY，当前使用 mock fallback")
    yield


app = FastAPI(title="电商客服 Agent", docs_url=None, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",
        swagger_js_url="https://fastly.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
        swagger_css_url="https://fastly.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
    )


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = Field(default=None, max_length=64)
    idempotency_key: str | None = Field(default=None, max_length=64)


def sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def resolve_pending_confirmation(
    session: SessionState,
    message: str,
    idempotency_key: str | None = None,
) -> dict | None:
    pending = session.pending_action
    if pending is None:
        return None

    if is_affirmative(message):
        session.clear_pending()
        result = execute_tool(
            pending.name,
            pending.args,
            confirmed=True,
            idempotency_key=idempotency_key or pending.idempotency_key,
        )
        ok = bool(result.get("ok"))
        session.add_system(
            "用户已明确确认执行写操作 "
            f"{pending.name}。工具结果：{wrap_tool_result(pending.name, result)}。"
            "该操作已处理，不要重复调用该工具。"
        )
        return {
            "type": "tool_call",
            "name": pending.name,
            "args": pending.args,
            "ok": ok,
            "confirmed": True,
        }

    if is_negative(message):
        reason = "用户取消"
    else:
        reason = "用户未确认，视为取消"

    session.clear_pending()
    session.add_system(f"待确认操作 {pending.name} 已取消（{reason}）。")
    return {"type": "confirmation_cancelled", "name": pending.name, "reason": reason}


async def mock_events(message: str, session: SessionState):
    result = run_mock_agent(message)
    tool_calls = result["tool_calls"]

    for call in tool_calls:
        yield {"type": "tool_call", "name": call["name"], "args": call["args"], "ok": True}

    for char in result["reply"]:
        yield {"type": "delta", "content": char}
        await asyncio.sleep(0.02)

    session.add_assistant(result["reply"])


async def agent_stream(
    message: str, session_id: str, idempotency_key: str | None = None
):
    session = get_session(session_id)
    session.add_user(message)

    yield sse({"type": "start", "session_id": session_id})

    streamed = False
    try:
        pending_event = resolve_pending_confirmation(
            session, message, idempotency_key
        )
        if pending_event is not None:
            yield sse(pending_event)

        if settings.llm_configured:
            try:
                async for event in run_llm_agent(session):
                    if event.get("type") == "delta":
                        streamed = True
                    yield sse(event)
            except Exception as exc:
                log_exception("agent.llm", exc)
                if streamed:
                    yield sse(
                        {
                            "type": "error",
                            "message": "模型服务中断，请稍后重试，或回复“转人工”。",
                        }
                    )
                else:
                    yield sse(
                        {
                            "type": "fallback",
                            "message": "模型服务暂不可用，已切换基础模式。",
                        }
                    )
                    async for event in mock_events(message, session):
                        yield sse(event)
        else:
            async for event in mock_events(message, session):
                yield sse(event)
    except Exception as exc:
        log_exception("agent.stream", exc)
        yield sse({"type": "error", "message": "服务暂时不可用，请稍后重试。"})

    yield sse({"type": "done", "session_id": session_id})


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空")
    if len(message) > settings.max_message_chars:
        raise HTTPException(
            status_code=413,
            detail=f"消息过长，最多 {settings.max_message_chars} 个字符",
        )

    if req.session_id is not None and not SESSION_ID_PATTERN.fullmatch(req.session_id):
        raise HTTPException(status_code=400, detail="session_id 格式不合法")
    if req.idempotency_key is not None and not SESSION_ID_PATTERN.fullmatch(
        req.idempotency_key
    ):
        raise HTTPException(status_code=400, detail="idempotency_key 格式不合法")

    session_id = req.session_id or uuid4().hex
    if not allow_request(session_id):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

    return StreamingResponse(
        agent_stream(message, session_id, req.idempotency_key),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/tools/products")
def product_list():
    return {"products": list(PRODUCTS.values())}


@app.get("/api/tools/products/{product_id}")
def product_detail(product_id: str):
    return get_product(product_id=product_id)


@app.get("/")
def read_root():
    return {"message": "ok"}


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "llm": "configured" if settings.llm_configured else "mock",
    }
