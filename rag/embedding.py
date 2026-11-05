from __future__ import annotations

import logging
import time
from functools import lru_cache

from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

from core.config import get_settings

logger = logging.getLogger("ecommerce_agent.embedding")

RETRYABLE_ERRORS = (
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
    InternalServerError,
)


class EmbeddingError(RuntimeError):
    pass


@lru_cache
def get_embedding_client() -> OpenAI:
    settings = get_settings()
    api_key = settings.embedding_api_key
    if not settings.embedding_configured or api_key is None:
        raise EmbeddingError("EMBEDDING_API_KEY 未配置")
    return OpenAI(
        api_key=api_key.get_secret_value(),
        base_url=settings.embedding_base_url,
        timeout=settings.embedding_timeout,
        max_retries=0,
    )


def _embed_batch(
    client: OpenAI,
    texts: list[str],
    model: str,
    dimension: int,
    max_retries: int,
    retry_delay: float,
) -> list[list[float]]:
    last_error: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            response = client.embeddings.create(model=model, input=texts)
            items = sorted(
                response.data, key=lambda item: getattr(item, "index", 0)
            )
            if len(items) != len(texts):
                raise EmbeddingError(
                    f"embedding 返回数量不匹配：请求 {len(texts)}，返回 {len(items)}"
                )
            vectors = [list(item.embedding) for item in items]
            for vector in vectors:
                if len(vector) != dimension:
                    raise EmbeddingError(
                        f"embedding 维度不匹配：期望 {dimension}，实际 {len(vector)}"
                    )
            return vectors
        except RETRYABLE_ERRORS as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            delay = retry_delay * (2**attempt)
            logger.warning(
                "embedding 请求失败，%.1fs 后重试（%d/%d）：%s",
                delay,
                attempt + 1,
                max_retries,
                type(exc).__name__,
            )
            time.sleep(delay)
    raise EmbeddingError(
        f"embedding 请求失败：{type(last_error).__name__}: {last_error}"
    ) from last_error


def embed_texts(
    texts: list[str],
    client: OpenAI | None = None,
    batch_size: int | None = None,
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> list[list[float]]:
    if not texts:
        return []

    settings = get_settings()
    model = settings.embedding_model
    dimension = settings.embedding_dim
    size = batch_size or settings.embedding_batch_size
    if size < 1:
        raise EmbeddingError("batch_size 必须大于 0")

    for index, text in enumerate(texts):
        if not text or not text.strip():
            raise EmbeddingError(f"第 {index} 条文本为空，不能生成 embedding")

    active_client = client or get_embedding_client()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), size):
        batch = texts[start : start + size]
        vectors.extend(
            _embed_batch(
                active_client,
                batch,
                model,
                dimension,
                max_retries,
                retry_delay,
            )
        )
    return vectors


def embed_query(text: str, client: OpenAI | None = None) -> list[float]:
    vectors = embed_texts([text], client=client)
    return vectors[0]
