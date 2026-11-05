from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from core.config import get_settings
from services.saleor_client import SaleorError, get_saleor_client

logger = logging.getLogger("ecommerce_agent.saleor.orders")

_ORDER_FIELDS = """
    id
    number
    externalReference
    status
    created
    total { gross { amount currency } }
    user { email }
    metadata { key value }
    lines {
      productName
      quantity
      variant { sku name }
      unitPrice { gross { amount } }
      totalPrice { gross { amount } }
    }
    fulfillments {
      id
      status
      trackingNumber
      created
      lines {
        quantity
        orderLine { productName variant { sku name } }
      }
    }
"""

_ORDER_QUERY = (
    "query($ref: String!) { order(externalReference: $ref) {"
    + _ORDER_FIELDS
    + "} }"
)

_ORDERS_QUERY = (
    "query($email: String!, $first: Int!) {"
    " orders(first: $first, filter: {customer: $email},"
    " sortBy: {field: CREATED_AT, direction: DESC}) {"
    " edges { node {"
    + _ORDER_FIELDS
    + "} } } }"
)

_STATUS_LABELS = {
    "canceled": "已取消",
    "pending_payment": "待付款",
    "paid": "已付款",
    "shipped": "已发货",
    "in_transit": "运输中",
    "delivered": "已签收",
    "completed": "已完成",
    "refunding": "退款中",
    "aftersale_processing": "售后处理中",
    "intercepting": "拦截中",
    "exception": "物流异常",
}


def _number(value: Any) -> float | int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return int(number) if number.is_integer() else number


def _metadata(node: dict[str, Any]) -> dict[str, str]:
    return {
        str(item.get("key")): str(item.get("value"))
        for item in node.get("metadata") or []
        if item.get("key")
    }


def _tracking(node: dict[str, Any]) -> str:
    fulfillments = node.get("fulfillments") or []
    return str(fulfillments[0].get("trackingNumber") or "") if fulfillments else ""


def _map_order(node: dict[str, Any]) -> dict[str, Any]:
    meta = _metadata(node)
    lines = node.get("lines") or []
    items: list[dict[str, Any]] = []
    for line in lines:
        variant = line.get("variant") or {}
        quantity = int(line.get("quantity") or 0)
        unit_price = _number(
            ((line.get("unitPrice") or {}).get("gross") or {}).get("amount")
        )
        subtotal = _number(
            ((line.get("totalPrice") or {}).get("gross") or {}).get("amount")
        )
        if not subtotal:
            subtotal = _number(unit_price * quantity)
        items.append(
            {
                "product_id": variant.get("sku"),
                "model": variant.get("name"),
                "name": line.get("productName"),
                "quantity": quantity,
                "unit_price": unit_price,
                "subtotal": subtotal,
            }
        )

    payable = _number(
        ((node.get("total") or {}).get("gross") or {}).get("amount")
    )
    status = meta.get("legacy_status") or "unknown"
    return {
        "order_id": node.get("externalReference") or str(node.get("number")),
        "buyer_id": meta.get("buyer_id"),
        "status": status,
        "status_label": meta.get("legacy_status_label")
        or _STATUS_LABELS.get(status, status),
        "item_count": sum(item["quantity"] for item in items),
        "amount": payable,
        "discount": 0,
        "shipping_fee": 0,
        "payable": payable,
        "payment_method": meta.get("payment_method") or "",
        "created_at": node.get("created"),
        "paid_at": meta.get("paid_at") or "",
        "shipped_at": meta.get("shipped_at") or "",
        "delivered_at": meta.get("delivered_at") or "",
        "canceled_at": meta.get("canceled_at") or "",
        "tracking_no": meta.get("tracking_no") or _tracking(node),
        "carrier": meta.get("carrier") or "",
        "expected_delivery": meta.get("expected_delivery") or "",
        "address": {},
        "address_text": meta.get("address_text") or "",
        "aftersale_id": meta.get("aftersale_id") or None,
        "remark": meta.get("remark") or "",
        "source": "saleor",
        "items": items,
    }


def _owner_matches(node: dict[str, Any], buyer_id: str) -> bool:
    meta = _metadata(node)
    owner = meta.get("buyer_id")
    if not owner:
        email = str((node.get("user") or {}).get("email") or "")
        owner = email.split("@")[0].upper() if "@" in email else ""
    return owner.upper() == buyer_id.upper()


def _map_shipments(node: dict[str, Any]) -> list[dict[str, Any]]:
    meta = _metadata(node)
    order_id = node.get("externalReference") or str(node.get("number"))
    status = meta.get("legacy_status") or "unknown"
    status_label = meta.get("legacy_status_label") or _STATUS_LABELS.get(
        status, status
    )
    shipments: list[dict[str, Any]] = []
    for fulfillment in node.get("fulfillments") or []:
        items = []
        for line in fulfillment.get("lines") or []:
            order_line = line.get("orderLine") or {}
            variant = order_line.get("variant") or {}
            items.append(
                {
                    "product_id": variant.get("sku"),
                    "model": variant.get("name"),
                    "quantity": int(line.get("quantity") or 0),
                }
            )
        shipments.append(
            {
                "tracking_no": fulfillment.get("trackingNumber")
                or meta.get("tracking_no")
                or "",
                "order_id": order_id,
                "carrier": meta.get("carrier") or "",
                "status": status,
                "status_label": status_label,
                "current_node": status_label,
                "expected_delivery": meta.get("expected_delivery") or "",
                "updated_at": meta.get("delivered_at")
                or fulfillment.get("created"),
                "events": [
                    {
                        "time": fulfillment.get("created"),
                        "status": status_label,
                        "description": "物流已创建/发货",
                        "location": "",
                    }
                ],
                "items": items,
            }
        )
    if not shipments and meta.get("tracking_no"):
        shipments.append(
            {
                "tracking_no": meta["tracking_no"],
                "order_id": order_id,
                "carrier": meta.get("carrier") or "",
                "status": status,
                "status_label": status_label,
                "current_node": status_label,
                "expected_delivery": meta.get("expected_delivery") or "",
                "updated_at": meta.get("delivered_at") or "",
                "events": [],
                "items": [
                    {
                        "product_id": item.get("product_id"),
                        "model": item.get("model"),
                        "quantity": item.get("quantity"),
                    }
                    for item in _map_order(node).get("items") or []
                ],
            }
        )
    return shipments


def get_saleor_shipment(
    buyer_id: str | None,
    *,
    order_id: str | None = None,
    tracking_no: str | None = None,
) -> dict[str, Any] | None:
    if not buyer_id:
        return None
    if order_id:
        try:
            data = get_saleor_client().query(
                _ORDER_QUERY, {"ref": order_id.strip().upper()}
            )
        except (httpx.HTTPError, SaleorError) as exc:
            logger.warning("Saleor 物流查询失败：%s", exc)
            return None
        node = data.get("order")
        if not node or not _owner_matches(node, buyer_id):
            return None
        shipments = _map_shipments(node)
        if tracking_no:
            target = tracking_no.strip().upper()
            return next(
                (
                    item
                    for item in shipments
                    if str(item.get("tracking_no")).upper() == target
                ),
                None,
            )
        return shipments[0] if shipments else None

    if tracking_no:
        target = tracking_no.strip().upper()
        email = f"{buyer_id.lower()}@example.com"
        try:
            data = get_saleor_client().query(
                _ORDERS_QUERY, {"email": email, "first": 50}
            )
        except (httpx.HTTPError, SaleorError) as exc:
            logger.warning("Saleor 物流查询失败：%s", exc)
            return None
        for edge in (data.get("orders") or {}).get("edges") or []:
            node = edge.get("node") or {}
            if not _owner_matches(node, buyer_id):
                continue
            for shipment in _map_shipments(node):
                if str(shipment.get("tracking_no")).upper() == target:
                    return shipment
    return None


def list_saleor_shipments(
    buyer_id: str, limit: int = 5
) -> list[dict[str, Any]]:
    email = f"{buyer_id.lower()}@example.com"
    try:
        data = get_saleor_client().query(
            _ORDERS_QUERY, {"email": email, "first": 20}
        )
    except (httpx.HTTPError, SaleorError) as exc:
        logger.warning("Saleor 物流列表查询失败：%s", exc)
        return []
    shipments: list[dict[str, Any]] = []
    for edge in (data.get("orders") or {}).get("edges") or []:
        node = edge.get("node") or {}
        if not _owner_matches(node, buyer_id):
            continue
        shipments.extend(_map_shipments(node))
        if len(shipments) >= limit:
            break
    return shipments[:limit]


def _map_aftersale(node: dict[str, Any]) -> dict[str, Any] | None:
    meta = _metadata(node)
    if not meta.get("aftersale_id"):
        return None
    try:
        timeline = json.loads(meta.get("aftersale_timeline") or "[]")
    except (TypeError, json.JSONDecodeError):
        timeline = []
    return {
        "aftersale_id": meta["aftersale_id"],
        "order_id": meta.get("aftersale_order_id")
        or node.get("externalReference"),
        "buyer_id": meta.get("aftersale_buyer_id") or meta.get("buyer_id"),
        "type": meta.get("aftersale_type") or "",
        "reason": meta.get("aftersale_reason") or "",
        "status": meta.get("aftersale_status") or "",
        "status_label": meta.get("aftersale_status_label") or "",
        "created_at": meta.get("aftersale_created_at") or "",
        "updated_at": meta.get("aftersale_updated_at") or "",
        "refund_amount": _number(meta.get("aftersale_refund_amount")),
        "timeline": timeline,
        "source": "saleor",
    }


def get_saleor_aftersale(
    order_id: str, buyer_id: str | None
) -> dict[str, Any] | None:
    if not buyer_id:
        return None
    try:
        data = get_saleor_client().query(
            _ORDER_QUERY, {"ref": order_id.strip().upper()}
        )
    except (httpx.HTTPError, SaleorError) as exc:
        logger.warning("Saleor 售后查询失败：%s", exc)
        return None
    node = data.get("order")
    if not node or not _owner_matches(node, buyer_id):
        return None
    return _map_aftersale(node)


def list_saleor_aftersales(
    buyer_id: str, limit: int = 5
) -> list[dict[str, Any]]:
    email = f"{buyer_id.lower()}@example.com"
    try:
        data = get_saleor_client().query(
            _ORDERS_QUERY, {"email": email, "first": 50}
        )
    except (httpx.HTTPError, SaleorError) as exc:
        logger.warning("Saleor 售后列表查询失败：%s", exc)
        return []
    aftersales: list[dict[str, Any]] = []
    for edge in (data.get("orders") or {}).get("edges") or []:
        node = edge.get("node") or {}
        if not _owner_matches(node, buyer_id):
            continue
        aftersale = _map_aftersale(node)
        if aftersale is not None:
            aftersales.append(aftersale)
        if len(aftersales) >= limit:
            break
    return aftersales


def get_saleor_order(
    order_id: str, buyer_id: str | None
) -> dict[str, Any] | None:
    if not buyer_id:
        return None
    try:
        data = get_saleor_client().query(
            _ORDER_QUERY, {"ref": order_id.strip().upper()}
        )
    except (httpx.HTTPError, SaleorError) as exc:
        logger.warning("Saleor 订单查询失败：%s", exc)
        return None
    node = data.get("order")
    if not node or not _owner_matches(node, buyer_id):
        return None
    return _map_order(node)


def list_saleor_orders(
    buyer_id: str, limit: int = 5
) -> list[dict[str, Any]]:
    email = f"{buyer_id.lower()}@example.com"
    try:
        data = get_saleor_client().query(
            _ORDERS_QUERY, {"email": email, "first": min(limit, 100)}
        )
    except (httpx.HTTPError, SaleorError) as exc:
        logger.warning("Saleor 订单列表查询失败：%s", exc)
        return []
    edges = (data.get("orders") or {}).get("edges") or []
    return [
        _map_order(edge["node"])
        for edge in edges
        if edge.get("node")
    ]


def saleor_channel() -> str:
    return get_settings().saleor_channel
