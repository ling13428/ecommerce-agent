from __future__ import annotations

import asyncio
import json
from functools import lru_cache
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from agent.session import SessionState
from core.config import get_settings
from core.security import SYSTEM_PROMPT, wrap_tool_result
from tools.registry import execute_tool, openai_tools


class LLMTimeoutError(RuntimeError):
    pass


@lru_cache
def get_llm_client() -> AsyncOpenAI:
    settings = get_settings()
    if not settings.llm_configured:
        raise RuntimeError("LLM_API_KEY 未配置")
    return AsyncOpenAI(
        api_key=settings.llm_api_key.get_secret_value(),
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout,
        max_retries=2,
    )


def _accumulate_tool_calls(
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


def _parse_arguments(raw: str) -> tuple[dict[str, Any], str | None]:
    if not raw.strip():
        return {}, None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}, "模型生成的工具参数不是合法 JSON"
    if not isinstance(value, dict):
        return {}, "工具参数必须是 JSON 对象"
    return value, None


def _handoff_message(reason: str, summary: str) -> str:
    detail = f"\n已记录的问题摘要：{summary}" if summary else ""
    return f"好的，正在为你转接人工客服，请稍候。{detail}\n（原因：{reason}）"


def _session_summary(session: SessionState) -> str:
    for message in reversed(session.snapshot()):
        if message.get("role") == "user":
            content = str(message.get("content", ""))
            return content[:200]
    return "用户需要人工协助。"


async def run_llm_agent(
    session: SessionState,
    client: AsyncOpenAI | None = None,
) -> AsyncIterator[dict[str, Any]]:
    settings = get_settings()
    client = client or get_llm_client()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *session.snapshot(),
    ]
    reply_parts: list[str] = []

    for step in range(settings.llm_max_steps):
        tool_calls: dict[int, dict[str, str]] = {}
        turn_text_parts: list[str] = []

        try:
            async with asyncio.timeout(settings.llm_timeout):
                stream = await client.chat.completions.create(
                    model=settings.llm_model,
                    messages=messages,
                    tools=openai_tools(),
                    tool_choice="auto",
                    stream=True,
                    temperature=settings.llm_temperature,
                    max_tokens=settings.llm_max_tokens,
                )
                async for chunk in stream:
                    choices = getattr(chunk, "choices", None)
                    if not choices:
                        continue
                    delta = getattr(choices[0], "delta", None)
                    if delta is None:
                        continue
                    content = getattr(delta, "content", None)
                    if content:
                        turn_text_parts.append(content)
                        reply_parts.append(content)
                        yield {"type": "delta", "content": content}
                    _accumulate_tool_calls(
                        tool_calls, getattr(delta, "tool_calls", None)
                    )
        except TimeoutError as exc:
            raise LLMTimeoutError("模型响应超时") from exc

        if not tool_calls:
            if not turn_text_parts:
                message = "抱歉，我没能生成有效回复，已为你转接人工客服。"
                yield {"type": "delta", "content": message}
                reply_parts.append(message)
                session.add_assistant("".join(reply_parts))
                yield {
                    "type": "handoff",
                    "reason": "empty_response",
                    "summary": _session_summary(session),
                }
            else:
                session.add_assistant("".join(reply_parts))
            return

        assistant_tool_calls = []
        for index in sorted(tool_calls):
            entry = tool_calls[index]
            call_id = entry["id"] or f"call_{step}_{index}"
            assistant_tool_calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": entry["name"],
                        "arguments": entry["arguments"] or "{}",
                    },
                }
            )

        messages.append(
            {
                "role": "assistant",
                "content": "".join(turn_text_parts) or None,
                "tool_calls": assistant_tool_calls,
            }
        )

        for index in sorted(tool_calls):
            entry = tool_calls[index]
            call_id = entry["id"] or f"call_{step}_{index}"
            name = entry["name"]
            arguments, parse_error = _parse_arguments(entry["arguments"])

            if parse_error:
                result: dict[str, Any] = {"ok": False, "error": parse_error}
            else:
                result = execute_tool(name, arguments, confirmed=False)

            yield {
                "type": "tool_call",
                "name": name,
                "args": arguments,
                "ok": bool(result.get("ok")),
            }

            if result.get("status") == "confirm_required":
                summary = str(result.get("message", "该操作需要确认"))
                message = (
                    f"这个操作需要你确认：{summary}\n"
                    "如果确认，请直接回复“确认”；如果不需要，请回复“取消”。"
                )
                session.set_pending(name, arguments, summary)
                yield {"type": "delta", "content": message}
                yield {
                    "type": "confirm_required",
                    "name": name,
                    "args": arguments,
                    "summary": summary,
                }
                reply_parts.append(message)
                session.add_assistant("".join(reply_parts))
                return

            if result.get("status") == "handoff":
                reason = str(result.get("reason", "用户需要人工"))
                summary = str(result.get("summary", ""))
                message = _handoff_message(reason, summary)
                yield {"type": "delta", "content": message}
                yield {
                    "type": "handoff",
                    "reason": reason,
                    "summary": summary,
                }
                reply_parts.append(message)
                session.add_assistant("".join(reply_parts))
                return

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": wrap_tool_result(name, result),
                }
            )

    message = "这个问题需要人工客服进一步处理，正在为你转接，请稍候。"
    yield {"type": "delta", "content": message}
    reply_parts.append(message)
    session.add_assistant("".join(reply_parts))
    yield {
        "type": "handoff",
        "reason": "max_steps_exceeded",
        "summary": _session_summary(session),
    }
