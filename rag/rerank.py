from __future__ import annotations

import logging
import threading

from core.config import get_settings

logger = logging.getLogger("ecommerce_agent.rerank")

_model_lock = threading.Lock()
_predict_lock = threading.Lock()
_models: dict[tuple[str, str], object] = {}
_failed_models: set[tuple[str, str]] = set()


def _get_model(model_name: str, device: str):
    key = (model_name, device)
    with _model_lock:
        cached = _models.get(key)
        if cached is not None:
            return cached
        if key in _failed_models:
            return None
        try:
            from sentence_transformers import CrossEncoder

            model = CrossEncoder(model_name, device=device, max_length=512)
        except Exception as exc:
            logger.warning(
                "CrossEncoder 加载失败，rerank 已跳过：%s（模型 %s）",
                exc,
                model_name,
            )
            _failed_models.add(key)
            return None
        _models[key] = model
        logger.info("CrossEncoder 已加载：%s（device=%s）", model_name, device)
        return model


def rerank_documents(
    query: str,
    documents: list[str],
    *,
    top_n: int | None = None,
) -> list[tuple[int, float]] | None:
    settings = get_settings()
    if not settings.rerank_enabled or not documents:
        return None

    limit = top_n or settings.rerank_top_n
    pairs = [
        (query, document[: settings.rerank_max_chars])
        for document in documents[:limit]
    ]
    model = _get_model(settings.rerank_model, settings.rerank_device)
    if model is None:
        return None

    try:
        with _predict_lock:
            scores = model.predict(
                pairs,
                batch_size=settings.rerank_batch_size,
                show_progress_bar=False,
            )
    except Exception as exc:
        logger.warning("CrossEncoder 打分失败，保留 RRF 排序：%s", exc)
        return None

    ranked = sorted(
        enumerate(float(score) for score in scores),
        key=lambda item: item[1],
        reverse=True,
    )
    return ranked
