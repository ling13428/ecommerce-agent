import asyncio
import time

from pydantic import BaseModel

from core.config import get_settings
from tools.registry import (
    ToolSpec,
    execute_tool,
    execute_tool_async,
    register_tool,
    unregister_tool,
)


class ReadArgs(BaseModel):
    key: str = "x"


class WriteArgs(BaseModel):
    order_id: str


class StrictResult(BaseModel):
    value: int


def _run(coro):
    return asyncio.run(coro)


def _env(monkeypatch, **values):
    for name, value in values.items():
        monkeypatch.setenv(name, str(value))
    get_settings.cache_clear()


def _cleanup():
    get_settings.cache_clear()


def test_typed_errors_and_confirmation(monkeypatch):
    register_tool(
        ToolSpec(
            name="_runtime_write",
            description="test",
            args_model=WriteArgs,
            func=lambda order_id: {"cancelled": order_id},
            kind="write",
        )
    )
    try:
        unknown = execute_tool("no_such_tool", {})
        assert unknown["error_code"] == "unknown_tool"
        assert unknown["retryable"] is False

        invalid = execute_tool("_runtime_write", {})
        assert invalid["error_code"] == "invalid_arguments"
        assert invalid["retryable"] is True

        confirm = execute_tool("_runtime_write", {"order_id": "A1"})
        assert confirm["status"] == "confirm_required"
        assert confirm["error_code"] == "confirmation_required"
        assert confirm["side_effect_committed"] is False
    finally:
        unregister_tool("_runtime_write")
        _cleanup()


def test_local_read_timeout_is_typed(monkeypatch):
    def slow(key: str):
        time.sleep(0.3)
        return {"key": key}

    register_tool(
        ToolSpec(
            name="_runtime_slow",
            description="test",
            args_model=ReadArgs,
            func=slow,
            timeout=0.05,
            max_attempts=1,
        )
    )
    try:
        _env(
            monkeypatch,
            TOOL_TIMEOUT="0.05",
            TOOL_RETRY_ATTEMPTS="1",
            TOOL_RETRY_BACKOFF="0",
        )
        result = _run(execute_tool_async("_runtime_slow", {"key": "a"}))
        assert result["ok"] is False
        assert result["error_code"] == "tool_timeout"
        assert result["retryable"] is True
        assert result["side_effect_committed"] is False
    finally:
        unregister_tool("_runtime_slow")
        _cleanup()


def test_read_is_retried_but_write_is_not(monkeypatch):
    read_calls = []
    write_calls = []

    def flaky_read(key: str):
        read_calls.append(key)
        if len(read_calls) == 1:
            raise RuntimeError("transient")
        return {"key": key}

    def broken_write(order_id: str):
        write_calls.append(order_id)
        raise RuntimeError("boom")

    read_spec = ToolSpec(
        name="_runtime_flaky_read",
        description="test",
        args_model=ReadArgs,
        func=flaky_read,
        max_attempts=2,
    )
    write_spec = ToolSpec(
        name="_runtime_broken_write",
        description="test",
        args_model=WriteArgs,
        func=broken_write,
        kind="write",
    )
    register_tool(read_spec)
    register_tool(write_spec)
    try:
        _env(
            monkeypatch,
            TOOL_RETRY_ATTEMPTS="2",
            TOOL_RETRY_BACKOFF="0",
        )
        ok = _run(execute_tool_async(read_spec.name, {"key": "a"}))
        assert ok["ok"] is True
        assert len(read_calls) == 2

        failed = execute_tool(
            write_spec.name,
            {"order_id": "A1"},
            confirmed=True,
            idempotency_key="write-key-1",
        )
        assert failed["ok"] is False
        assert failed["error_code"] == "tool_execution_failed"
        assert failed["side_effect_committed"] is None
        assert len(write_calls) == 1
    finally:
        unregister_tool(read_spec.name)
        unregister_tool(write_spec.name)
        _cleanup()


def test_uncertain_write_failure_is_cached(monkeypatch):
    calls = []

    def broken(order_id: str):
        calls.append(order_id)
        raise RuntimeError("boom")

    spec = ToolSpec(
        name="_runtime_uncertain_write",
        description="test",
        args_model=WriteArgs,
        func=broken,
        kind="write",
    )
    register_tool(spec)
    try:
        _env(monkeypatch, TOOL_IDEMPOTENCY_UNCERTAIN_TTL_SECONDS="600")
        first = execute_tool(
            spec.name,
            {"order_id": "A1"},
            confirmed=True,
            idempotency_key="uncertain-key",
        )
        second = execute_tool(
            spec.name,
            {"order_id": "A1"},
            confirmed=True,
            idempotency_key="uncertain-key",
        )
        assert second == first
        assert first["ok"] is False
        assert len(calls) == 1
    finally:
        unregister_tool(spec.name)
        _cleanup()


def test_write_timeout_is_cached_as_uncertain(monkeypatch):
    calls = []

    def slow_write(order_id: str):
        calls.append(order_id)
        time.sleep(0.4)
        return {"cancelled": order_id}

    spec = ToolSpec(
        name="_runtime_slow_write",
        description="test",
        args_model=WriteArgs,
        func=slow_write,
        kind="write",
        timeout=0.05,
    )
    register_tool(spec)
    try:
        _env(monkeypatch, TOOL_IDEMPOTENCY_UNCERTAIN_TTL_SECONDS="600")
        first = execute_tool(
            spec.name,
            {"order_id": "A1"},
            confirmed=True,
            idempotency_key="slow-write-key",
        )
        second = execute_tool(
            spec.name,
            {"order_id": "A1"},
            confirmed=True,
            idempotency_key="slow-write-key",
        )
        assert first["error_code"] == "tool_timeout"
        assert first["side_effect_committed"] is None
        assert second == first
        assert calls == ["A1"]
    finally:
        unregister_tool(spec.name)
        _cleanup()


def test_tool_circuit_opens_after_repeated_failures(monkeypatch):
    calls = []

    def broken(key: str):
        calls.append(key)
        raise RuntimeError("down")

    spec = ToolSpec(
        name="_runtime_circuit",
        description="test",
        args_model=ReadArgs,
        func=broken,
        max_attempts=1,
    )
    register_tool(spec)
    try:
        _env(
            monkeypatch,
            TOOL_RETRY_ATTEMPTS="1",
            TOOL_CIRCUIT_FAILURES="2",
            TOOL_CIRCUIT_COOLDOWN="60",
        )
        first = execute_tool(spec.name, {"key": "a"})
        second = execute_tool(spec.name, {"key": "a"})
        third = execute_tool(spec.name, {"key": "a"})

        assert first["error_code"] == "tool_execution_failed"
        assert second["error_code"] == "tool_execution_failed"
        assert third["error_code"] == "tool_circuit_open"
        assert third["retryable"] is True
        assert len(calls) == 2
    finally:
        unregister_tool(spec.name)
        _cleanup()


def test_large_result_is_truncated(monkeypatch):
    def huge(key: str):
        return {"blob": "x" * 6000, "items": list(range(200))}

    spec = ToolSpec(
        name="_runtime_huge",
        description="test",
        args_model=ReadArgs,
        func=huge,
    )
    register_tool(spec)
    try:
        _env(
            monkeypatch,
            TOOL_RESULT_MAX_CHARS="1000",
            TOOL_RESULT_STRING_MAX_CHARS="200",
            TOOL_RESULT_LIST_MAX_ITEMS="10",
        )
        result = execute_tool(spec.name, {"key": "a"})
        assert result["ok"] is True
        assert result["truncated"] is True
        assert result["original_chars"] > 1000
        assert len(result["result"]["blob"]) < 6000
        assert result["result"]["items"][-1].startswith("…[截断")
    finally:
        unregister_tool(spec.name)
        _cleanup()


def test_output_schema_mismatch_is_reported(monkeypatch):
    def wrong(key: str):
        return {"value": "not-an-int"}

    spec = ToolSpec(
        name="_runtime_schema",
        description="test",
        args_model=ReadArgs,
        func=wrong,
        result_model=StrictResult,
    )
    register_tool(spec)
    try:
        result = execute_tool(spec.name, {"key": "a"})
        assert result["ok"] is False
        assert result["error_code"] == "invalid_result"
        assert result["retryable"] is True
    finally:
        unregister_tool(spec.name)
        _cleanup()
