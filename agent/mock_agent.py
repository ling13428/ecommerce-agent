from __future__ import annotations

import re

from tools.products import get_product

PRODUCT_ID_PATTERN = re.compile(r"[Pp](\d{4})")


def find_product(message: str) -> tuple[dict | None, dict | None, str | None]:
    match = PRODUCT_ID_PATTERN.search(message)
    if match:
        product_id = f"P{match.group(1)}"
        result = get_product(product_id=product_id)
        if result["found"]:
            return result["product"], {"product_id": product_id}, None
        return None, {"product_id": product_id}, result["message"]

    result = get_product(name=message)
    if result["found"]:
        return result["product"], {"name": message}, None

    return None, None, None


def stock_text(stock: int) -> str:
    return f"{stock} 件" if stock > 0 else "暂时缺货"


def fallback_reply(message: str) -> str:
    if any(word in message for word in ("你好", "您好", "在吗", "hello", "hi")):
        return "你好，我是电商客服助手。请告诉我商品名称或编号（例如 P1001），我可以查询价格、库存、规格、活动和发货时效。"
    if any(word in message for word in ("订单", "物流", "快递", "退货", "退款", "售后")):
        return "订单、物流和售后查询还在接入中。目前我可以先帮你查询商品信息，请告诉我商品名称或编号。"
    return "请告诉我商品名称或编号（例如 P1001），我帮你查询价格、库存、规格、活动和发货时效。"


def product_reply(message: str, product: dict) -> str:
    sections = []

    if any(word in message for word in ("价格", "多少钱", "几块", "贵", "便宜")):
        sections.append(f"价格：¥{product['price']}")
    if any(word in message for word in ("库存", "有货", "缺货", "现货", "还有吗")):
        sections.append(f"库存：{stock_text(product['stock'])}")
    if any(word in message for word in ("规格", "参数", "配置", "颜色", "尺寸", "功能")):
        sections.append(f"规格：{product['specs']}")
    if any(word in message for word in ("活动", "优惠", "折扣", "满减", "券")):
        sections.append(f"活动：{product['activity']}")
    if any(word in message for word in ("发货", "多久", "几天", "物流", "快递")):
        sections.append(f"发货：{product['shipping']}")

    if not sections:
        sections = [
            f"价格：¥{product['price']}",
            f"库存：{stock_text(product['stock'])}",
            f"规格：{product['specs']}",
            f"活动：{product['activity']}",
            f"发货：{product['shipping']}",
        ]

    lines = [
        f"商品 {product['id']}｜{product['name']}",
        *sections,
        "以上信息来自商品工具 get_product。",
    ]
    return "\n".join(lines)


def run_mock_agent(message: str) -> dict:
    product, args, error = find_product(message)
    tool_calls = []

    if args is not None:
        tool_calls.append({"name": "get_product", "args": args})

    if error:
        return {
            "reply": f"{error}，请确认商品编号后再试。",
            "tool_calls": tool_calls,
        }

    if product is None:
        return {
            "reply": fallback_reply(message),
            "tool_calls": tool_calls,
        }

    return {
        "reply": product_reply(message, product),
        "tool_calls": tool_calls,
    }
