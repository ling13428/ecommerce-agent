import time

from agent.session import SessionState
from services.dashboard import build_dashboard


def _trace(
    status,
    *,
    first_response_ms=None,
    route=None,
    handoff_reason=None,
    started_at=None,
):
    return {
        "status": status,
        "first_response_ms": first_response_ms,
        "route": route,
        "handoff_reason": handoff_reason,
        "started_at": started_at if started_at is not None else time.time(),
    }


def _session(session_id, *, updated_at, traces, messages=2):
    session = SessionState(session_id=session_id)
    session.updated_at = updated_at
    session.traces = traces
    session.messages = [
        {"id": index, "role": "user" if index % 2 else "assistant", "content": "x"}
        for index in range(1, messages + 1)
    ]
    return session


def test_dashboard_aggregates_rates_and_latency():
    now = time.time()
    sessions = [
        _session(
            "s1",
            updated_at=now,
            traces=[
                _trace("ok", first_response_ms=100, route="product"),
                _trace(
                    "handoff",
                    first_response_ms=200,
                    route="handoff",
                    handoff_reason="user_requested_human",
                ),
            ],
        ),
        _session(
            "s2",
            updated_at=now - 8 * 24 * 3600,
            traces=[_trace("ok", first_response_ms=999, started_at=now - 8 * 24 * 3600)],
        ),
    ]

    report = build_dashboard(sessions, days=7, now=now)

    assert report["totals"]["sessions"] == 1
    assert report["totals"]["traces"] == 2
    assert report["totals"]["messages"] == 2
    assert report["rates"]["resolution"] == 0.5
    assert report["rates"]["handoff"] == 0.5
    assert report["latency"]["first_response_avg_ms"] == 150.0
    assert report["latency"]["first_response_p95_ms"] == 200.0
    assert report["routes"] == [
        {"route": "product", "count": 1},
        {"route": "handoff", "count": 1},
    ]
    assert report["handoff_reasons"] == [
        {"reason": "user_requested_human", "count": 1}
    ]


def test_dashboard_empty():
    report = build_dashboard([], days=7, now=time.time())

    assert report["totals"] == {"sessions": 0, "traces": 0, "messages": 0}
    assert report["rates"]["resolution"] == 0.0
    assert report["latency"]["first_response_count"] == 0
    assert report["routes"] == []
    assert report["handoff_reasons"] == []
