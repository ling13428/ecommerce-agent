from __future__ import annotations

from typing import Any

from mcp_servers.common import build_server, context_from_token, run_write
from tools import commerce as commerce_tools
from tools import orders as order_tools

INSTRUCTIONS = (
    "电商订单、物流、售后、支付与优惠券能力。所有查询和写操作都必须携带"
    "工具上下文令牌；写操作还必须携带 orchestrator 签发的审批令牌。"
)


def _context(context_token: str | None):
    return context_from_token(context_token)


def get_order(
    order_id: str | None = None,
    context_token: str | None = None,
) -> dict[str, Any]:
    return order_tools.get_order(order_id, context=_context(context_token))


def get_logistics(
    order_id: str | None = None,
    tracking_no: str | None = None,
    context_token: str | None = None,
) -> dict[str, Any]:
    return order_tools.get_logistics(
        order_id, tracking_no, context=_context(context_token)
    )


def get_aftersale(
    order_id: str | None = None,
    context_token: str | None = None,
) -> dict[str, Any]:
    return order_tools.get_aftersale(order_id, context=_context(context_token))


def get_payment_methods(
    order_id: str | None = None,
    context_token: str | None = None,
) -> dict[str, Any]:
    return commerce_tools.get_payment_methods(
        order_id, context=_context(context_token)
    )


def get_coupons(
    active_only: bool = True,
    context_token: str | None = None,
) -> dict[str, Any]:
    return commerce_tools.get_coupons(
        active_only, context=_context(context_token)
    )


def cancel_order(
    order_id: str,
    approval_token: str | None = None,
    context_token: str | None = None,
) -> dict[str, Any]:
    context = _context(context_token)
    return run_write(
        "cancel_order",
        {"order_id": order_id},
        approval_token,
        lambda: order_tools.cancel_order(order_id, context=context),
        context=context,
    )


def update_address(
    order_id: str,
    address: str,
    approval_token: str | None = None,
    context_token: str | None = None,
) -> dict[str, Any]:
    context = _context(context_token)
    return run_write(
        "update_address",
        {"order_id": order_id, "address": address},
        approval_token,
        lambda: order_tools.update_address(order_id, address, context=context),
        context=context,
    )


def intercept_parcel(
    order_id: str,
    reason: str = "买家申请拦截",
    approval_token: str | None = None,
    context_token: str | None = None,
) -> dict[str, Any]:
    context = _context(context_token)
    return run_write(
        "intercept_parcel",
        {"order_id": order_id, "reason": reason},
        approval_token,
        lambda: order_tools.intercept_parcel(order_id, reason, context=context),
        context=context,
    )


def create_aftersale(
    order_id: str,
    aftersale_type: str,
    reason: str,
    description: str = "",
    approval_token: str | None = None,
    context_token: str | None = None,
) -> dict[str, Any]:
    context = _context(context_token)
    return run_write(
        "create_aftersale",
        {
            "order_id": order_id,
            "aftersale_type": aftersale_type,
            "reason": reason,
            "description": description,
        },
        approval_token,
        lambda: order_tools.create_aftersale(
            order_id,
            aftersale_type,
            reason,
            description,
            context=context,
        ),
        context=context,
    )


def build(host: str = "127.0.0.1", port: int = 9101):
    server = build_server(
        "commerce", instructions=INSTRUCTIONS, host=host, port=port
    )
    for tool in (
        get_order,
        get_logistics,
        get_aftersale,
        get_payment_methods,
        get_coupons,
        cancel_order,
        update_address,
        intercept_parcel,
        create_aftersale,
    ):
        server.add_tool(tool)
    return server
