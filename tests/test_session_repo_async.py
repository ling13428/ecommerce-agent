import time

import pytest

from agent.session_repo import (
    AsyncThreadedSessionRepository,
    DuplicateMessage,
    SqliteSessionRepository,
    VersionConflict,
)


@pytest.fixture
def repo(tmp_path):
    sync_repo = SqliteSessionRepository(tmp_path / "sessions.db")
    sync_repo.ensure_schema()
    sync_repo.create("s1", "BUYER1", time.time())
    async_repo = AsyncThreadedSessionRepository(sync_repo, max_workers=2)
    yield async_repo
    async_repo.close()


@pytest.mark.asyncio
async def test_async_threaded_repo_append_and_read(repo):
    message_id, version = await repo.append_message(
        "s1",
        role="user",
        content="你好",
        source=None,
        client_msg_id="c1",
        expected_version=0,
        now=time.time(),
    )
    assert message_id > 0
    assert version == 1

    trace_id, version = await repo.append_trace(
        "s1",
        {"user_message_id": message_id, "status": "ok", "steps": []},
        expected_version=1,
        now=time.time(),
    )
    assert trace_id > 0
    assert version == 2

    record = await repo.full_record("s1")
    assert record is not None
    assert record["messages"][0]["content"] == "你好"
    assert record["traces"][0]["status"] == "ok"


@pytest.mark.asyncio
async def test_async_threaded_repo_version_and_duplicate(repo):
    await repo.append_message(
        "s1",
        role="user",
        content="你好",
        source=None,
        client_msg_id="same",
        expected_version=0,
        now=time.time(),
    )

    with pytest.raises(DuplicateMessage):
        await repo.append_message(
            "s1",
            role="user",
            content="重复",
            source=None,
            client_msg_id="same",
            expected_version=1,
            now=time.time(),
        )

    with pytest.raises(VersionConflict):
        await repo.update_meta(
            "s1",
            {"human_mode": True},
            expected_version=0,
            now=time.time(),
        )
