import json

from fastapi.testclient import TestClient

import main
from agent.session import SessionState, get_session, reset_sessions

client = TestClient(
    main.app, headers={"X-Admin-Token": "test-admin-token"}
)


def setup_function():
    reset_sessions()


def teardown_function():
    reset_sessions()


def test_admin_requires_token():
    anonymous = TestClient(main.app)
    assert anonymous.get("/api/admin/sessions").status_code == 401


def test_buyer_login_and_me():
    from services import orders as order_service

    buyer = order_service.list_buyers()[0]
    login = client.post(
        "/api/auth/buyer/login",
        json={
            "buyer_id": buyer["buyer_id"],
            "login_code": buyer["login_code"],
        },
    )
    assert login.status_code == 200
    token = login.json()["token"]
    me = client.get(
        "/api/auth/buyer/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200
    assert me.json()["buyer"]["buyer_id"] == buyer["buyer_id"]
    assert (
        client.get(
            "/api/auth/buyer/me",
            headers={"Authorization": "Bearer invalid"},
        ).status_code
        == 401
    )


def test_public_messages_hide_system_and_filter_human():
    session = SessionState(session_id="s1")
    session.add_user("你好")
    session.add_system("内部备注")
    session.add_assistant("机器人回复")
    session.add_assistant("人工回复", source="human")

    visible = session.public_messages()
    assert [message["content"] for message in visible] == [
        "你好",
        "机器人回复",
        "人工回复",
    ]
    assert all("source" not in message for message in visible[:2])

    human_only = session.public_messages(after_id=visible[1]["id"], human_only=True)
    assert [message["content"] for message in human_only] == ["人工回复"]


def test_snapshot_strips_internal_fields():
    session = SessionState(session_id="s2")
    session.add_user("hi")
    session.add_assistant("hello", source="human")

    assert session.snapshot() == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_admin_session_flow_and_merchant_reply():
    session = get_session("merchant-flow")
    session.add_user("我的快递到哪了")
    session.add_assistant("正在为你查询…")

    listed = client.get("/api/admin/sessions").json()["sessions"]
    assert listed[0]["session_id"] == "merchant-flow"
    assert listed[0]["last_role"] == "assistant"
    assert listed[0]["human_mode"] is False

    detail = client.get("/api/admin/sessions/merchant-flow").json()
    assert len(detail["messages"]) == 2

    takeover = client.post(
        "/api/admin/sessions/merchant-flow/takeover", json={"enabled": True}
    )
    assert takeover.status_code == 200
    assert takeover.json()["human_mode"] is True

    reply = client.post(
        "/api/admin/sessions/merchant-flow/reply",
        json={"message": "我在，帮你查一下"},
    )
    assert reply.status_code == 200

    detail = client.get("/api/admin/sessions/merchant-flow").json()
    assert detail["messages"][-1] == {
        "id": detail["messages"][-1]["id"],
        "role": "assistant",
        "content": "我在，帮你查一下",
        "source": "human",
    }


def test_chat_messages_returns_only_human_replies():
    session = get_session("buyer-poll")
    session.add_user("在吗")
    session.add_assistant("机器人回复")
    session.add_assistant("人工回复", source="human")
    session.set_human_mode(True)

    payload = client.get(
        "/api/chat/messages", params={"session_id": "buyer-poll", "after_id": 0}
    ).json()
    assert payload["human_mode"] is True
    assert [message["content"] for message in payload["messages"]] == ["人工回复"]


def test_chat_messages_unknown_session_is_empty():
    payload = client.get(
        "/api/chat/messages", params={"session_id": "missing-session"}
    ).json()
    assert payload == {"human_mode": False, "messages": []}


def test_human_mode_skips_llm_and_keeps_buyer_message():
    session = get_session("human-gate")
    session.set_human_mode(True)

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "你好", "session_id": "human-gate"},
    ) as response:
        body = "".join(response.iter_text())

    events = [
        json.loads(line[len("data: ") :])
        for line in body.splitlines()
        if line.startswith("data: ")
    ]
    types = [event["type"] for event in events]
    assert types == ["start", "human_mode", "done"]
    assert session.last_user_message() == "你好"


def test_admin_detail_exposes_agent_trace():
    session = get_session("trace-flow")
    session.set_human_mode(True)

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "在吗", "session_id": "trace-flow"},
    ) as response:
        "".join(response.iter_text())

    detail = client.get("/api/admin/sessions/trace-flow").json()
    assert len(detail["traces"]) == 1
    trace = detail["traces"][0]
    assert trace["status"] == "human_mode"
    assert trace["user_message"] == "在吗"
    assert [step["type"] for step in trace["steps"]] == ["receive", "human_mode"]


def test_agent_stream_records_trace_without_leaking_internal_events(monkeypatch):
    from types import SimpleNamespace

    async def fake_agent(session, **kwargs):
        yield {
            "type": "llm_step",
            "step": 1,
            "tool_call_count": 1,
            "has_text": False,
        }
        yield {
            "type": "tool_call",
            "name": "search_knowledge",
            "args": {"query": "续航"},
            "ok": True,
            "step": 1,
            "detail": {
                "kind": "rag",
                "query": "续航",
                "product_id": "P2001",
                "abstained": False,
                "top_score": 0.78,
                "hits": [
                    {
                        "doc_id": "P2001-02",
                        "title": "VK75 Pro 参数",
                        "section": "参数",
                        "score": 0.78,
                        "content": "续航约 30 小时",
                    }
                ],
            },
        }
        yield {"type": "delta", "content": "续航约 30 小时。"}

    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(
            llm_configured=True, llm_model="fake", max_message_chars=2000
        ),
    )
    monkeypatch.setattr(main, "run_llm_agent", fake_agent)

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "P2001 续航", "session_id": "trace-rag"},
    ) as response:
        body = "".join(response.iter_text())

    events = [
        json.loads(line[len("data: ") :])
        for line in body.splitlines()
        if line.startswith("data: ")
    ]
    types = [event["type"] for event in events]
    assert "llm_step" not in types
    tool_events = [event for event in events if event["type"] == "tool_call"]
    assert "detail" not in tool_events[0]

    trace = get_session("trace-rag").public_traces()[0]
    assert trace["status"] == "ok"
    assert trace["reply"] == "续航约 30 小时。"
    assert trace["tool_calls"] == 1
    assert trace["rag_hits"] == 1
    assert [step["type"] for step in trace["steps"]] == [
        "receive",
        "route",
        "llm",
        "tool_call",
        "reply",
    ]
    assert trace["steps"][3]["detail"]["hits"][0]["doc_id"] == "P2001-02"


def test_session_traces_are_capped_and_filterable():
    session = SessionState(session_id="trace-cap", max_traces=2)
    session.add_trace({"user_message": "第一轮", "steps": []})
    second = session.add_trace({"user_message": "第二轮", "steps": []})
    session.add_trace({"user_message": "第三轮", "steps": []})

    assert len(session.traces) == 2
    assert [trace["id"] for trace in session.public_traces()] == [
        second["id"],
        second["id"] + 1,
    ]
    assert len(session.public_traces(after_id=second["id"])) == 1


def test_admin_unknown_session_returns_404():
    response = client.get("/api/admin/sessions/not-exist")
    assert response.status_code == 404

    response = client.post(
        "/api/admin/sessions/not-exist/reply", json={"message": "hi"}
    )
    assert response.status_code == 404


def test_admin_rejects_invalid_session_id():
    response = client.get("/api/admin/sessions/bad id!")
    assert response.status_code == 400
