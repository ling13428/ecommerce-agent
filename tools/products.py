from __future__ import annotations

PRODUCTS: dict[str, dict] = {
    "P1001": {
        "id": "P1001",
        "name": "无线蓝牙耳机",
        "price": 299,
        "stock": 120,
        "specs": "蓝牙 5.3，主动降噪，续航 30 小时，黑/白两色",
        "activity": "满 199 减 20",
        "shipping": "48 小时内发货",
    },
    "P1002": {
        "id": "P1002",
        "name": "智能手表",
        "price": 599,
        "stock": 0,
        "specs": "1.8 英寸屏，心率/血氧监测，5ATM 防水",
        "activity": "赠表带一条",
        "shipping": "预售，7 天内发货",
    },
    "P1003": {
        "id": "P1003",
        "name": "便携充电宝",
        "price": 129,
        "stock": 350,
        "specs": "10000mAh，22.5W 快充，双口输出",
        "activity": "第二件半价",
        "shipping": "24 小时内发货",
    },
    "P1004": {
        "id": "P1004",
        "name": "机械键盘",
        "price": 399,
        "stock": 45,
        "specs": "87 键，热插拔，三模连接",
        "activity": "满 300 减 30",
        "shipping": "48 小时内发货",
    },
}

ALIASES: dict[str, list[str]] = {
    "P1001": ["蓝牙耳机", "无线耳机", "耳机"],
    "P1002": ["智能手表", "手表"],
    "P1003": ["充电宝", "移动电源"],
    "P1004": ["机械键盘", "键盘"],
}


def _normalize(text: str) -> str:
    return "".join(text.lower().split())


def get_product(product_id: str | None = None, name: str | None = None) -> dict:
    if product_id:
        product = PRODUCTS.get(product_id.upper())
        if product is not None:
            return {"found": True, "product": product}
        return {"found": False, "message": f"未找到商品编号 {product_id}"}

    if not name:
        return {"found": False, "message": "请提供商品编号或商品名称"}

    query = _normalize(name)
    for pid, aliases in ALIASES.items():
        if any(_normalize(alias) in query for alias in aliases):
            return {"found": True, "product": PRODUCTS[pid]}

    return {"found": False, "message": f"未找到与“{name}”匹配的商品"}
