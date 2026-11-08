import json
import time

import pytest

import main
from agent import session as session_module
from agent import session_store
from agent.router import RouteResult
from agent.session_repo import get_repository
from core.config import get_settings


@pytest.fixture
def normalized(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSION_PERSISTENCE", "true")
    monkeypatch.setenv("SESSION_STORAGE_MODE", "normalized")
    monkeypatch.setenv("SESSION_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("SESSION_DB_PATH", str(tmp_path / "sessions.db"))
    monkeypatch.setenv("CACHE_BACKEND", "memory")
    get_settings.cache_clear()
    session_store.reset_store()
    session_module.reset_sessions()
    monkeypatch.setattr(main, "settings", get_settings())

    async def fake_route(*args, **kwargs):
        return RouteResult(
            route="chat",
            sub_intent="smalltalk",
            action="reply",
            confidence=0.95,
            message="你好呀",
        )

    monkeypatch.setattr(main, "route_message_l2", fake_route)
    yield
    get_settings.cache_clear()
    session_store.reset_store()
    session_module.reset_sessions()


async def collect(events):
    return [event async for event in events]


def parse_events(chunks):
    result = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if not line.startswith("data:"):
                continue
            try:
                result.append(json.loads(line[len("data:") :].strip()))
            except json.JSONDecodeError:
                continue
    return result


@pytest.mark.asyncio
async def test_stream_creates_session_and_dedupes_client_message(normalized):
    events = collect(
        main.agent_stream("你好", None, None, "client-1", None)
    )
    parsed = parse_events(await events)
    start = next(item for item in parsed if item["type"] == "start")
    session_id = start["session_id"]
    assert any(
        item.get("type") == "delta" and "你好呀" in item.get("content", "")
        for item in parsed
    )

    duplicate = parse_events(
        await collect(
            main.agent_stream("你好", session_id, None, "client-1", None)
        )
    )
    assert any(item.get("duplicate") for item in duplicate)


@pytest.mark.asyncio
async def test_idle_session_starts_a_new_one(normalized):
    first = parse_events(
        await collect(
            main.agent_stream("你好", None, None, "first", None)
        )
    )
    session_id = next(
        item["session_id"] for item in first if item["type"] == "start"
    )

    repository = get_repository()
    assert repository is not None
    meta = repository.get_meta(session_id)
    assert meta is not None
    repository.update_meta(
        session_id,
        {"status": "active"},
        expected_version=int(meta["version"]),
        now=time.time() - 31 * 60,
    )
    session_module.invalidate_session(session_id)

    second = parse_events(
        await collect(
            main.agent_stream("你好", session_id, None, "second", None)
        )
    )
    new_session_id = next(
        item["session_id"] for item in second if item["type"] == "start"
    )
    assert new_session_id != session_id

    ids = {item["session_id"] for item in session_module.list_sessions()}
    assert session_id in ids
    assert new_session_id in ids
