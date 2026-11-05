from __future__ import annotations

from typing import Any

from services import orders as order_service
from tools.context import ToolContext

NO_BUYER_MESSAGE = "当前会话还没有绑定买家，请先在页面上方输入买家 ID，例如 BUY-0001。"


def _buyer_payload(buyer_id: str | None) -> dict[str, Any] | None:
    buyer = order_service.get_buyer(buyer_id)
    if buyer is None:
        return None
    return {
        "buyer_id": buyer["buyer_id"],
        "nickname": buyer["nickname"],
        "member_level": buyer["member_level"],
    }


def get_payment_methods(
    order_id: str | None = None,
    *,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    buyer_id = context.buyer_id if context is not None else None
    payload = order_service.list_payment_methods(
        buyer_id, order_id=order_id
    )
    return {"found": True, **payload}


def get_coupons(
    active_only: bool = True,
    *,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    buyer_id = context.buyer_id if context is not None else None
    buyer = _buyer_payload(buyer_id)
    if buyer is None:
        return {
            "found": False,
            "message": NO_BUYER_MESSAGE,
        }
    coupons = order_service.list_coupons(buyer_id, active_only=active_only)
    if not coupons:
        return {
            "found": False,
            "message": (
                "当前买家没有可使用的优惠券。"
                if active_only
                else "当前买家没有优惠券记录。"
            ),
            "buyer": buyer,
        }
    return {
        "found": True,
        "buyer": buyer,
        "count": len(coupons),
        "coupons": coupons,
    }
