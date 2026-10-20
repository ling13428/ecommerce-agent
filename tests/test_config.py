import pytest

from core.config import Settings


def test_empty_key_means_llm_not_configured():
    settings = Settings(_env_file=None, llm_api_key="")
    assert settings.llm_configured is False


def test_secret_is_masked_in_repr():
    settings = Settings(_env_file=None, llm_api_key="sk-super-secret-value")
    assert settings.llm_configured is True
    assert "sk-super-secret-value" not in repr(settings)


def test_invalid_base_url_fails_startup_validation():
    settings = Settings(
        _env_file=None,
        llm_api_key="sk-test",
        llm_base_url="ftp://example.com",
    )
    with pytest.raises(ValueError):
        settings.validate_startup()
