import asyncio
import json
from types import SimpleNamespace

from agent.router import route_message_l2
from agent.session import SessionState


class FakeCompletions:
    def __init__(self, content=None, exc=None):
        self.content = content
        self.exc = exc
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.content)
                )
            ]
        )


class FakeClient:
    def __init__(self, content=None, exc=None):
        self.chat = SimpleNamespace(
            completions=FakeCompletions(content=content, exc=exc)
        )


def make_settings(**overrides):
    base = {
        "router_llm_enabled": True,
        "router_llm_min_confidence": 0.7,
        "router_llm_timeout": 2.0,
        "router_llm_max_tokens": 200,
        "llm_model": "deepseek-chat",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def new_session(message):
    session = SessionState(session_id="router-l2-test")
    session.add_user(message)
    return session


def decide(message, client, settings=None):
    return asyncio.run(
        route_message_l2(
            message,
            new_session(message),
            client=client,
            settings=settings or make_settings(),
        )
    )


def decision_json(route, sub_intent, confidence, reason=""):
    return json.dumps(
        {
            "route": route,
            "sub_intent": sub_intent,
            "confidence": confidence,
            "reason": reason,
        },
        ensure_ascii=False,
    )


def test_confident_rule_skips_llm():
    client = FakeClient(content=decision_json("handoff", "human", 0.9))
    result = decide("我要转人工", client)

    assert result.route == "handoff"
    assert result.source == "rule"
    assert client.chat.completions.calls == 0


def test_ambiguous_message_uses_llm():
    client = FakeClient(
        content=decision_json(
            "transaction", "logistics", 0.9, "询问包裹进度"
        )
    )
    result = decide("我的东西怎么还没到", client)

    assert result.route == "transaction"
    assert result.sub_intent == "logistics"
    assert result.source == "llm"
    assert result.confidence == 0.9
    assert "get_logistics" in result.allowed_tools


def test_low_confidence_keeps_rule_result():
    client = FakeClient(
        content=decision_json("chat", "smalltalk", 0.4)
    )
    result = decide("随便聊聊", client)

    assert result.route == "chat"
    assert result.sub_intent == "out_of_scope"
    assert result.source == "rule"


def test_invalid_json_keeps_rule_result():
    client = FakeClient(content="not a json object")
    result = decide("我的东西怎么还没到", client)

    assert result.route == "chat"
    assert result.sub_intent == "out_of_scope"
    assert result.source == "rule"


def test_timeout_keeps_rule_result():
    client = FakeClient(exc=TimeoutError())
    result = decide("我的东西怎么还没到", client)

    assert result.source == "rule"
    assert result.route == "chat"


def test_disabled_router_skips_llm():
    client = FakeClient(content=decision_json("transaction", "order_query", 0.9))
    result = decide(
        "我的东西怎么还没到",
        client,
        settings=make_settings(router_llm_enabled=False),
    )

    assert result.source == "rule"
    assert client.chat.completions.calls == 0


def test_policy_question_skips_llm():
    client = FakeClient(content=decision_json("knowledge", "knowledge", 0.9))
    result = decide("七天无理由退货政策", client)

    assert result.route == "knowledge"
    assert result.source == "rule"
    assert client.chat.completions.calls == 0


def test_product_knowledge_skips_llm():
    client = FakeClient(content=decision_json("knowledge", "knowledge", 0.9))
    result = decide("VK75 Pro 的触发键程", client)

    assert result.route == "knowledge"
    assert result.source == "rule"
    assert client.chat.completions.calls == 0


def test_code_fence_and_unknown_sub_intent():
    fenced = "```json\n" + decision_json(
        "transaction", "unknown_intent", 0.85
    ) + "\n```"
    client = FakeClient(content=fenced)
    result = decide("我的东西怎么还没到", client)

    assert result.route == "transaction"
    assert result.sub_intent == "order_query"
    assert result.source == "llm"
    assert "get_order" in result.allowed_tools


def test_unknown_route_falls_back():
    client = FakeClient(
        content=decision_json("unknown", "knowledge", 0.95)
    )
    result = decide("我的东西怎么还没到", client)

    assert result.source == "rule"
    assert result.route == "chat"
