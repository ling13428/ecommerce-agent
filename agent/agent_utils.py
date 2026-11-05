from __future__ import annotations

import json
import threading
import time
from functools import lru_cache
from typing import Any

from openai import AsyncOpenAI

from agent.session import SessionState
from core.alerts import send_alert
from core.config import get_settings


class LLMTimeoutError(RuntimeError):
    pass


@lru_cache
def get_llm_client() -> AsyncOpenAI:
    settings = get_settings()
    api_key = settings.llm_api_key
    if not settings.llm_configured or api_key is None:
        raise RuntimeError("LLM_API_KEY 未配置")
    return AsyncOpenAI(
        api_key=api_key.get_secret_value(),
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout,
        max_retries=2,
    )


@lru_cache
def get_fallback_client() -> AsyncOpenAI:
    settings = get_settings()
    key = settings.llm_fallback_api_key
    if key is None or not key.get_secret_value().strip():
        raise RuntimeError("LLM_FALLBACK_API_KEY 未配置")
    return AsyncOpenAI(
        api_key=key.get_secret_value(),
        base_url=settings.llm_fallback_base_url or settings.llm_base_url,
        timeout=settings.llm_timeout,
        max_retries=2,
    )


_breaker_lock = threading.Lock()
_breaker_failures = 0
_breaker_open_until = 0.0


def reset_breaker() -> None:
    global _breaker_failures, _breaker_open_until
    with _breaker_lock:
        _breaker_failures = 0
        _breaker_open_until = 0.0


def breaker_open() -> bool:
    with _breaker_lock:
        return _breaker_open_until > time.time()


def record_llm_failure() -> None:
    global _breaker_failures, _breaker_open_until
    settings = get_settings()
    opened = False
    with _breaker_lock:
        _breaker_failures += 1
        if (
            _breaker_failures >= settings.llm_circuit_failures
            and _breaker_open_until <= time.time()
        ):
            _breaker_open_until = time.time() + settings.llm_circuit_cooldown
            _breaker_failures = 0
            opened = True
    if opened:
        send_alert(
            "llm_circuit_open",
            "主模型连续失败，已切换备用/降级",
            cooldown=settings.llm_circuit_cooldown,
        )


def record_llm_success() -> None:
    global _breaker_failures, _breaker_open_until
    with _breaker_lock:
        _breaker_failures = 0
        _breaker_open_until = 0.0


def resolve_llm() -> tuple[AsyncOpenAI, str]:
    settings = get_settings()
    if breaker_open() and settings.llm_fallback_configured:
        try:
            return (
                get_fallback_client(),
                settings.llm_fallback_model or settings.llm_model,
            )
        except Exception:
            pass
    return get_llm_client(), settings.llm_model


def accumulate_tool_calls(
    tool_calls: dict[int, dict[str, str]], delta_tool_calls: Any
) -> None:
    for tool_call in delta_tool_calls or []:
        index = getattr(tool_call, "index", 0) or 0
        entry = tool_calls.setdefault(
            index, {"id": "", "name": "", "arguments": ""}
        )
        if getattr(tool_call, "id", None):
            entry["id"] = tool_call.id
        function = getattr(tool_call, "function", None)
        if function is None:
            continue
        if getattr(function, "name", None):
            entry["name"] = function.name
        if getattr(function, "arguments", None):
            entry["arguments"] += function.arguments


def parse_arguments(raw: str) -> tuple[dict[str, Any], str | None]:
    if not raw.strip():
        return {}, None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}, "模型生成的工具参数不是合法 JSON"
    if not isinstance(value, dict):
        return {}, "工具参数必须是 JSON 对象"
    return value, None


def truncate(value: Any, limit: int = 2000) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit else f"{text[:limit]}…"


def rag_detail(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "rag",
        "query": payload.get("query"),
        "product_id": payload.get("product_id"),
        "abstained": bool(payload.get("abstained")),
        "top_score": payload.get("top_score"),
        "reason": payload.get("reason"),
        "hits": [
            {
                "doc_id": hit.get("doc_id"),
                "parent_id": hit.get("parent_id"),
                "title": hit.get("title"),
                "section": hit.get("section"),
                "source": hit.get("source"),
                "score": hit.get("score"),
                "fusion_score": hit.get("fusion_score"),
                "rerank_score": hit.get("rerank_score"),
                "deprecated": bool(hit.get("deprecated", False)),
                "version": hit.get("version"),
                "effective_date": hit.get("effective_date"),
                "valid_until": hit.get("valid_until"),
                "content": truncate(hit.get("content")),
            }
            for hit in (payload.get("results") or [])
            if isinstance(hit, dict)
        ],
    }


def tool_detail(name: str, result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"kind": "unknown", "result": truncate(result)}

    if result.get("status") == "confirm_required":
        return {
            "kind": "confirm",
            "summary": result.get("message"),
            "args": result.get("args"),
        }

    if result.get("ok") is False:
        return {
            "kind": "error",
            "error": result.get("error"),
            "error_code": result.get("error_code"),
            "retryable": result.get("retryable"),
            "side_effect_committed": result.get("side_effect_committed"),
            "details": result.get("details"),
        }

    if name == "search_knowledge":
        payload = result.get("result")
        if not isinstance(payload, dict):
            payload = result
        detail = rag_detail(payload)
        if result.get("status") == "handoff":
            detail["rejected"] = True
            detail["handoff_reason"] = result.get("reason")
        return detail

    if result.get("status") == "handoff":
        return {
            "kind": "handoff",
            "reason": result.get("reason"),
            "summary": result.get("summary"),
        }

    if name == "get_product":
        return {"kind": "product", "result": result.get("result", result)}

    return {"kind": "tool", "result": result.get("result", result)}


def handoff_message(reason: str, summary: str) -> str:
    detail = f"\n已记录的问题摘要：{summary}" if summary else ""
    return f"好的，正在为你转接人工客服，请稍候。{detail}\n（原因：{reason}）"


HANDOFF_HINTS = ("转人工", "转接", "人工客服", "人工坐席")


def mentions_handoff(text: str) -> bool:
    return any(hint in text for hint in HANDOFF_HINTS)


def session_summary(session: SessionState) -> str:
    for message in reversed(session.snapshot()):
        if message.get("role") == "user":
            content = str(message.get("content", ""))
            return content[:200]
    return "用户需要人工协助。"


def latest_user_message(session: SessionState) -> str:
    for message in reversed(session.snapshot()):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    return ""
