from __future__ import annotations

import json
import logging
import time

from core.config import get_settings
from core.security import redact

logger = logging.getLogger("ecommerce_agent")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.localtime(record.created)
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    settings = get_settings()
    handler = logging.StreamHandler()
    if (settings.log_format or "text").strip().lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s | %(message)s")
        )
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False


def log_exception(context: str, exc: BaseException) -> None:
    message = redact(f"{type(exc).__name__}: {exc}")
    logger.error("%s | %s", context, message)
