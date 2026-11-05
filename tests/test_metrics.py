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
