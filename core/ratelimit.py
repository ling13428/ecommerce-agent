from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from core.config import get_settings


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        if self.limit <= 0:
            return True

        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window_seconds:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_limiter: RateLimiter | None = None
_limiter_lock = threading.Lock()


def _get_limiter() -> RateLimiter:
    global _limiter
    with _limiter_lock:
        if _limiter is None:
            _limiter = RateLimiter(get_settings().rate_limit_per_minute)
        return _limiter


def allow_request(session_id: str) -> bool:
    return _get_limiter().allow(session_id)


def reset_rate_limiter() -> None:
    _get_limiter().reset()
