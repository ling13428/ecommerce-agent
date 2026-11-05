from __future__ import annotations

import logging

from core.config import get_settings
from core.otp import mask_phone

logger = logging.getLogger("ecommerce_agent.sms")


def send_verification_code(phone: str, code: str) -> None:
    settings = get_settings()
    provider = (settings.sms_provider or "console").strip().lower()
    masked = mask_phone(phone)

    if provider == "console":
        visible = code if settings.sms_debug else "******"
        logger.info("SMS(console) to=%s code=%s", masked, visible)
        return

    logger.warning(
        "SMS provider=%s 未实现，验证码未发送（to=%s）", provider, masked
    )
