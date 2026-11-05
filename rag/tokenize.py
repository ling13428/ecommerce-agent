from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("ecommerce_agent.tokenize")

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+")
_MODEL_RE = re.compile(r"[a-z]+\d+[a-z0-9]*")

_jieba: Any | None = None
_jieba_failed = False


def _get_jieba():
    global _jieba, _jieba_failed
    if _jieba is not None or _jieba_failed:
        return _jieba
    try:
        import jieba

        jieba.setLogLevel(logging.WARNING)
        _jieba = jieba
    except ImportError:
        logger.info("未安装 jieba，中文按二元组切分；可选 pip install jieba")
        _jieba_failed = True
    return _jieba


def _expand_token(raw: str) -> list[str]:
    token = raw.strip()
    if not token or not re.search(r"[a-z0-9\u4e00-\u9fff]", token):
        return []
    tokens = [token]
    if _MODEL_RE.fullmatch(token):
        tokens.extend(re.findall(r"[a-z]+|\d+", token))
    return tokens


def _fallback_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        if _CJK_RE.fullmatch(raw) and len(raw) > 1:
            tokens.extend(raw[index : index + 2] for index in range(len(raw) - 1))
            tokens.append(raw)
        else:
            tokens.extend(_expand_token(raw))
    return tokens


def tokenize(text: str) -> list[str]:
    normalized = text.lower()
    jieba = _get_jieba()
    if jieba is None:
        return _fallback_tokens(normalized)

    tokens: list[str] = []
    for raw in jieba.cut_for_search(normalized):
        tokens.extend(_expand_token(raw))
    return tokens
