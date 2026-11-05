from core.config import get_settings
from core.features import saleor_enabled


def setup_env(monkeypatch, *, percent=100, allowlist=""):
    monkeypatch.setenv("ORDER_PROVIDER", "saleor")
    monkeypatch.setenv("SALEOR_ROLLOUT_PERCENT", str(percent))
    monkeypatch.setenv("SALEOR_ALLOWLIST", allowlist)
    get_settings.cache_clear()


def cleanup():
    get_settings.cache_clear()


def test_rollout_100_enables_all_buyers(monkeypatch):
    setup_env(monkeypatch, percent=100)
    try:
        assert saleor_enabled("BUY-0001") is True
        assert saleor_enabled("BUY-0099") is True
    finally:
        cleanup()


def test_rollout_0_disables_all_buyers(monkeypatch):
    setup_env(monkeypatch, percent=0)
    try:
        assert saleor_enabled("BUY-0001") is False
    finally:
        cleanup()


def test_allowlist_overrides_percent(monkeypatch):
    setup_env(monkeypatch, percent=0, allowlist="BUY-0001, BUY-0002")
    try:
        assert saleor_enabled("BUY-0001") is True
        assert saleor_enabled("buy-0002") is True
        assert saleor_enabled("BUY-0003") is False
    finally:
        cleanup()


def test_mock_provider_always_disabled(monkeypatch):
    monkeypatch.setenv("ORDER_PROVIDER", "mock")
    monkeypatch.setenv("SALEOR_ROLLOUT_PERCENT", "100")
    get_settings.cache_clear()
    try:
        assert saleor_enabled("BUY-0001") is False
    finally:
        cleanup()


def test_bucket_is_stable_for_same_buyer(monkeypatch):
    setup_env(monkeypatch, percent=50)
    try:
        first = saleor_enabled("BUY-0007")
        second = saleor_enabled("BUY-0007")
        assert first == second
    finally:
        cleanup()
