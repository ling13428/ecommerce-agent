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
    llm_fallback_api_key: SecretStr | None = None
    llm_fallback_base_url: str = ""
    llm_fallback_model: str = ""
    llm_circuit_failures: int = Field(default=3, ge=1, le=100)
    llm_circuit_cooldown: float = Field(default=60.0, ge=1, le=3600)

    agent_engine: str = "graph"
    agent_checkpoint_backend: str = "sqlite"
    agent_checkpoint_db_path: str = str(
        BASE_DIR / "data" / "sessions" / "checkpoints.db"
    )

    cache_backend: str = "memory"
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = Field(default=100, ge=1, le=1000)
    session_ttl_seconds: int = Field(default=7 * 24 * 3600, ge=60)

    router_llm_enabled: bool = True
    router_llm_min_confidence: float = Field(default=0.7, ge=0, le=1)
    router_llm_timeout: float = Field(default=3.0, gt=0, le=30)
    router_llm_max_tokens: int = Field(default=200, ge=32, le=1024)

    embedding_api_key: SecretStr | None = None
    embedding_base_url: str = (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = Field(default=1024, ge=1, le=4096)
    embedding_batch_size: int = Field(default=10, ge=1, le=64)
    embedding_timeout: float = Field(default=30.0, gt=0, le=300)

    ocr_api_key: SecretStr | None = None
    ocr_base_url: str = ""
    ocr_model: str = "qwen-vl-ocr"
    ocr_timeout: float = Field(default=60.0, gt=0, le=300)

    admin_token: SecretStr | None = None
    auth_secret: SecretStr | None = None
    buyer_token_ttl_hours: int = Field(default=24, ge=1, le=720)
    sms_provider: str = "console"
    sms_debug: bool = True
    otp_ttl_seconds: int = Field(default=300, ge=60, le=1800)
    otp_max_attempts: int = Field(default=5, ge=1, le=20)
    otp_send_cooldown: int = Field(default=60, ge=1, le=600)

    database_url: str = "postgresql://rag:rag@localhost:5433/ecommerce_rag"
    database_pool_max_size: int = Field(default=10, ge=1, le=100)
    database_pool_timeout: float = Field(default=5.0, gt=0, le=60)
    database_async_pool_min_size: int = Field(default=1, ge=1, le=50)
    database_async_pool_max_size: int = Field(default=20, ge=1, le=200)
    database_async_pool_timeout: float = Field(default=5.0, gt=0, le=60)
    orders_workers: int = Field(default=4, ge=1, le=32)
    audit_workers: int = Field(default=2, ge=1, le=16)
    orders_backend: str = "sqlite"

    product_provider: str = "mock"
    order_provider: str = "mock"
    saleor_rollout_percent: int = Field(default=100, ge=0, le=100)
    saleor_allowlist: str = ""
    saleor_api_url: str = "http://127.0.0.1:8001/graphql/"
    saleor_channel: str = "emberfox"
    saleor_token: SecretStr | None = None
    saleor_email: str = ""
    saleor_password: SecretStr | None = None
    saleor_timeout: float = Field(default=5.0, gt=0, le=60)
    rag_min_score: float = Field(default=0.55, ge=0, le=1)
    rag_hybrid_enabled: bool = True
    rag_sparse_candidates: int = Field(default=40, ge=1, le=200)
    rag_rrf_k: int = Field(default=60, ge=1, le=1000)
    rag_bm25_index_ttl: float = Field(default=300.0, ge=0, le=86400)

    rerank_enabled: bool = False
    rerank_model: str = "BAAI/bge-reranker-base"
    rerank_device: str = "cpu"
    rerank_top_n: int = Field(default=20, ge=1, le=100)
    rerank_batch_size: int = Field(default=8, ge=1, le=64)
    rerank_max_chars: int = Field(default=1500, ge=100, le=8000)

    session_persistence: bool = True
    session_db_path: str = str(BASE_DIR / "data" / "sessions" / "sessions.db")
    session_store_backend: str = "sqlite"
    session_storage_mode: str = "normalized"
    session_retention_days: int = Field(default=30, ge=1, le=3650)
    session_idle_timeout_minutes: int = Field(default=30, ge=1, le=1440)
    session_lock_timeout_seconds: float = Field(default=5.0, gt=0, le=120)
    session_lock_ttl_seconds: int = Field(default=60, ge=5, le=600)
    session_version_strict: bool = True
    session_db_pool_min_size: int = Field(default=1, ge=1, le=50)
    session_db_pool_max_size: int = Field(default=20, ge=1, le=200)
    session_db_pool_timeout: float = Field(default=5.0, gt=0, le=60)
    session_sqlite_workers: int = Field(default=4, ge=1, le=32)
    audit_enabled: bool = True

    tool_backend: str = "local"
    tool_secret: SecretStr | None = None
    tool_context_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    tool_approval_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    mcp_timeout: float = Field(default=10.0, gt=0, le=120)
    mcp_commerce_url: str = "http://127.0.0.1:9101/mcp"
    mcp_catalog_url: str = "http://127.0.0.1:9102/mcp"
    mcp_knowledge_url: str = "http://127.0.0.1:9103/mcp"
    tool_timeout: float = Field(default=15.0, gt=0, le=300)
    tool_max_workers: int = Field(default=16, ge=1, le=256)
    tool_max_concurrency_per_tool: int = Field(default=8, ge=1, le=256)
    tool_retry_attempts: int = Field(default=2, ge=1, le=5)
    tool_retry_backoff: float = Field(default=0.2, ge=0, le=10)
    tool_circuit_failures: int = Field(default=5, ge=1, le=100)
    tool_circuit_cooldown: float = Field(default=30.0, ge=1, le=3600)
    tool_result_max_chars: int = Field(default=24000, ge=1000, le=200000)
    tool_result_string_max_chars: int = Field(
        default=4000, ge=100, le=50000
    )
    tool_result_list_max_items: int = Field(default=50, ge=1, le=1000)
    tool_idempotency_ttl_seconds: int = Field(
        default=24 * 60 * 60, ge=60, le=30 * 24 * 3600
    )
    tool_idempotency_uncertain_ttl_seconds: int = Field(
        default=300, ge=10, le=24 * 3600
    )
    tool_idempotency_max_entries: int = Field(default=5000, ge=1)
    tool_idempotency_lock_ttl_seconds: int = Field(
        default=60, ge=5, le=3600
    )

    log_format: str = "text"
    alert_webhook_url: str = ""
    sse_heartbeat_seconds: float = Field(default=15.0, ge=0, le=120)
    rate_limit_per_minute: int = Field(default=20, ge=0, le=1000)
    max_message_chars: int = Field(default=2000, ge=1, le=20000)
    frontend_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def llm_configured(self) -> bool:
        if self.llm_api_key is None:
            return False
        return bool(self.llm_api_key.get_secret_value().strip())

    @property
    def llm_fallback_configured(self) -> bool:
        if self.llm_fallback_api_key is None:
            return False
        return bool(self.llm_fallback_api_key.get_secret_value().strip())

    @property
    def admin_token_value(self) -> str:
        if self.admin_token is None:
            return ""
        return self.admin_token.get_secret_value().strip()

    @property
    def auth_secret_value(self) -> str:
        if self.auth_secret is None:
            return ""
        return self.auth_secret.get_secret_value().strip()

    @property
    def tool_secret_value(self) -> str:
        if self.tool_secret is not None:
            value = self.tool_secret.get_secret_value().strip()
            if value:
                return value
        return self.auth_secret_value

    @property
    def embedding_configured(self) -> bool:
        if self.embedding_api_key is None:
            return False
        return bool(self.embedding_api_key.get_secret_value().strip())

    @property
    def effective_ocr_api_key(self) -> SecretStr | None:
        if self.ocr_api_key is not None and self.ocr_api_key.get_secret_value().strip():
            return self.ocr_api_key
        return self.embedding_api_key

    @property
    def effective_ocr_base_url(self) -> str:
        return self.ocr_base_url.strip() or self.embedding_base_url

    @property
    def ocr_configured(self) -> bool:
        key = self.effective_ocr_api_key
        return bool(key is not None and key.get_secret_value().strip())

    @property
    def frontend_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.frontend_origins.split(",")
            if origin.strip()
        ]

    def validate_startup(self) -> None:
        if (self.agent_engine or "").strip().lower() not in {"graph", "legacy"}:
            raise ValueError("AGENT_ENGINE 必须是 graph 或 legacy")
        if (self.agent_checkpoint_backend or "").strip().lower() not in {
            "sqlite",
            "postgres",
            "memory",
        }:
            raise ValueError(
                "AGENT_CHECKPOINT_BACKEND 必须是 sqlite、postgres 或 memory"
            )
        if (self.log_format or "").strip().lower() not in {"text", "json"}:
            raise ValueError("LOG_FORMAT 必须是 text 或 json")
        if (self.session_store_backend or "").strip().lower() not in {
            "sqlite",
            "postgres",
        }:
            raise ValueError("SESSION_STORE_BACKEND 必须是 sqlite 或 postgres")
        if (self.session_storage_mode or "").strip().lower() not in {
            "normalized",
            "payload",
        }:
            raise ValueError("SESSION_STORAGE_MODE 必须是 normalized 或 payload")
        if (self.cache_backend or "").strip().lower() not in {
            "memory",
            "redis",
        }:
            raise ValueError("CACHE_BACKEND 必须是 memory 或 redis")
        if (self.cache_backend or "").strip().lower() == "redis":
            parsed_redis = urlparse(self.redis_url)
            if parsed_redis.scheme not in ("redis", "rediss"):
                raise ValueError("REDIS_URL 必须以 redis:// 或 rediss:// 开头")
        if (self.tool_backend or "").strip().lower() not in {"local", "mcp"}:
            raise ValueError("TOOL_BACKEND 必须是 local 或 mcp")
        if (self.tool_backend or "").strip().lower() == "mcp" and not self.tool_secret_value:
            raise ValueError("TOOL_BACKEND=mcp 时必须配置 TOOL_SECRET 或 AUTH_SECRET")
        for name, url in (
            ("MCP_COMMERCE_URL", self.mcp_commerce_url),
            ("MCP_CATALOG_URL", self.mcp_catalog_url),
            ("MCP_KNOWLEDGE_URL", self.mcp_knowledge_url),
        ):
            parsed_mcp = urlparse(url)
            if parsed_mcp.scheme not in ("http", "https") or not parsed_mcp.netloc:
                raise ValueError(f"{name} 必须是合法的 http(s) 地址")

        if self.llm_configured:
            parsed = urlparse(self.llm_base_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("LLM_BASE_URL 必须是合法的 http(s) 地址")
            if not self.llm_model.strip():
                raise ValueError("LLM_MODEL 不能为空")

        if self.embedding_configured:
            parsed = urlparse(self.embedding_base_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("EMBEDDING_BASE_URL 必须是合法的 http(s) 地址")
            if not self.embedding_model.strip():
                raise ValueError("EMBEDDING_MODEL 不能为空")

        if self.ocr_configured:
            parsed = urlparse(self.effective_ocr_base_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("OCR_BASE_URL 必须是合法的 http(s) 地址")
            if not self.ocr_model.strip():
                raise ValueError("OCR_MODEL 不能为空")

        if self.rerank_enabled and not self.rerank_model.strip():
            raise ValueError("RERANK_MODEL 不能为空")

        parsed_db = urlparse(self.database_url)
        if parsed_db.scheme not in ("postgresql", "postgres"):
            raise ValueError("DATABASE_URL 必须以 postgresql:// 开头")
        if (self.orders_backend or "").strip().lower() not in {
            "sqlite",
            "postgres",
        }:
            raise ValueError("ORDERS_BACKEND 必须是 sqlite 或 postgres")
        if (self.product_provider or "").strip().lower() not in {
            "mock",
            "saleor",
        }:
            raise ValueError("PRODUCT_PROVIDER 必须是 mock 或 saleor")
        if (self.order_provider or "").strip().lower() not in {
            "mock",
            "saleor",
        }:
            raise ValueError("ORDER_PROVIDER 必须是 mock 或 saleor")
        if (
            self.product_provider or ""
        ).strip().lower() == "saleor" or (
            self.order_provider or ""
        ).strip().lower() == "saleor":
            parsed_saleor = urlparse(self.saleor_api_url)
            if parsed_saleor.scheme not in ("http", "https"):
                raise ValueError("SALEOR_API_URL 必须是合法的 http(s) 地址")
            has_token = bool(
                self.saleor_token
                and self.saleor_token.get_secret_value().strip()
            )
            has_password = bool(
                self.saleor_email
                and self.saleor_password
                and self.saleor_password.get_secret_value().strip()
            )
            if not has_token and not has_password:
                raise ValueError(
                    "SALEOR_TOKEN 或 SALEOR_EMAIL/SALEOR_PASSWORD 必须配置一个"
                )


@lru_cache
def get_settings() -> Settings:
    return Settings()
