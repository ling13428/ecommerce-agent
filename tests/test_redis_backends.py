from pydantic import BaseModel

from agent import session_store
from agent.session_store import (
    CompositeSessionStore,
    RedisSessionStore,
    load_record,
    load_records,
)
from core.cache import reset_cache, set_redis_client
from core.config import get_settings
from core.ratelimit import allow_request
from tools.registry import ToolSpec, execute_tool, register_tool, unregister_tool


class FakePipeline:
    def __init__(self, client):
        self.client = client
        self.ops = []

    def set(self, *args, **kwargs):
        self.ops.append(("set", args, kwargs))
        return self

    def zadd(self, *args, **kwargs):
        self.ops.append(("zadd", args, kwargs))
        return self

    def expire(self, *args, **kwargs):
        self.ops.append(("expire", args, kwargs))
        return self

    def execute(self):
        for name, args, kwargs in self.ops:
            getattr(self.client, name)(*args, **kwargs)
        self.ops = []


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.sorted_sets = {}
        self.expires = {}

    def ping(self):
        return True

    def incr(self, key):
        value = int(self.values.get(key, 0)) + 1
        self.values[key] = value
        return value

    def expire(self, key, seconds):
        self.expires[key] = seconds
        return True

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return None
        self.values[key] = value
        if ex is not None:
            self.expires[key] = ex
        return True

    def delete(self, *keys):
        count = 0
        for key in keys:
            if key in self.values:
                del self.values[key]
                count += 1
            if key in self.sorted_sets:
                del self.sorted_sets[key]
                count += 1
        return count

    def pipeline(self):
        return FakePipeline(self)

    def zadd(self, key, mapping):
        self.sorted_sets.setdefault(key, {}).update(mapping)
        return len(mapping)

    def zrange(self, key, start, end):
        items = sorted(
            self.sorted_sets.get(key, {}).items(), key=lambda item: item[1]
        )
        return [name for name, _ in items[start : None if end == -1 else end + 1]]

    def mget(self, keys):
        return [self.values.get(key) for key in keys]


def use_redis(monkeypatch, **env):
    monkeypatch.setenv("CACHE_BACKEND", "redis")
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))
    get_settings.cache_clear()
    reset_cache()
    session_store.reset_store()
    client = FakeRedis()
    set_redis_client(client)
    return client


def cleanup():
    reset_cache()
    session_store.reset_store()
    get_settings.cache_clear()


def test_redis_rate_limit_is_shared(monkeypatch):
    try:
        use_redis(monkeypatch, RATE_LIMIT_PER_MINUTE=2)
        assert allow_request("session-a") is True
        assert allow_request("session-a") is True
        assert allow_request("session-a") is False
        assert allow_request("session-b") is True
    finally:
        cleanup()


class WriteArgs(BaseModel):
    order_id: str


def test_redis_idempotency_prevents_duplicate_execution(monkeypatch):
    calls = []

    def cancel(order_id):
        calls.append(order_id)
        return {"cancelled": order_id}

    register_tool(
        ToolSpec(
            name="_redis_write",
            description="test only",
            args_model=WriteArgs,
            func=cancel,
            kind="write",
        )
    )
    try:
        use_redis(monkeypatch)
        first = execute_tool(
            "_redis_write",
            {"order_id": "A100"},
            confirmed=True,
            idempotency_key="key-1",
        )
        second = execute_tool(
            "_redis_write",
            {"order_id": "A100"},
            confirmed=True,
            idempotency_key="key-1",
        )
        assert first["ok"] is True
        assert second == first
        assert calls == ["A100"]
    finally:
        unregister_tool("_redis_write")
        cleanup()


def test_redis_session_store_roundtrip(monkeypatch):
    try:
        use_redis(monkeypatch)
        store = session_store.get_store()
        assert isinstance(store, RedisSessionStore)
        store.save(
            {
                "session_id": "s-redis",
                "messages": [{"id": 1, "role": "user", "content": "你好"}],
                "updated_at": 100.0,
            }
        )
        assert load_record("s-redis")["session_id"] == "s-redis"
        records = load_records()
        assert [record["session_id"] for record in records] == ["s-redis"]

        store.clear()
        assert load_record("s-redis") is None
        assert load_records() == []
    finally:
        cleanup()


class FakeMemoryStore:
    def __init__(self):
        self.values = {}

    def save(self, record):
        self.values[record["session_id"]] = record

    def load_one(self, session_id):
        return self.values.get(session_id)

    def load_all(self):
        return list(self.values.values())

    def clear(self):
        self.values.clear()


def test_composite_store_writes_through_and_warms_cache():
    hot = FakeMemoryStore()
    durable = FakeMemoryStore()
    store = CompositeSessionStore(hot, durable)
    record = {"session_id": "s1", "messages": [], "updated_at": 1.0}

    store.save(record)
    assert hot.load_one("s1") == record
    assert durable.load_one("s1") == record

    hot.clear()
    assert store.load_one("s1") == record
    assert hot.load_one("s1") == record
    assert [item["session_id"] for item in store.load_all()] == ["s1"]

    store.clear()
    assert durable.load_one("s1") is None
    assert hot.load_one("s1") is None
