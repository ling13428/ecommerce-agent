import pytest

from core.cache import reset_async_cache, set_async_redis_client
from core.config import get_settings
from core.ratelimit import allow_request_async, reset_rate_limiter
from core.session_lock import session_lock
from mcp_servers.idempotency import run_once_async


class FakeAsyncRedis:
    def __init__(self):
        self.values = {}
        self.expires = {}
        self.closed = False

    async def ping(self):
        return True

    async def incr(self, key):
        value = int(self.values.get(key, 0)) + 1
        self.values[key] = value
        return value

    async def expire(self, key, seconds):
        self.expires[key] = seconds
        return True

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return None
        self.values[key] = value
        if ex is not None:
            self.expires[key] = ex
        return True

    async def delete(self, *keys):
        count = 0
        for key in keys:
            if key in self.values:
                del self.values[key]
                count += 1
        return count

    async def eval(self, script, numkeys, *args):
        key, owner = args[0], args[1]
        if self.values.get(key) != owner:
            return 0
        if "expire" in script:
            if len(args) > 2:
                self.expires[key] = int(args[2])
            return 1
        del self.values[key]
        return 1

    async def aclose(self):
        self.closed = True


@pytest.fixture
def async_redis(monkeypatch):
    monkeypatch.setenv("CACHE_BACKEND", "redis")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    get_settings.cache_clear()
    reset_rate_limiter()
    reset_async_cache()
    fake = FakeAsyncRedis()
    set_async_redis_client(fake)
    yield fake
    reset_async_cache()
    reset_rate_limiter()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_async_rate_limit_uses_async_redis(async_redis):
    assert await allow_request_async("session-a") is True
    assert await allow_request_async("session-a") is True
    assert await allow_request_async("session-a") is False
    assert await allow_request_async("session-b") is True


@pytest.mark.asyncio
async def test_session_lock_uses_async_redis(async_redis):
    async with session_lock("lock-session", timeout=1):
        assert async_redis.values.get("session:lock:lock-session")
    assert async_redis.values.get("session:lock:lock-session") is None


@pytest.mark.asyncio
async def test_async_idempotency_runs_once(async_redis):
    calls: list[str] = []

    async def work():
        calls.append("run")
        return {"ok": True, "value": 1}

    first = await run_once_async("mcp-key", work)
    second = await run_once_async("mcp-key", work)
    assert first == second
    assert calls == ["run"]
