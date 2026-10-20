from __future__ import annotations

import logging

from core.security import redact

logger = logging.getLogger("ecommerce_agent")


def setup_logging() -> None:
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )


def log_exception(context: str, exc: BaseException) -> None:
    message = redact(f"{type(exc).__name__}: {exc}")
    logger.error("%s | %s", context, message)
