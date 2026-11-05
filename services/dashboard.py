from __future__ import annotations

import time
from collections import Counter
from typing import Any

from agent.session import SessionState


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(ratio * (len(ordered) - 1))))
    return float(ordered[index])


def build_dashboard(
    sessions: list[SessionState],
    *,
    days: int = 7,
    now: float | None = None,
) -> dict[str, Any]:
    now = now if now is not None else time.time()
    cutoff = now - days * 24 * 3600

    sessions_in_window = [
        session
        for session in sessions
        if (session.updated_at or 0) >= cutoff
    ]
    traces: list[dict[str, Any]] = []
    for session in sessions_in_window:
        for trace in session.traces:
            if float(trace.get("started_at") or 0) >= cutoff:
                traces.append(trace)

    total_traces = len(traces)
    statuses = Counter(str(trace.get("status") or "unknown") for trace in traces)

    resolved = statuses.get("ok", 0)
    handoff = statuses.get("handoff", 0)
    errors = statuses.get("error", 0)
    fallback = statuses.get("fallback", 0)

    first_responses = [
        float(trace["first_response_ms"])
        for trace in traces
        if trace.get("first_response_ms") is not None
    ]
    routes = Counter(
        str(trace.get("route"))
        for trace in traces
        if trace.get("route")
    )
    handoff_reasons = Counter(
        str(trace.get("handoff_reason"))
        for trace in traces
        if trace.get("handoff_reason")
    )

    messages = sum(
        len(
            [
                message
                for message in session.messages
                if message.get("role") in {"user", "assistant"}
            ]
        )
        for session in sessions_in_window
    )

    def ratio(value: int) -> float:
        return round(value / total_traces, 3) if total_traces else 0.0

    return {
        "window_days": days,
        "generated_at": now,
        "totals": {
            "sessions": len(sessions_in_window),
            "traces": total_traces,
            "messages": messages,
        },
        "rates": {
            "resolution": ratio(resolved),
            "handoff": ratio(handoff),
            "error": ratio(errors),
            "fallback": ratio(fallback),
        },
        "latency": {
            "first_response_avg_ms": round(
                sum(first_responses) / len(first_responses), 1
            )
            if first_responses
            else 0.0,
            "first_response_p95_ms": round(
                _percentile(first_responses, 0.95), 1
            ),
            "first_response_count": len(first_responses),
        },
        "routes": [
            {"route": route, "count": count}
            for route, count in routes.most_common()
        ],
        "handoff_reasons": [
            {"reason": reason, "count": count}
            for reason, count in handoff_reasons.most_common()
        ],
        "statuses": dict(statuses),
    }
