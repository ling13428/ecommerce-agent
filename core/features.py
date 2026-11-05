from __future__ import annotations

import hashlib

from core.config import get_settings


def saleor_enabled(buyer_id: str | None) -> bool:
    settings = get_settings()
    if (settings.order_provider or "").strip().lower() != "saleor":
        return False

    allowlist = {
        item.strip().upper()
        for item in (settings.saleor_allowlist or "").split(",")
        if item.strip()
    }
    if allowlist:
        return bool(buyer_id and buyer_id.strip().upper() in allowlist)

    percent = settings.saleor_rollout_percent
    if percent >= 100:
        return True
    if percent <= 0 or not buyer_id:
        return False

    digest = hashlib.sha256(
        buyer_id.strip().upper().encode("utf-8")
    ).hexdigest()
    bucket = int(digest[:8], 16) % 100
    return bucket < percent
