from __future__ import annotations

import threading
import time
from typing import Any


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._duration_count = 0
        self._duration_sum_ms = 0.0
        self._duration_max_ms = 0.0
        self._tools: dict[str, dict[str, Any]] = {}
        self._started_at = time.time()

    def incr(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    def observe_request(self, status_code: int, duration_ms: float) -> None:
        with self._lock:
            self._counters["requests_total"] = (
                self._counters.get("requests_total", 0) + 1
            )
            bucket = f"responses_{status_code // 100}xx"
            self._counters[bucket] = self._counters.get(bucket, 0) + 1
            if status_code >= 500:
                self._counters["errors_total"] = (
                    self._counters.get("errors_total", 0) + 1
                )
            self._duration_count += 1
            self._duration_sum_ms += duration_ms
            self._duration_max_ms = max(self._duration_max_ms, duration_ms)

    def observe_tool(
        self,
        name: str,
        duration_ms: float,
        outcome: str,
        error_code: str = "",
    ) -> None:
        with self._lock:
            entry = self._tools.setdefault(
                name,
                {
                    "calls": 0,
                    "ok": 0,
                    "errors": 0,
                    "blocked": 0,
                    "timeouts": 0,
                    "latency_count": 0,
                    "latency_sum_ms": 0.0,
                    "latency_max_ms": 0.0,
                    "error_codes": {},
                },
            )
            entry["calls"] += 1
            entry["latency_count"] += 1
            entry["latency_sum_ms"] += duration_ms
            entry["latency_max_ms"] = max(
                entry["latency_max_ms"], duration_ms
            )
            self._counters["tool_exec_total"] = (
                self._counters.get("tool_exec_total", 0) + 1
            )
            if outcome == "ok":
                entry["ok"] += 1
                self._counters["tool_ok_total"] = (
                    self._counters.get("tool_ok_total", 0) + 1
                )
            elif outcome == "blocked":
                entry["blocked"] += 1
                self._counters["tool_blocked_total"] = (
                    self._counters.get("tool_blocked_total", 0) + 1
                )
            elif outcome == "timeout":
                entry["timeouts"] += 1
                self._counters["tool_timeout_total"] = (
                    self._counters.get("tool_timeout_total", 0) + 1
                )
            if outcome in {"error", "timeout"}:
                entry["errors"] += 1
                self._counters["tool_error_total"] = (
                    self._counters.get("tool_error_total", 0) + 1
                )
                if error_code:
                    codes = entry["error_codes"]
                    codes[error_code] = codes.get(error_code, 0) + 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)
            count = self._duration_count
            average = self._duration_sum_ms / count if count else 0.0
            tools: dict[str, Any] = {}
            for name, entry in self._tools.items():
                latency_count = entry["latency_count"]
                tools[name] = {
                    "calls": entry["calls"],
                    "ok": entry["ok"],
                    "errors": entry["errors"],
                    "blocked": entry["blocked"],
                    "timeouts": entry["timeouts"],
                    "latency_ms": {
                        "count": latency_count,
                        "avg": round(
                            entry["latency_sum_ms"] / latency_count, 2
                        )
                        if latency_count
                        else 0.0,
                        "max": round(entry["latency_max_ms"], 2),
                    },
                    "error_codes": dict(entry["error_codes"]),
                }
            return {
                "uptime_seconds": int(time.time() - self._started_at),
                "counters": counters,
                "latency_ms": {
                    "count": count,
                    "avg": round(average, 2),
                    "max": round(self._duration_max_ms, 2),
                },
                "tools": tools,
            }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._duration_count = 0
            self._duration_sum_ms = 0.0
            self._duration_max_ms = 0.0
            self._tools.clear()
            self._started_at = time.time()


METRICS = Metrics()
