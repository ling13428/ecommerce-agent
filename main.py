import asyncio
import json
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent.checkpoint import delete_thread
from agent.graph_agent import NoPendingInterrupt, run_graph_agent_resume
from agent.llm_agent import run_llm_agent
from agent.mock_agent import run_mock_agent
from agent.router import RouteResult, route_message_l2
from agent.session import (
    SessionState,
    all_sessions,
    get_existing_session,
    get_session,
    list_sessions,
    load_persisted_sessions,
)
from core.alerts import send_alert
from core.audit import list_audit
from core.auth import AuthError, bearer_token, create_token, verify_token
from core.config import get_settings
from core.logging import log_exception, logger, setup_logging
from core.metrics import METRICS
from core.otp import OtpCooldown, issue_code, verify_code
from core.ratelimit import allow_request
from core.security import is_affirmative, is_negative, redact, wrap_tool_result
from core.sms import send_verification_code
from core.sse import with_heartbeat
from rag.bm25 import warmup_bm25
from services import orders as order_service
from services.dashboard import build_dashboard
from tools.context import ToolContext
from tools.products import PRODUCTS, get_product
from tools.registry import execute_tool_async

settings = get_settings()

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
BUYER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
PHONE_PATTERN = re.compile(r"^1\d{10}$")

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "frontend"


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

    if settings.session_persistence:
        try:
            loaded = load_persisted_sessions()
            logger.info("会话持久化已启用 | 已加载会话=%d", loaded)
        except Exception as exc:
            logger.warning("加载持久化会话失败 | %s", redact(str(exc)))
    else:
        logger.warning("会话持久化已关闭，重启后会丢失会话与轨迹")

    if settings.rag_hybrid_enabled:
        threading.Thread(
            target=warmup_bm25,
            args=(settings.database_url,),
            daemon=True,
            name="bm25-warmup",
        ).start()

    yield


app = FastAPI(title="电商客服 Agent", docs_url=None, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "Authorization", "X-Admin-Token"],
)


@app.middleware("http")
async def disable_static_cache(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/web"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@app.middleware("http")
async def record_request_metrics(request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        METRICS.observe_request(
            500, (time.perf_counter() - started) * 1000
        )
        raise
    METRICS.observe_request(
        response.status_code, (time.perf_counter() - started) * 1000
    )
    return response


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


class BuyerLoginRequest(BaseModel):
    buyer_id: str = Field(min_length=1, max_length=32)
    login_code: str = Field(min_length=1, max_length=32)


class SendCodeRequest(BaseModel):
    phone: str = Field(min_length=11, max_length=11)


class OtpLoginRequest(BaseModel):
    phone: str = Field(min_length=11, max_length=11)
    code: str = Field(min_length=4, max_length=8)


def _bearer_or_none(authorization: str | None) -> str | None:
    try:
        return bearer_token(authorization)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def require_admin(
    x_admin_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    expected = settings.admin_token_value
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="管理接口未配置 ADMIN_TOKEN，已拒绝访问",
        )
    token = (x_admin_token or _bearer_or_none(authorization) or "").strip()
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="管理 Token 不正确")


def _buyer_from_authorization(authorization: str | None) -> str | None:
    token = _bearer_or_none(authorization)
    if token is None:
        return None
    secret = settings.auth_secret_value
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="买家登录未配置 AUTH_SECRET",
        )
    try:
        payload = verify_token(token, secret)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    if payload.get("role") != "buyer":
        raise HTTPException(status_code=403, detail="Token 角色不合法")
    buyer_id = str(payload.get("sub") or "").strip().upper()
    if order_service.get_buyer(buyer_id) is None:
        raise HTTPException(status_code=401, detail="买家不存在")
    return buyer_id


def _require_buyer_id(authorization: str | None) -> str:
    buyer_id = _buyer_from_authorization(authorization)
    if buyer_id is None:
        raise HTTPException(status_code=401, detail="请先登录买家账号")
    return buyer_id


def _buyer_payload(buyer: dict[str, Any]) -> dict[str, Any]:
    return {
        "buyer_id": buyer["buyer_id"],
        "nickname": buyer["nickname"],
        "member_level": buyer["member_level"],
        "city": buyer["city"],
        "phone": buyer.get("phone"),
    }


def _check_session_buyer(
    session: SessionState | None, buyer_id: str | None
) -> None:
    if session is None or not session.buyer_id:
        return
    if buyer_id is None:
        raise HTTPException(status_code=401, detail="该会话已绑定买家，请先登录")
    if session.buyer_id != buyer_id:
        raise HTTPException(status_code=403, detail="无权访问该会话")


def sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def resolve_pending_confirmation(
    session: SessionState,
    message: str,
    idempotency_key: str | None = None,
) -> dict | None:
    pending = session.pending_action
    if pending is None:
        return None

    if is_affirmative(message):
        session.clear_pending()
        result = await execute_tool_async(
            pending.name,
            pending.args,
            confirmed=True,
            idempotency_key=idempotency_key or pending.idempotency_key,
            context=ToolContext(
                buyer_id=session.buyer_id,
                session_id=session.session_id,
            ),
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
            "detail": {"kind": "write", "result": result},
        }

    if is_negative(message):
        reason = "用户取消"
    else:
        reason = "用户未确认，视为取消"

    session.clear_pending()
    session.add_system(f"待确认操作 {pending.name} 已取消（{reason}）。")
    return {"type": "confirmation_cancelled", "name": pending.name, "reason": reason}


async def router_events(
    route: RouteResult, message: str, session: SessionState
):
    text = route.message or "我正在为你处理这个问题，请稍候。"
    yield {"type": "delta", "content": text}
    session.add_assistant(text)

    if route.action == "handoff":
        summary = (
            f"用户问题：{message[:200]}；"
            f"路由：{route.route}/{route.sub_intent}"
        )
        yield {
            "type": "handoff",
            "reason": route.reason or route.sub_intent,
            "summary": summary,
        }


async def mock_events(message: str, session: SessionState):
    result = run_mock_agent(message)
    tool_calls = result["tool_calls"]

    for call in tool_calls:
        detail = None
        if call.get("name") == "get_product" and "result" in call:
            detail = {"kind": "product", "result": call["result"]}
        yield {
            "type": "tool_call",
            "name": call["name"],
            "args": call["args"],
            "ok": True,
            "detail": detail,
        }

    for char in result["reply"]:
        yield {"type": "delta", "content": char}
        await asyncio.sleep(0.02)

    session.add_assistant(result["reply"])


async def agent_stream(
    message: str,
    session_id: str,
    idempotency_key: str | None = None,
    buyer_id: str | None = None,
):
    session = get_session(session_id)
    if buyer_id:
        session.set_buyer_id(buyer_id)
    user_message = session.add_user(message)
    started = time.perf_counter()

    trace: dict[str, Any] = {
        "user_message_id": user_message["id"],
        "user_message": message,
        "started_at": time.time(),
        "finished_at": None,
        "duration_ms": None,
        "status": "running",
        "model": settings.llm_model if settings.llm_configured else "mock",
        "buyer_id": session.buyer_id,
        "reply": "",
        "tool_calls": 0,
        "rag_hits": 0,
        "handoff_reason": None,
        "route": None,
        "routes": [],
        "sub_intent": None,
        "route_action": None,
        "route_confidence": None,
        "route_source": None,
        "route_reason": None,
        "slots": {},
        "first_response_ms": None,
        "steps": [],
    }
    recorded = False

    def add_step(kind: str, label: str, **detail: Any) -> None:
        step: dict[str, Any] = {
            "type": kind,
            "label": label,
            "at_ms": int((time.perf_counter() - started) * 1000),
        }
        step.update(detail)
        trace["steps"].append(step)

    def finish(status: str | None = None) -> None:
        nonlocal recorded
        if recorded:
            return
        recorded = True
        if trace["reply"]:
            add_step("reply", "生成最终回复", content=trace["reply"])
        if status:
            trace["status"] = status
        elif trace["status"] == "running":
            trace["status"] = "ok" if trace["reply"] else "empty"
        trace["finished_at"] = time.time()
        trace["duration_ms"] = int((time.perf_counter() - started) * 1000)
        session.add_trace(trace)

    def record_pending_event(pending_event: dict) -> None:
        detail = pending_event.pop("detail", None)
        if pending_event.get("type") == "tool_call":
            trace["tool_calls"] += 1
            add_step(
                "tool_call",
                f"执行写操作 {pending_event.get('name')}",
                name=pending_event.get("name"),
                args=pending_event.get("args"),
                ok=bool(pending_event.get("ok")),
                confirmed=True,
                detail=detail,
            )
        else:
            trace["status"] = "cancelled"
            add_step(
                "confirmation_cancelled",
                "写操作已取消",
                name=pending_event.get("name"),
                reason=pending_event.get("reason"),
            )

    add_step(
        "receive",
        "接收用户消息",
        message=message,
        human_mode=session.human_mode,
        model=trace["model"],
    )

    yield sse({"type": "start", "session_id": session_id})

    if session.human_mode:
        add_step("human_mode", "人工接管中，消息仅入库等待人工回复")
        finish("human_mode")
        yield sse(
            {
                "type": "human_mode",
                "message": "当前会话已由人工客服接管，你的消息已发送给客服。",
            }
        )
        yield sse({"type": "done", "session_id": session_id})
        return

    streamed = False

    async def pipe(events):
        nonlocal streamed
        async for event in events:
            event_type = event.get("type")
            if event_type == "llm_step":
                add_step(
                    "llm",
                    f"模型第 {event.get('step')} 轮",
                    step=event.get("step"),
                    tool_call_count=event.get("tool_call_count"),
                    has_text=event.get("has_text"),
                )
                continue
            if event_type == "delta":
                streamed = True
                if trace["first_response_ms"] is None:
                    trace["first_response_ms"] = round(
                        (time.perf_counter() - started) * 1000, 1
                    )
                trace["reply"] += event.get("content", "")
            elif event_type == "tool_call":
                detail = event.pop("detail", None)
                trace["tool_calls"] += 1
                METRICS.incr("tool_calls_total")
                add_step(
                    "tool_call",
                    f"调用工具 {event.get('name')}",
                    name=event.get("name"),
                    args=event.get("args"),
                    step=event.get("step"),
                    ok=bool(event.get("ok")),
                    confirmed=bool(event.get("confirmed", False)),
                    detail=detail,
                )
                if isinstance(detail, dict):
                    if detail.get("kind") == "rag":
                        trace["rag_hits"] += len(detail.get("hits") or [])
                        if detail.get("handoff_reason"):
                            trace["handoff_reason"] = detail.get("handoff_reason")
                    elif detail.get("kind") == "handoff":
                        trace["handoff_reason"] = detail.get("reason")
            elif event_type == "handoff":
                session.set_human_mode(True)
                METRICS.incr("handoffs_total")
                trace["status"] = "handoff"
                trace["handoff_reason"] = event.get("reason")
                add_step(
                    "handoff",
                    "转接人工客服",
                    reason=event.get("reason"),
                    summary=event.get("summary"),
                )
            elif event_type == "confirm_required":
                trace["status"] = "confirm_required"
                add_step(
                    "confirm_required",
                    "等待用户确认写操作",
                    name=event.get("name"),
                    summary=event.get("summary"),
                )
            elif event_type == "confirmation_cancelled":
                trace["status"] = "cancelled"
                add_step(
                    "confirmation_cancelled",
                    "写操作已取消",
                    name=event.get("name"),
                    reason=event.get("reason"),
                )
            elif event_type == "fallback":
                trace["status"] = "fallback"
                add_step(
                    "fallback",
                    "模型不可用，切换规则模式",
                    message=event.get("message"),
                )
            elif event_type == "human_mode":
                add_step(
                    "human_mode",
                    "消息已转给人工客服",
                    message=event.get("message"),
                )
            elif event_type == "error":
                trace["status"] = "error"
                add_step("error", "处理出错", message=event.get("message"))
            yield sse(event)

    route: RouteResult | None = None
    graph_engine = (
        (getattr(settings, "agent_engine", "graph") or "graph")
        .strip()
        .lower()
        == "graph"
    )
    skip_agent = False
    skip_routing = False
    try:
        pending = session.pending_action
        if pending is not None and graph_engine:
            if is_affirmative(message) or is_negative(message):
                approved = is_affirmative(message)
                add_step(
                    "confirm_resume",
                    (
                        "恢复图执行：用户已确认"
                        if approved
                        else "恢复图执行：用户已取消"
                    ),
                    approved=approved,
                )
                try:
                    async for chunk in pipe(
                        run_graph_agent_resume(
                            session,
                            approved=approved,
                            idempotency_key=idempotency_key,
                        )
                    ):
                        yield chunk
                    skip_agent = True
                except NoPendingInterrupt:
                    add_step(
                        "confirm_fallback",
                        "未找到图断点，回退为直接执行",
                    )
                    pending_event = await resolve_pending_confirmation(
                        session, message, idempotency_key
                    )
                    if pending_event is not None:
                        record_pending_event(pending_event)
                        yield sse(pending_event)
                        skip_routing = True
            else:
                await delete_thread(session.session_id)
                session.clear_pending()
                add_step(
                    "confirm_required",
                    "用户转向新问题，待确认操作已取消",
                )
        elif pending is not None:
            pending_event = await resolve_pending_confirmation(
                session, message, idempotency_key
            )
            if pending_event is not None:
                record_pending_event(pending_event)
                yield sse(pending_event)
                skip_routing = True

        if not skip_agent:
            if not skip_routing:
                route = await route_message_l2(
                    message, session, settings=settings
                )
                trace["route"] = route.route
                trace["routes"] = list(route.routes)
                trace["sub_intent"] = route.sub_intent
                trace["route_action"] = route.action
                trace["route_confidence"] = route.confidence
                trace["route_source"] = route.source
                trace["route_reason"] = route.reason
                trace["slots"] = dict(route.slots)
                add_step(
                    "route",
                    f"意图路由：{route.route}",
                    route=route.route,
                    routes=list(route.routes),
                    sub_intent=route.sub_intent,
                    action=route.action,
                    confidence=route.confidence,
                    source=route.source,
                    reason=route.reason,
                    slots=dict(route.slots),
                    allowed_tools=sorted(route.allowed_tools),
                )

            if route is not None and route.action in {
                "handoff",
                "clarify",
                "reply",
            }:
                async for chunk in pipe(
                    router_events(route, message, session)
                ):
                    yield chunk
            elif settings.llm_configured:
                try:
                    async for chunk in pipe(
                        run_llm_agent(session, route=route)
                    ):
                        yield chunk
                except Exception as exc:
                    log_exception("agent.llm", exc)
                    METRICS.incr("llm_errors_total")
                    send_alert(
                        "llm_failure",
                        f"{type(exc).__name__}: {exc}",
                        session_id=session_id,
                        streamed=streamed,
                    )
                    if streamed:
                        trace["status"] = "error"
                        add_step("error", "模型服务中断", error=str(exc))
                        yield sse(
                            {
                                "type": "error",
                                "message": "模型服务中断，请稍后重试，或回复“转人工”。",
                            }
                        )
                    else:
                        trace["status"] = "fallback"
                        add_step(
                            "fallback",
                            "模型调用失败，切换规则模式",
                            error=str(exc),
                        )
                        yield sse(
                            {
                                "type": "fallback",
                                "message": "模型服务暂不可用，已切换基础模式。",
                            }
                        )
                        async for chunk in pipe(
                            mock_events(message, session)
                        ):
                            yield chunk
            else:
                async for chunk in pipe(mock_events(message, session)):
                    yield chunk
    except Exception as exc:
        log_exception("agent.stream", exc)
        trace["status"] = "error"
        add_step("error", "服务异常", error=str(exc))
        yield sse({"type": "error", "message": "服务暂时不可用，请稍后重试。"})
    finally:
        finish()

    yield sse({"type": "done", "session_id": session_id})


@app.post("/api/auth/buyer/login")
def buyer_login(req: BuyerLoginRequest):
    secret = settings.auth_secret_value
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="买家登录未配置 AUTH_SECRET",
        )
    if not BUYER_ID_PATTERN.fullmatch(req.buyer_id):
        raise HTTPException(status_code=400, detail="买家 ID 格式不合法")
    buyer = order_service.verify_buyer_login(req.buyer_id, req.login_code)
    if buyer is None:
        raise HTTPException(status_code=401, detail="买家 ID 或登录码不正确")
    token = create_token(
        buyer["buyer_id"],
        secret,
        role="buyer",
        ttl_seconds=settings.buyer_token_ttl_hours * 3600,
    )
    return {"token": token, "buyer": _buyer_payload(buyer)}


def _normalize_phone(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


@app.post("/api/auth/buyer/send-code")
def buyer_send_code(req: SendCodeRequest):
    if not settings.auth_secret_value:
        raise HTTPException(
            status_code=503,
            detail="买家登录未配置 AUTH_SECRET",
        )
    phone = _normalize_phone(req.phone)
    if not PHONE_PATTERN.fullmatch(phone):
        raise HTTPException(status_code=400, detail="手机号格式不正确")

    try:
        code, ttl = issue_code(phone)
    except OtpCooldown as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    if order_service.find_buyer_by_phone(phone) is not None:
        send_verification_code(phone, code)

    payload: dict[str, Any] = {"ok": True, "expires_in": ttl}
    if settings.sms_debug:
        payload["debug_code"] = code
    return payload


@app.post("/api/auth/buyer/otp/login")
def buyer_otp_login(req: OtpLoginRequest):
    secret = settings.auth_secret_value
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="买家登录未配置 AUTH_SECRET",
        )
    phone = _normalize_phone(req.phone)
    if not PHONE_PATTERN.fullmatch(phone):
        raise HTTPException(status_code=400, detail="手机号格式不正确")

    if not verify_code(phone, req.code.strip()):
        raise HTTPException(status_code=401, detail="验证码不正确或已过期")

    buyer = order_service.find_buyer_by_phone(phone)
    if buyer is None:
        raise HTTPException(status_code=401, detail="手机号或验证码不正确")

    token = create_token(
        buyer["buyer_id"],
        secret,
        role="buyer",
        ttl_seconds=settings.buyer_token_ttl_hours * 3600,
    )
    return {"token": token, "buyer": _buyer_payload(buyer)}


@app.get("/api/auth/buyer/me")
def buyer_me(authorization: str | None = Header(default=None)):
    buyer_id = _require_buyer_id(authorization)
    buyer = order_service.get_buyer(buyer_id)
    if buyer is None:
        raise HTTPException(status_code=401, detail="买家不存在")
    return {"buyer": _buyer_payload(buyer)}


@app.post("/api/chat/stream")
async def chat_stream(
    req: ChatRequest,
    authorization: str | None = Header(default=None),
):
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

    buyer_id = _buyer_from_authorization(authorization)
    session_id = req.session_id or uuid4().hex
    _check_session_buyer(get_existing_session(session_id), buyer_id)
    if not allow_request(session_id):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

    return StreamingResponse(
        with_heartbeat(
            agent_stream(
                message,
                session_id,
                req.idempotency_key,
                buyer_id,
            ),
            float(getattr(settings, "sse_heartbeat_seconds", 15.0)),
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class TakeoverRequest(BaseModel):
    enabled: bool = True


class AdminReplyRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


def _validate_session_id(session_id: str) -> None:
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="session_id 格式不合法")


def _require_session(session_id: str) -> SessionState:
    _validate_session_id(session_id)
    session = get_existing_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    return session


@app.get("/api/admin/metrics", dependencies=[Depends(require_admin)])
def admin_metrics():
    return METRICS.snapshot()


@app.get("/api/admin/dashboard", dependencies=[Depends(require_admin)])
def admin_dashboard(days: int = 7):
    return build_dashboard(
        all_sessions(),
        days=min(max(days, 1), 90),
    )


@app.get("/api/admin/audit", dependencies=[Depends(require_admin)])
def admin_audit(limit: int = 50, actor: str | None = None):
    return {
        "items": list_audit(
            limit=min(max(limit, 1), 200),
            actor=actor,
        )
    }


@app.get("/api/admin/sessions", dependencies=[Depends(require_admin)])
def admin_sessions():
    return {"sessions": list_sessions()}


@app.get(
    "/api/admin/sessions/{session_id}",
    dependencies=[Depends(require_admin)],
)
def admin_session_detail(session_id: str):
    session = _require_session(session_id)
    return {
        "session_id": session.session_id,
        "buyer_id": session.buyer_id,
        "human_mode": session.human_mode,
        "pending_action": (
            session.pending_action.name if session.pending_action else None
        ),
        "messages": session.public_messages(),
        "traces": session.public_traces(),
    }


@app.post(
    "/api/admin/sessions/{session_id}/takeover",
    dependencies=[Depends(require_admin)],
)
def admin_takeover(session_id: str, req: TakeoverRequest):
    session = _require_session(session_id)
    session.set_human_mode(req.enabled)
    session.add_system(
        "人工客服已接管会话。" if req.enabled else "人工客服已结束接管，机器人恢复服务。"
    )
    return {
        "ok": True,
        "session_id": session.session_id,
        "human_mode": session.human_mode,
    }


@app.post(
    "/api/admin/sessions/{session_id}/reply",
    dependencies=[Depends(require_admin)],
)
def admin_reply(session_id: str, req: AdminReplyRequest):
    session = _require_session(session_id)
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空")
    session.set_human_mode(True)
    session.add_assistant(message, source="human")
    return {
        "ok": True,
        "session_id": session.session_id,
        "human_mode": session.human_mode,
    }


@app.get("/api/chat/messages")
def chat_messages(
    session_id: str,
    after_id: int = 0,
    authorization: str | None = Header(default=None),
):
    _validate_session_id(session_id)
    buyer_id = _buyer_from_authorization(authorization)
    session = get_existing_session(session_id)
    if session is None:
        return {"human_mode": False, "messages": []}
    _check_session_buyer(session, buyer_id)
    return {
        "human_mode": session.human_mode,
        "messages": session.public_messages(
            after_id=max(after_id, 0), human_only=True
        ),
    }


@app.get("/api/demo/buyers")
def demo_buyers():
    return {
        "buyers": [
            {
                "buyer_id": buyer["buyer_id"],
                "nickname": buyer["nickname"],
                "member_level": buyer["member_level"],
                "city": buyer["city"],
                "order_count": buyer["order_count"],
                "login_phone": order_service.buyer_login_phone(buyer),
            }
            for buyer in order_service.list_buyers()
        ]
    }


@app.get("/api/tools/products")
def product_list():
    return {"products": list(PRODUCTS.values())}


@app.get("/api/tools/products/{product_id}")
def product_detail(product_id: str):
    return get_product(product_id=product_id)


@app.get("/", include_in_schema=False)
def read_root():
    return RedirectResponse("/web/")


if WEB_DIR.is_dir():
    app.mount("/web", StaticFiles(directory=WEB_DIR, html=True), name="web")


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "llm": "configured" if settings.llm_configured else "mock",
        "tools": (settings.tool_backend or "local").strip().lower(),
    }
