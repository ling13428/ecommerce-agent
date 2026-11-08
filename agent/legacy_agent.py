from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, cast

from openai import AsyncOpenAI

from agent.agent_utils import (
    LLMTimeoutError,
    record_llm_failure,
    record_llm_success,
    resolve_llm,
)
from agent.agent_utils import (
    accumulate_tool_calls as _accumulate_tool_calls,
)
from agent.agent_utils import (
    handoff_message as _handoff_message,
)
from agent.agent_utils import (
    latest_user_message as _latest_user_message,
)
from agent.agent_utils import (
    mentions_handoff as _mentions_handoff,
)
from agent.agent_utils import (
    parse_arguments as _parse_arguments,
)
from agent.agent_utils import (
    session_summary as _session_summary,
)
from agent.agent_utils import (
    tool_detail as _tool_detail,
)
from agent.router import RouteResult, prompt_for_route
from agent.session import SessionState
from core.config import get_settings
from core.idempotency import business_idempotency_key
from core.security import SYSTEM_PROMPT, wrap_tool_result
from tools.context import ToolContext
from tools.products import detect_product_id
from tools.registry import execute_tool_async, openai_tools


async def run_legacy_agent(
    session: SessionState,
    client: AsyncOpenAI | None = None,
    route: RouteResult | None = None,
) -> AsyncIterator[dict[str, Any]]:
    settings = get_settings()
    if client is None:
        client, model = resolve_llm()
    else:
        model = settings.llm_model

    system_prompt = SYSTEM_PROMPT
    if route is not None:
        system_prompt = f"{SYSTEM_PROMPT}\n\n{prompt_for_route(route)}"

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        *session.snapshot(),
    ]
    reply_parts: list[str] = []

    allowed_tools = route.allowed_tools if route is not None else None
    tool_specs = openai_tools(allowed=allowed_tools)
    tool_kwargs = (
        {"tools": tool_specs, "tool_choice": "auto"} if tool_specs else {}
    )

    for step in range(settings.llm_max_steps):
        tool_calls: dict[int, dict[str, str]] = {}
        turn_text_parts: list[str] = []

        try:
            async with asyncio.timeout(settings.llm_timeout):
                completions = cast(Any, client.chat.completions)
                stream = await completions.create(
                    model=model,
                    messages=messages,
                    stream=True,
                    temperature=settings.llm_temperature,
                    max_tokens=settings.llm_max_tokens,
                    **tool_kwargs,
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
            record_llm_failure()
            raise LLMTimeoutError("模型响应超时") from exc
        except Exception:
            record_llm_failure()
            raise
        else:
            record_llm_success()

        yield {
            "type": "llm_step",
            "step": step + 1,
            "tool_call_count": len(tool_calls),
            "has_text": bool(turn_text_parts),
        }

        if not tool_calls:
            if not turn_text_parts:
                message = "抱歉，我没能生成有效回复，已为你转接人工客服。"
                yield {"type": "delta", "content": message}
                reply_parts.append(message)
                await session.add_assistant_async("".join(reply_parts))
                yield {
                    "type": "handoff",
                    "reason": "empty_response",
                    "summary": _session_summary(session),
                }
            else:
                await session.add_assistant_async("".join(reply_parts))
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

            if (
                not parse_error
                and name == "search_knowledge"
                and not arguments.get("product_id")
            ):
                product_id = detect_product_id(_latest_user_message(session))
                if product_id:
                    arguments["product_id"] = product_id

            if parse_error:
                result: dict[str, Any] = {"ok": False, "error": parse_error}
            else:
                result = await execute_tool_async(
                    name,
                    arguments,
                    confirmed=False,
                    context=ToolContext(
                        buyer_id=session.buyer_id,
                        session_id=session.session_id,
                    ),
                )

            yield {
                "type": "tool_call",
                "name": name,
                "args": arguments,
                "ok": bool(result.get("ok")),
                "step": step + 1,
                "detail": _tool_detail(name, result),
            }

            if result.get("status") == "confirm_required":
                summary = str(result.get("message", "该操作需要确认"))
                message = (
                    f"这个操作需要你确认：{summary}\n"
                    "如果确认，请直接回复“确认”；如果不需要，请回复“取消”。"
                )
                pending_args = result.get("args") or arguments
                await session.set_pending_async(
                    name,
                    pending_args,
                    summary,
                    idempotency_key=business_idempotency_key(
                        name, pending_args, session.buyer_id
                    ),
                )
                yield {"type": "delta", "content": message}
                yield {
                    "type": "confirm_required",
                    "name": name,
                    "args": arguments,
                    "summary": summary,
                }
                reply_parts.append(message)
                await session.add_assistant_async("".join(reply_parts))
                return

            if result.get("status") == "handoff":
                reason = str(result.get("reason", "用户需要人工"))
                summary = str(result.get("summary", ""))
                if not _mentions_handoff("".join(turn_text_parts)):
                    message = _handoff_message(reason, summary)
                    yield {"type": "delta", "content": message}
                    reply_parts.append(message)
                yield {
                    "type": "handoff",
                    "reason": reason,
                    "summary": summary,
                }
                await session.add_assistant_async("".join(reply_parts))
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
    await session.add_assistant_async("".join(reply_parts))
    yield {
        "type": "handoff",
        "reason": "max_steps_exceeded",
        "summary": _session_summary(session),
    }
