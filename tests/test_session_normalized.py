import pytest

from agent import session as session_module
from agent import session_store
from agent.session_repo import DuplicateMessage, VersionConflict
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
    yield
    get_settings.cache_clear()
    session_store.reset_store()
    session_module.reset_sessions()


def test_normalized_session_persists_incrementally(normalized):
    session = session_module.get_session("sess-1")
    session.set_buyer_id("BUYER1")
    session.add_user("你好", client_msg_id="c1")
    session.add_assistant("你好，有什么可以帮你？")
    session.add_trace(
        {"user_message_id": 1, "status": "ok", "steps": []}
    )
    session.close("resolved")

    session_module.reset_sessions()

    restored = session_module.get_session("sess-1")
    assert restored.buyer_id == "BUYER1"
    assert [message["content"] for message in restored.messages] == [
        "你好",
        "你好，有什么可以帮你？",
    ]
    assert len(restored.traces) == 1
    assert restored.status == "closed"
    assert restored.close_reason == "resolved"


def test_duplicate_client_msg_id_is_rejected(normalized):
    session = session_module.get_session("sess-2")
    session.add_user("第一条", client_msg_id="same")
    with pytest.raises(DuplicateMessage):
        session.add_user("重复", client_msg_id="same")
    assert len(session.messages) == 1


def test_stale_session_object_cannot_write(normalized):
    stale = session_module.get_session("sess-3")
    stale.add_user("a")

    session_module.reset_sessions()

    fresh = session_module.get_session("sess-3")
    fresh.add_user("b")

    with pytest.raises(VersionConflict):
        stale.add_user("c")

    session_module.reset_sessions()
    restored = session_module.get_session("sess-3")
    assert [message["content"] for message in restored.messages] == ["a", "b"]
