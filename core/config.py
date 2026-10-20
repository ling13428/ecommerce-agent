from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    llm_api_key: SecretStr | None = None
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_timeout: float = Field(default=30.0, gt=0, le=300)
    llm_max_steps: int = Field(default=5, ge=1, le=10)
    llm_max_tokens: int = Field(default=800, ge=64, le=8192)
    llm_temperature: float = Field(default=0.2, ge=0, le=2)

    rate_limit_per_minute: int = Field(default=20, ge=0, le=1000)
    max_message_chars: int = Field(default=2000, ge=1, le=20000)
    frontend_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def llm_configured(self) -> bool:
        if self.llm_api_key is None:
            return False
        return bool(self.llm_api_key.get_secret_value().strip())

    @property
    def frontend_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.frontend_origins.split(",")
            if origin.strip()
        ]

    def validate_startup(self) -> None:
        if not self.llm_configured:
            return

        parsed = urlparse(self.llm_base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("LLM_BASE_URL 必须是合法的 http(s) 地址")
        if not self.llm_model.strip():
            raise ValueError("LLM_MODEL 不能为空")


@lru_cache
def get_settings() -> Settings:
    return Settings()
