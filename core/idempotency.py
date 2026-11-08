from __future__ import annotations

import hashlib
import json
from typing import Any

_MAX_KEY_LENGTH = 120


def _digest(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, ensure_ascii=False, default=str
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def business_idempotency_key(
    tool: str, args: dict[str, Any], buyer_id: str | None
) -> str:
    """Derive a deterministic key from the business meaning of a write.

    Retries of the same business action must map to the same key; a different
    order/address/aftersale type must map to a different one.
    """
    buyer = (buyer_id or "").strip().upper()
    order_id = str(args.get("order_id") or "").strip().upper()

    if tool == "cancel_order":
        key = f"cancel_order:{buyer}:{order_id}"
    elif tool == "update_address":
        address = str(args.get("address") or "").strip()
        key = f"update_address:{buyer}:{order_id}:{_digest(address)}"
    elif tool == "intercept_parcel":
        key = f"intercept_parcel:{buyer}:{order_id}"
    elif tool == "create_aftersale":
        aftersale_type = str(args.get("aftersale_type") or "").strip()
        key = f"create_aftersale:{buyer}:{order_id}:{aftersale_type}"
    else:
        key = f"{tool}:{buyer}:{_digest(args)}"
    return key[:_MAX_KEY_LENGTH]
