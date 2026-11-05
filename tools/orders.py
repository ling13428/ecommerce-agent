from __future__ import annotations

from typing import Any

from services import orders as order_service
from tools.context import ToolContext

NO_BUYER_MESSAGE = "当前会话还没有绑定买家，请先在页面上方输入买家 ID，例如 BUY-0001。"
UNKNOWN_BUYER_MESSAGE = "没有找到该买家，请检查买家 ID，例如 BUY-0001。"
NOT_FOUND_MESSAGE = "没有查到该订单。请确认订单号是否正确，以及是否属于当前买家。"


def _missing_buyer(context: ToolContext | None) -> dict[str, Any]:
    buyer_id = context.buyer_id if context is not None else None
    message = NO_BUYER_MESSAGE if not buyer_id else UNKNOWN_BUYER_MESSAGE
    return {"found": False, "message": message}


def _buyer_payload(buyer_id: str | None) -> dict[str, Any] | None:
    buyer = order_service.get_buyer(buyer_id)
    if buyer is None:
        return None
    return {
        "buyer_id": buyer["buyer_id"],
        "nickname": buyer["nickname"],
        "member_level": buyer["member_level"],
        "city": buyer["city"],
    }


def get_order(
    order_id: str | None = None,
    *,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    buyer_id = context.buyer_id if context is not None else None
    buyer = _buyer_payload(buyer_id)
    if buyer is None:
        return _missing_buyer(context)

    if order_id:
        order = order_service.get_order(order_id, buyer_id)
        if order is None:
            return {"found": False, "message": NOT_FOUND_MESSAGE, "buyer": buyer}
        return {"found": True, "buyer": buyer, "order": order}

    orders = order_service.list_orders(buyer_id)
    if not orders:
        return {
            "found": False,
            "message": "当前买家名下没有订单，请确认买家 ID 是否正确。",
            "buyer": buyer,
        }
    return {
        "found": True,
        "buyer": buyer,
        "count": len(orders),
        "orders": orders,
        "message": f"找到最近 {len(orders)} 笔订单。",
    }


def get_logistics(
    order_id: str | None = None,
    tracking_no: str | None = None,
    *,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    buyer_id = context.buyer_id if context is not None else None
    buyer = _buyer_payload(buyer_id)
    if buyer is None:
        return _missing_buyer(context)

    if order_id or tracking_no:
        shipment = order_service.get_shipment(
            buyer_id, order_id=order_id, tracking_no=tracking_no
        )
        if shipment is None:
            return {
                "found": False,
                "message": "没有查到对应的物流信息，请确认订单号或物流单号。",
                "buyer": buyer,
            }
        return {"found": True, "buyer": buyer, "shipment": shipment}

    shipments = order_service.list_shipments(buyer_id)
    if not shipments:
        return {
            "found": False,
            "message": "当前买家没有可查询的物流记录。",
            "buyer": buyer,
        }
    return {
        "found": True,
        "buyer": buyer,
        "count": len(shipments),
        "shipments": shipments,
        "message": f"找到最近 {len(shipments)} 条物流记录。",
    }


def get_aftersale(
    order_id: str | None = None,
    *,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    buyer_id = context.buyer_id if context is not None else None
    buyer = _buyer_payload(buyer_id)
    if buyer is None:
        return _missing_buyer(context)

    if order_id:
        aftersale = order_service.get_aftersale(order_id, buyer_id)
        if aftersale is None:
            return {
                "found": False,
                "message": "该订单没有售后记录，或订单号不属于当前买家。",
                "buyer": buyer,
            }
        return {"found": True, "buyer": buyer, "aftersale": aftersale}

    aftersales = order_service.list_aftersales(buyer_id)
    if not aftersales:
        return {
            "found": False,
            "message": "当前买家没有售后记录。",
            "buyer": buyer,
        }
    return {
        "found": True,
        "buyer": buyer,
        "count": len(aftersales),
        "aftersales": aftersales,
        "message": f"找到最近 {len(aftersales)} 条售后记录。",
    }


def cancel_order(
    order_id: str,
    *,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    buyer_id = context.buyer_id if context is not None else None
    buyer = _buyer_payload(buyer_id)
    if buyer is None:
        return _missing_buyer(context)
    result = order_service.cancel_order(order_id, buyer_id)
    return {**result, "buyer": buyer}


def update_address(
    order_id: str,
    address: str,
    *,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    buyer_id = context.buyer_id if context is not None else None
    buyer = _buyer_payload(buyer_id)
    if buyer is None:
        return _missing_buyer(context)
    result = order_service.update_address(order_id, buyer_id, address)
    return {**result, "buyer": buyer}


def intercept_parcel(
    order_id: str,
    reason: str = "买家申请拦截",
    *,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    buyer_id = context.buyer_id if context is not None else None
    buyer = _buyer_payload(buyer_id)
    if buyer is None:
        return _missing_buyer(context)
    result = order_service.intercept_parcel(order_id, buyer_id, reason)
    return {**result, "buyer": buyer}


def create_aftersale(
    order_id: str,
    aftersale_type: str,
    reason: str = "买家申请售后",
    description: str = "",
    *,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    buyer_id = context.buyer_id if context is not None else None
    buyer = _buyer_payload(buyer_id)
    if buyer is None:
        return _missing_buyer(context)
    result = order_service.create_aftersale(
        order_id, buyer_id, aftersale_type, reason, description
    )
    return {**result, "buyer": buyer}
