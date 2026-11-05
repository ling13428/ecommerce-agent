from __future__ import annotations

import logging
import threading
from typing import Any

import httpx

from core.config import get_settings
from core.security import redact

logger = logging.getLogger("ecommerce_agent.alerts")


def _post(url: str, payload: dict[str, Any]) -> None:
    try:
        httpx.post(url, json=payload, timeout=5)
    except Exception as exc:
        logger.warning("告警 Webhook 发送失败：%s", exc)


def send_alert(kind: str, message: str, **fields: Any) -> None:
    payload = {
        "kind": kind,
        "message": redact(message),
        "fields": {key: redact(str(value)) for key, value in fields.items()},
    }
    logger.error("ALERT %s | %s | %s", kind, payload["message"], payload["fields"])

    url = (getattr(get_settings(), "alert_webhook_url", "") or "").strip()
    if not url:
        return
    threading.Thread(target=_post, args=(url, payload), daemon=True).start()
