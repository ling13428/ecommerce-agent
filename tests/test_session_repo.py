import threading
import time

import pytest

from agent.session_repo import (
    DuplicateMessage,
    SqliteSessionRepository,
    VersionConflict,
)


def make_repo(tmp_path):
    repo = SqliteSessionRepository(tmp_path / "sessions.db")
    repo.ensure_schema()
    repo.create("s1", "BUYER1", time.time())
    return repo


def test_append_message_and_trace_bumps_version(tmp_path):
    repo = make_repo(tmp_path)

    message_id, version = repo.append_message(
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

    trace_id, version = repo.append_trace(
        "s1",
        {"user_message_id": message_id, "status": "ok", "steps": []},
        expected_version=1,
        now=time.time(),
    )
    assert trace_id > 0
    assert version == 2

    record = repo.full_record("s1")
    assert record is not None
    assert record["messages"][0]["content"] == "你好"
    assert record["traces"][0]["status"] == "ok"
    assert record["next_message_id"] == message_id + 1


def test_stale_version_is_rejected(tmp_path):
    repo = make_repo(tmp_path)
    repo.append_message(
        "s1",
        role="user",
        content="第一条",
        source=None,
        client_msg_id=None,
        expected_version=0,
        now=time.time(),
    )

    with pytest.raises(VersionConflict):
        repo.append_message(
            "s1",
            role="user",
            content="过期写入",
            source=None,
            client_msg_id=None,
            expected_version=0,
            now=time.time(),
        )

    record = repo.full_record("s1")
    assert record is not None
    assert len(record["messages"]) == 1


def test_duplicate_client_msg_id_is_rejected(tmp_path):
    repo = make_repo(tmp_path)
    repo.append_message(
        "s1",
        role="user",
        content="你好",
        source=None,
        client_msg_id="same-id",
        expected_version=0,
        now=time.time(),
    )

    with pytest.raises(DuplicateMessage):
        repo.append_message(
            "s1",
            role="user",
            content="重复",
            source=None,
            client_msg_id="same-id",
            expected_version=1,
            now=time.time(),
        )

    record = repo.full_record("s1")
    assert record is not None
    assert len(record["messages"]) == 1
    assert record["version"] == 1


def test_update_meta_cas(tmp_path):
    repo = make_repo(tmp_path)
    version = repo.update_meta(
        "s1",
        {"human_mode": True},
        expected_version=0,
        now=time.time(),
    )
    assert version == 1
    meta = repo.get_meta("s1")
    assert meta is not None
    assert meta["human_mode"] is True

    with pytest.raises(VersionConflict):
        repo.update_meta(
            "s1",
            {"human_mode": False},
            expected_version=0,
            now=time.time(),
        )


def test_serialized_appends_do_not_lose_messages(tmp_path):
    repo = make_repo(tmp_path)
    guard = threading.Lock()
    total = 20

    def worker(index):
        for attempt in range(50):
            with guard:
                meta = repo.get_meta("s1")
                try:
                    repo.append_message(
                        "s1",
                        role="user",
                        content=f"消息{index}",
                        source=None,
                        client_msg_id=f"c{index}",
                        expected_version=int(meta["version"]),
                        now=time.time(),
                    )
                    return
                except VersionConflict:
                    continue
        raise AssertionError("append failed")

    threads = [
        threading.Thread(target=worker, args=(index,))
        for index in range(total)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    record = repo.full_record("s1")
    assert record is not None
    messages = record["messages"]
    assert len(messages) == total
    assert len({message["id"] for message in messages}) == total
