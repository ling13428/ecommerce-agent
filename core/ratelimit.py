from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque

from core.cache import get_redis
from core.config import get_settings

logger = logging.getLogger("ecommerce_agent.ratelimit")


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
    limit = get_settings().rate_limit_per_minute
    if limit <= 0:
        return True

    client = get_redis()
    if client is not None:
        key = f"ratelimit:{session_id}:{int(time.time() // 60)}"
        try:
            count = int(client.incr(key))
            if count == 1:
                client.expire(key, 62)
            return count <= limit
        except Exception as exc:
            logger.warning("Redis 限流失败，回退到进程内存：%s", exc)

    return _get_limiter().allow(session_id)


def reset_rate_limiter() -> None:
    _get_limiter().reset()
