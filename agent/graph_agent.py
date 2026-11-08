from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, AsyncIterator, TypedDict, cast
from uuid import uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from openai import AsyncOpenAI

from agent.agent_utils import (
    LLMTimeoutError,
    accumulate_tool_calls,
    handoff_message,
    latest_user_message,
    mentions_handoff,
    parse_arguments,
    record_llm_failure,
    record_llm_success,
    resolve_llm,
    session_summary,
    tool_detail,
)
from agent.checkpoint import get_checkpointer
from agent.router import RouteResult, prompt_for_route
from agent.session import SessionState
from core.config import get_settings
from core.idempotency import business_idempotency_key
from core.security import SYSTEM_PROMPT, wrap_tool_result
from tools.context import ToolContext
from tools.products import detect_product_id
from tools.registry import execute_tool_async, openai_tools


class NoPendingInterrupt(RuntimeError):
    pass


class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    step: int
    stop: str | None
    reason: str
    summary: str
    pending_name: str
    pending_args: dict[str, Any]
    pending_summary: str
    pending_call_id: str
    pending_idempotency_key: str
    decision: bool
    last_turn_text: str


@dataclass
class RunContext:
    session: SessionState
    client: AsyncOpenAI
    model: str
    route: RouteResult | None
    reply_parts: list[str]
    tool_specs: list[dict[str, Any]]


_RUN_CONTEXT: ContextVar[RunContext | None] = ContextVar(
    "agent_run_context", default=None
)


def _run_context() -> RunContext:
    context = _RUN_CONTEXT.get()
    if context is None:
        raise RuntimeError("agent run context is not set")
    return context


def _tool_context() -> ToolContext:
    session = _run_context().session
    return ToolContext(
        buyer_id=session.buyer_id,
        session_id=session.session_id,
    )


def _assistant_tool_calls(
    tool_calls: dict[int, dict[str, str]], step: int
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index in sorted(tool_calls):
        entry = tool_calls[index]
        result.append(
            {
                "id": entry["id"] or f"call_{step}_{index}",
                "type": "function",
                "function": {
                    "name": entry["name"],
                    "arguments": entry["arguments"] or "{}",
                },
            }
        )
    return result


def _thread_config(session: SessionState) -> dict[str, Any]:
    return {"configurable": {"thread_id": session.session_id}}


def _build_graph(checkpointer: BaseCheckpointSaver):
    settings = get_settings()

    async def agent_node(state: AgentState) -> dict[str, Any]:
        context = _run_context()
        writer = get_stream_writer()
        tool_calls: dict[int, dict[str, str]] = {}
        turn_text_parts: list[str] = []
        tool_kwargs = (
            {"tools": context.tool_specs, "tool_choice": "auto"}
            if context.tool_specs
            else {}
        )

        try:
            async with asyncio.timeout(settings.llm_timeout):
                completions = cast(Any, context.client.chat.completions)
                stream = await completions.create(
                    model=context.model,
                    messages=state["messages"],
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
                        context.reply_parts.append(content)
                        writer({"type": "delta", "content": content})
                    accumulate_tool_calls(
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

        step = int(state.get("step", 0)) + 1
        writer(
            {
                "type": "llm_step",
                "step": step,
                "tool_call_count": len(tool_calls),
                "has_text": bool(turn_text_parts),
            }
        )

        calls = _assistant_tool_calls(tool_calls, step)
        messages = list(state["messages"])
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(turn_text_parts) or None,
        }
        if calls:
            assistant_message["tool_calls"] = calls
        messages.append(assistant_message)

        stop = None
        if not calls and not turn_text_parts:
            stop = "empty"

        return {
            "messages": messages,
            "step": step,
            "stop": stop,
            "last_turn_text": "".join(turn_text_parts),
        }

    async def tools_node(state: AgentState) -> dict[str, Any]:
        context = _run_context()
        session = context.session
        writer = get_stream_writer()
        last = state["messages"][-1]
        calls = last.get("tool_calls") or []

        prepared: list[tuple[dict[str, Any], str, dict[str, Any], str | None]] = []
        for call in calls:
            function = call.get("function") or {}
            name = function.get("name") or ""
            arguments, parse_error = parse_arguments(
                function.get("arguments") or ""
            )
            if (
                not parse_error
                and name == "search_knowledge"
                and not arguments.get("product_id")
            ):
                product_id = detect_product_id(latest_user_message(session))
                if product_id:
                    arguments["product_id"] = product_id
            prepared.append((call, name, arguments, parse_error))

        async def run_one(
            entry: tuple[dict[str, Any], str, dict[str, Any], str | None]
        ) -> dict[str, Any]:
            _, name, arguments, parse_error = entry
            if parse_error:
                return {"ok": False, "error": parse_error}
            return await execute_tool_async(
                name,
                arguments,
                confirmed=False,
                context=_tool_context(),
            )

        results = await asyncio.gather(*(run_one(item) for item in prepared))

        for (call, name, arguments, _), result in zip(prepared, results):
            writer(
                {
                    "type": "tool_call",
                    "name": name,
                    "args": arguments,
                    "ok": bool(result.get("ok")),
                    "step": state.get("step", 1),
                    "detail": tool_detail(name, result),
                }
            )

        messages = list(state["messages"])
        stop = None
        reason = ""
        summary = ""
        pending_name = ""
        pending_args: dict[str, Any] = {}
        pending_summary = ""
        pending_call_id = ""
        pending_idempotency_key = ""

        for (call, name, arguments, _), result in zip(prepared, results):
            status = result.get("status")
            if status == "confirm_required":
                stop = "confirm"
                pending_name = name
                pending_args = result.get("args") or arguments
                pending_summary = str(
                    result.get("message", "该操作需要确认")
                )
                pending_call_id = call.get("id") or ""
                message = (
                    f"这个操作需要你确认：{pending_summary}\n"
                    "如果确认，请直接回复“确认”；如果不需要，请回复“取消”。"
                )
                writer({"type": "delta", "content": message})
                context.reply_parts.append(message)
                writer(
                    {
                        "type": "confirm_required",
                        "name": name,
                        "args": pending_args,
                        "summary": pending_summary,
                    }
                )
                await session.set_pending_async(
                    name,
                    pending_args,
                    pending_summary,
                    idempotency_key=business_idempotency_key(
                        name, pending_args, session.buyer_id
                    ),
                )
                if session.pending_action is not None:
                    pending_idempotency_key = (
                        session.pending_action.idempotency_key
                    )
                await session.add_assistant_async(
                    "".join(context.reply_parts)
                )
                break
            if status == "handoff":
                stop = "handoff"
                reason = str(result.get("reason", "用户需要人工"))
                summary = str(result.get("summary", ""))
                break
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id") or "",
                    "content": wrap_tool_result(name, result),
                }
            )

        return {
            "messages": messages,
            "stop": stop,
            "reason": reason,
            "summary": summary,
            "pending_name": pending_name,
            "pending_args": pending_args,
            "pending_summary": pending_summary,
            "pending_call_id": pending_call_id,
            "pending_idempotency_key": pending_idempotency_key,
        }

    async def confirm_node(state: AgentState) -> dict[str, Any]:
        decision = interrupt(
            {
                "type": "confirm_required",
                "name": state.get("pending_name"),
                "args": state.get("pending_args"),
                "summary": state.get("pending_summary"),
            }
        )
        if isinstance(decision, dict):
            approved = bool(decision.get("approved"))
            key = str(decision.get("idempotency_key") or "")
        else:
            approved = bool(decision)
            key = ""
        return {
            "decision": approved,
            "pending_idempotency_key": (
                key or str(state.get("pending_idempotency_key") or "")
            ),
        }

    async def write_node(state: AgentState) -> dict[str, Any]:
        context = _run_context()
        session = context.session
        writer = get_stream_writer()
        name = str(state.get("pending_name") or "")
        arguments = dict(state.get("pending_args") or {})
        call_id = str(state.get("pending_call_id") or "")
        idempotency_key = str(state.get("pending_idempotency_key") or "")
        if not idempotency_key and session.pending_action is not None:
            idempotency_key = session.pending_action.idempotency_key
        if not idempotency_key:
            idempotency_key = uuid4().hex

        result = await execute_tool_async(
            name,
            arguments,
            confirmed=True,
            idempotency_key=idempotency_key,
            context=_tool_context(),
        )

        writer(
            {
                "type": "tool_call",
                "name": name,
                "args": arguments,
                "ok": bool(result.get("ok")),
                "confirmed": True,
                "step": state.get("step", 1),
                "detail": {"kind": "write", "result": result},
            }
        )

        messages = list(state["messages"])
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": wrap_tool_result(name, result),
            }
        )
        messages.append(
            {
                "role": "system",
                "content": (
                    f"用户已明确确认执行写操作 {name}，该操作已处理，"
                    "不要重复调用同一工具。"
                ),
            }
        )
        await session.clear_pending_async()
        return {"messages": messages, "stop": None}

    async def cancelled_node(state: AgentState) -> dict[str, Any]:
        context = _run_context()
        session = context.session
        writer = get_stream_writer()
        name = str(state.get("pending_name") or "")
        call_id = str(state.get("pending_call_id") or "")
        writer(
            {
                "type": "confirmation_cancelled",
                "name": name,
                "reason": "用户取消",
            }
        )
        messages = list(state["messages"])
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": "用户拒绝执行该操作，未做任何变更。",
            }
        )
        await session.clear_pending_async()
        return {"messages": messages, "stop": None}

    async def handoff_node(state: AgentState) -> dict[str, Any]:
        context = _run_context()
        writer = get_stream_writer()
        reason = str(state.get("reason") or "用户需要人工")
        summary = str(state.get("summary") or "")
        if not mentions_handoff(str(state.get("last_turn_text") or "")):
            message = handoff_message(reason, summary)
            writer({"type": "delta", "content": message})
            context.reply_parts.append(message)
        writer({"type": "handoff", "reason": reason, "summary": summary})
        await context.session.add_assistant_async(
            "".join(context.reply_parts)
        )
        return {}

    async def empty_node(state: AgentState) -> dict[str, Any]:
        context = _run_context()
        writer = get_stream_writer()
        message = "抱歉，我没能生成有效回复，已为你转接人工客服。"
        writer({"type": "delta", "content": message})
        context.reply_parts.append(message)
        await context.session.add_assistant_async(
            "".join(context.reply_parts)
        )
        writer(
            {
                "type": "handoff",
                "reason": "empty_response",
                "summary": session_summary(context.session),
            }
        )
        return {}

    async def max_steps_node(state: AgentState) -> dict[str, Any]:
        context = _run_context()
        writer = get_stream_writer()
        message = "这个问题需要人工客服进一步处理，正在为你转接，请稍候。"
        writer({"type": "delta", "content": message})
        context.reply_parts.append(message)
        await context.session.add_assistant_async(
            "".join(context.reply_parts)
        )
        writer(
            {
                "type": "handoff",
                "reason": "max_steps_exceeded",
                "summary": session_summary(context.session),
            }
        )
        return {}

    async def finish_node(state: AgentState) -> dict[str, Any]:
        context = _run_context()
        await context.session.add_assistant_async(
            "".join(context.reply_parts)
        )
        return {}

    def route_after_agent(state: AgentState) -> str:
        if state.get("stop") == "empty":
            return "empty"
        last = state["messages"][-1]
        if last.get("tool_calls"):
            return "tools"
        return "finish"

    def route_after_tools(state: AgentState) -> str:
        stop = state.get("stop")
        if stop in {"confirm", "handoff"}:
            return stop
        if int(state.get("step", 0)) >= settings.llm_max_steps:
            return "max_steps"
        return "agent"

    def route_after_confirm(state: AgentState) -> str:
        return "write" if state.get("decision") else "cancelled"

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("confirm", confirm_node)
    graph.add_node("write", write_node)
    graph.add_node("cancelled", cancelled_node)
    graph.add_node("handoff", handoff_node)
    graph.add_node("empty", empty_node)
    graph.add_node("max_steps", max_steps_node)
    graph.add_node("finish", finish_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        route_after_agent,
        {"tools": "tools", "finish": "finish", "empty": "empty"},
    )
    graph.add_conditional_edges(
        "tools",
        route_after_tools,
        {
            "agent": "agent",
            "confirm": "confirm",
            "handoff": "handoff",
            "max_steps": "max_steps",
        },
    )
    graph.add_conditional_edges(
        "confirm",
        route_after_confirm,
        {"write": "write", "cancelled": "cancelled"},
    )
    graph.add_edge("write", "agent")
    graph.add_edge("cancelled", "agent")
    for terminal in ("handoff", "empty", "max_steps", "finish"):
        graph.add_edge(terminal, END)

    return graph.compile(checkpointer=checkpointer)


_COMPILED: dict[tuple[int, int], Any] = {}


def _compiled_graph(checkpointer: BaseCheckpointSaver) -> Any:
    loop_id = id(asyncio.get_running_loop())
    key = (loop_id, id(checkpointer))
    graph = _COMPILED.get(key)
    if graph is None:
        graph = _build_graph(checkpointer)
        _COMPILED[key] = graph
    return graph


def _initial_state(
    session: SessionState, system_prompt: str
) -> AgentState:
    return {
        "messages": [
            {"role": "system", "content": system_prompt},
            *session.snapshot(),
        ],
        "step": 0,
        "stop": None,
        "reason": "",
        "summary": "",
        "pending_name": "",
        "pending_args": {},
        "pending_summary": "",
        "pending_call_id": "",
        "pending_idempotency_key": "",
        "decision": False,
        "last_turn_text": "",
    }


async def run_graph_agent(
    session: SessionState,
    client: AsyncOpenAI | None = None,
    route: RouteResult | None = None,
) -> AsyncIterator[dict[str, Any]]:
    if client is None:
        client, model = resolve_llm()
    else:
        model = get_settings().llm_model

    system_prompt = SYSTEM_PROMPT
    if route is not None:
        system_prompt = f"{SYSTEM_PROMPT}\n\n{prompt_for_route(route)}"

    allowed_tools = route.allowed_tools if route is not None else None
    reply_parts: list[str] = []
    checkpointer = await get_checkpointer()
    graph = _compiled_graph(checkpointer)
    config = _thread_config(session)

    token = _RUN_CONTEXT.set(
        RunContext(
            session=session,
            client=client,
            model=model,
            route=route,
            reply_parts=reply_parts,
            tool_specs=openai_tools(allowed=allowed_tools),
        )
    )
    try:
        snapshot = await graph.aget_state(config)
        if snapshot.next:
            await checkpointer.adelete_thread(session.session_id)

        async for event in graph.astream(
            _initial_state(session, system_prompt),
            config=config,
            stream_mode="custom",
        ):
            yield event
    finally:
        _RUN_CONTEXT.reset(token)


async def run_graph_agent_resume(
    session: SessionState,
    approved: bool,
    client: AsyncOpenAI | None = None,
    idempotency_key: str | None = None,
    route: RouteResult | None = None,
) -> AsyncIterator[dict[str, Any]]:
    if client is None:
        client, model = resolve_llm()
    else:
        model = get_settings().llm_model
    reply_parts: list[str] = []
    checkpointer = await get_checkpointer()
    graph = _compiled_graph(checkpointer)
    config = _thread_config(session)

    allowed_tools = route.allowed_tools if route is not None else None
    token = _RUN_CONTEXT.set(
        RunContext(
            session=session,
            client=client,
            model=model,
            route=route,
            reply_parts=reply_parts,
            tool_specs=openai_tools(allowed=allowed_tools),
        )
    )
    try:
        snapshot = await graph.aget_state(config)
        if not snapshot.next:
            raise NoPendingInterrupt(
                f"会话 {session.session_id} 没有可恢复的中断"
            )

        resume_value = {
            "approved": approved,
            "idempotency_key": idempotency_key or "",
        }
        async for event in graph.astream(
            Command(resume=resume_value),
            config=config,
            stream_mode="custom",
        ):
            yield event
    finally:
        _RUN_CONTEXT.reset(token)
