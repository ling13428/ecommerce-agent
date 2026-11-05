from types import SimpleNamespace

from agent import agent_utils


def make_settings(**overrides):
    base = {
        "llm_circuit_failures": 2,
        "llm_circuit_cooldown": 30.0,
        "llm_fallback_configured": False,
        "llm_fallback_model": "",
        "llm_model": "main",
        "alert_webhook_url": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_breaker_opens_after_consecutive_failures(monkeypatch):
    agent_utils.reset_breaker()
    monkeypatch.setattr(agent_utils, "get_settings", lambda: make_settings())

    assert agent_utils.breaker_open() is False
    agent_utils.record_llm_failure()
    assert agent_utils.breaker_open() is False
    agent_utils.record_llm_failure()
    assert agent_utils.breaker_open() is True

    agent_utils.record_llm_success()
    assert agent_utils.breaker_open() is False


def test_resolve_llm_switches_to_fallback_when_open(monkeypatch):
    agent_utils.reset_breaker()
    settings = make_settings(
        llm_fallback_configured=True, llm_fallback_model="backup"
    )
    monkeypatch.setattr(agent_utils, "get_settings", lambda: settings)
    monkeypatch.setattr(agent_utils, "get_llm_client", lambda: "primary")
    monkeypatch.setattr(agent_utils, "get_fallback_client", lambda: "fallback")

    assert agent_utils.resolve_llm() == ("primary", "main")

    agent_utils.record_llm_failure()
    agent_utils.record_llm_failure()
    assert agent_utils.resolve_llm() == ("fallback", "backup")

    agent_utils.record_llm_success()
    assert agent_utils.resolve_llm() == ("primary", "main")
    agent_utils.reset_breaker()


def test_resolve_llm_keeps_primary_without_fallback(monkeypatch):
    agent_utils.reset_breaker()
    monkeypatch.setattr(agent_utils, "get_settings", lambda: make_settings())
    monkeypatch.setattr(agent_utils, "get_llm_client", lambda: "primary")

    agent_utils.record_llm_failure()
    agent_utils.record_llm_failure()

    assert agent_utils.breaker_open() is True
    assert agent_utils.resolve_llm() == ("primary", "main")
    agent_utils.reset_breaker()
