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

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)
            count = self._duration_count
            average = self._duration_sum_ms / count if count else 0.0
            return {
                "uptime_seconds": int(time.time() - self._started_at),
                "counters": counters,
                "latency_ms": {
                    "count": count,
                    "avg": round(average, 2),
                    "max": round(self._duration_max_ms, 2),
                },
            }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._duration_count = 0
            self._duration_sum_ms = 0.0
            self._duration_max_ms = 0.0
            self._started_at = time.time()


METRICS = Metrics()
