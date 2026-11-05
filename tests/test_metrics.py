import json
import logging

from core.logging import JsonFormatter
from core.metrics import Metrics


def test_metrics_snapshot_counts_and_latency():
    metrics = Metrics()
    metrics.observe_request(200, 10)
    metrics.observe_request(500, 30)
    metrics.incr("tool_calls_total")

    snapshot = metrics.snapshot()

    assert snapshot["counters"]["requests_total"] == 2
    assert snapshot["counters"]["responses_2xx"] == 1
    assert snapshot["counters"]["responses_5xx"] == 1
    assert snapshot["counters"]["errors_total"] == 1
    assert snapshot["counters"]["tool_calls_total"] == 1
    assert snapshot["latency_ms"] == {"count": 2, "avg": 20.0, "max": 30.0}


def test_metrics_tracks_per_tool_outcomes_and_latency():
    metrics = Metrics()
    metrics.observe_tool("get_order", 10, "ok")
    metrics.observe_tool("get_order", 30, "timeout", "tool_timeout")
    metrics.observe_tool("get_order", 5, "blocked")
    metrics.incr("tool_retry_total")

    snapshot = metrics.snapshot()
    entry = snapshot["tools"]["get_order"]

    assert entry["calls"] == 3
    assert entry["ok"] == 1
    assert entry["errors"] == 1
    assert entry["timeouts"] == 1
    assert entry["blocked"] == 1
    assert entry["latency_ms"] == {"count": 3, "avg": 15.0, "max": 30.0}
    assert entry["error_codes"] == {"tool_timeout": 1}
    assert snapshot["counters"]["tool_exec_total"] == 3
    assert snapshot["counters"]["tool_ok_total"] == 1
    assert snapshot["counters"]["tool_error_total"] == 1
    assert snapshot["counters"]["tool_timeout_total"] == 1
    assert snapshot["counters"]["tool_blocked_total"] == 1
    assert snapshot["counters"]["tool_retry_total"] == 1


def test_json_formatter_redacts_secret():
    record = logging.LogRecord(
        "ecommerce_agent.test",
        logging.ERROR,
        __file__,
        1,
        "请求失败 api_key=sk-abcdef123456",
        None,
        None,
    )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "ERROR"
    assert payload["logger"] == "ecommerce_agent.test"
    assert "sk-abcdef123456" not in payload["message"]
    assert "***" in payload["message"]
