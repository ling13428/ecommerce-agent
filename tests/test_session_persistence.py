from agent.session import SessionState
from agent.session_store import SessionStore


def test_session_record_roundtrip():
    session = SessionState(session_id="roundtrip")
    session.add_user("P2001 多少钱")
    session.add_assistant("969 元")
    session.set_human_mode(True)
    session.set_pending("cancel_order", {"order_id": "A100"}, "取消订单 A100")
    session.add_trace(
        {
            "user_message_id": 1,
            "user_message": "P2001 多少钱",
            "status": "ok",
            "steps": [{"type": "reply", "content": "969 元"}],
        }
    )

    restored = SessionState.from_record(session.to_record())

    assert restored.session_id == "roundtrip"
    assert restored.messages == session.messages
    assert restored.traces == session.traces
    assert restored.human_mode is True
    assert restored.pending_action is not None
    assert restored.pending_action.name == "cancel_order"
    assert restored.pending_action.args == {"order_id": "A100"}
    assert restored.next_message_id == session.next_message_id
    assert restored.next_trace_id == session.next_trace_id


def test_all_traces_are_retained_and_history_is_windowed_for_llm():
    session = SessionState(session_id="retention")

    for index in range(40):
        session.add_message("user", f"问题 {index}")
        session.add_trace(
            {
                "user_message_id": index + 1,
                "user_message": f"问题 {index}",
                "status": "ok",
                "steps": [],
            }
        )

    assert len(session.messages) == 40
    assert len(session.traces) == 40
    assert [trace["id"] for trace in session.traces] == list(range(1, 41))

    snapshot = session.snapshot()
    assert len(snapshot) == session.context_messages
    assert snapshot[0]["content"] == "问题 20"


def test_session_store_roundtrip(tmp_path):
    store = SessionStore(tmp_path / "sessions.db")
    session = SessionState(session_id="stored")
    session.add_user("你好")
    session.add_assistant("你好，有什么可以帮你？")
    session.add_trace(
        {
            "user_message_id": 1,
            "user_message": "你好",
            "status": "ok",
            "steps": [],
        }
    )

    store.save(session.to_record())
    store.save(session.to_record())
    records = store.load_all()

    assert len(records) == 1
    restored = SessionState.from_record(records[0])
    assert restored.session_id == "stored"
    assert len(restored.traces) == 1
    assert restored.messages[-1]["content"] == "你好，有什么可以帮你？"

    store.clear()
    assert store.load_all() == []
    store.close()
