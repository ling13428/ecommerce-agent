from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data" / "products" / "catalog.json"
OUTPUT_DIR = ROOT / "data" / "orders"
STORE_DB = OUTPUT_DIR / "orders.db"

TIMEZONE = timezone(timedelta(hours=8))

SURNAMES = list("林陈王李张刘黄赵周吴徐孙马朱胡郭何高罗郑")
GIVEN_NAMES = [
    "嘉宁",
    "子墨",
    "雨桐",
    "思远",
    "晨阳",
    "若初",
    "一凡",
    "可欣",
    "明轩",
    "佳怡",
    "浩然",
    "语嫣",
    "泽宇",
    "梦琪",
    "俊杰",
    "诗涵",
    "天佑",
    "欣怡",
    "博文",
    "安琪",
    "宇航",
    "梓萱",
    "文博",
    "静怡",
]
NICKNAMES = [
    "数码玩家阿凯",
    "林间小鹿",
    "深夜装机",
    "键盘收藏家",
    "阿泽的桌面",
    "小满同学",
    "北岛咖啡",
    "一只柚子",
    "耳机重度用户",
    "周末宅家",
    "橘子汽水",
    "桌面美学研究所",
    "晚风与猫",
    "新手外设党",
    "清风徐来",
    "不加班的一天",
    "电竞小队长",
    "慢热型选手",
    "极简主义者",
    "爱折腾的鱼",
    "云端漫步",
    "摸鱼研究所",
    "半糖主义",
    "冬日暖阳",
]

CITIES = [
    ("浙江省", "杭州市", "西湖区", "文三路"),
    ("浙江省", "宁波市", "鄞州区", "中山东路"),
    ("江苏省", "南京市", "鼓楼区", "中山北路"),
    ("江苏省", "苏州市", "工业园区", "星湖街"),
    ("上海市", "上海市", "浦东新区", "张江路"),
    ("北京市", "北京市", "海淀区", "知春路"),
    ("广东省", "深圳市", "南山区", "科技园"),
    ("广东省", "广州市", "天河区", "体育西路"),
    ("四川省", "成都市", "武侯区", "天府大道"),
    ("湖北省", "武汉市", "洪山区", "光谷大道"),
    ("陕西省", "西安市", "雁塔区", "科技路"),
    ("山东省", "青岛市", "市南区", "香港中路"),
    ("福建省", "厦门市", "思明区", "软件园二期"),
    ("湖南省", "长沙市", "岳麓区", "麓谷大道"),
    ("重庆市", "重庆市", "渝北区", "金开大道"),
    ("天津市", "天津市", "南开区", "鞍山西道"),
]

CARRIERS = [
    ("顺丰速运", "SF"),
    ("京东物流", "JD"),
    ("中通快递", "ZTO"),
    ("圆通速递", "YTO"),
    ("韵达快递", "YD"),
]

STATUS_WEIGHTS = [
    ("pending_payment", 5),
    ("paid", 8),
    ("shipped", 8),
    ("in_transit", 10),
    ("delivered", 13),
    ("completed", 4),
    ("exception", 4),
    ("canceled", 4),
    ("refunding", 4),
]

STATUS_LABELS = {
    "pending_payment": "待付款",
    "paid": "已付款待发货",
    "shipped": "已发货",
    "in_transit": "运输中",
    "delivered": "已签收",
    "completed": "已完成",
    "exception": "物流异常",
    "canceled": "已取消",
    "refunding": "退款中",
}

PAYMENT_METHODS = ["支付宝", "微信支付", "银行卡", "花呗分期"]

COUPON_TEMPLATES = [
    {
        "title": "满 500 减 50",
        "type": "满减",
        "threshold": 500,
        "amount": 50,
    },
    {
        "title": "满 1000 减 120",
        "type": "满减",
        "threshold": 1000,
        "amount": 120,
    },
    {
        "title": "全场 9 折券",
        "type": "折扣",
        "threshold": 0,
        "discount": 0.9,
    },
    {
        "title": "免运费券",
        "type": "免邮",
        "threshold": 0,
    },
    {
        "title": "新人 30 元券",
        "type": "满减",
        "threshold": 200,
        "amount": 30,
    },
]

AFTERSALE_TYPES = [
    ("退货退款", "收到商品后不合适"),
    ("仅退款", "商品与描述不符"),
    ("换货", "颜色或型号需要更换"),
    ("维修", "使用中出现故障"),
]

AFTERSALE_STATUS = {
    "pending": "待商家处理",
    "approved": "商家已同意",
    "rejected": "商家已拒绝",
    "completed": "已完成",
}


def _iso(value: datetime) -> str:
    return value.astimezone(TIMEZONE).isoformat(timespec="seconds")


def _mask_phone(rng: random.Random) -> str:
    prefix = rng.choice(["138", "139", "135", "136", "150", "158", "186", "188"])
    return f"{prefix}****{rng.randint(1000, 9999)}"


def _address(rng: random.Random, city: tuple[str, str, str, str]) -> dict[str, str]:
    province, city_name, district, street = city
    return {
        "province": province,
        "city": city_name,
        "district": district,
        "detail": f"{street}{rng.randint(1, 299)}号{rng.randint(1, 18)}栋***",
    }


def _masked_address(address: dict[str, str]) -> str:
    return (
        f"{address['province']}{address['city']}{address['district']}"
        f"{address['detail']}"
    )


def _tracking_no(rng: random.Random, prefix: str) -> str:
    return f"{prefix}{rng.randint(100000000000, 999999999999)}"


def _load_products() -> list[dict[str, Any]]:
    with CATALOG.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return list(data["products"])


def _build_buyers(now: datetime, rng: random.Random) -> list[dict[str, Any]]:
    used_names: set[str] = set()
    used_codes: set[str] = set()
    buyers: list[dict[str, Any]] = []
    for index, nickname in enumerate(NICKNAMES, 1):
        while True:
            name = f"{rng.choice(SURNAMES)}{rng.choice(GIVEN_NAMES)}"
            if name not in used_names:
                used_names.add(name)
                break
        city = rng.choice(CITIES)
        registered = now - timedelta(days=rng.randint(30, 900))
        while True:
            login_code = f"{rng.randint(100000, 999999)}"
            if login_code not in used_codes:
                used_codes.add(login_code)
                break
        buyers.append(
            {
                "buyer_id": f"BUY-{index:04d}",
                "nickname": nickname,
                "name": name,
                "login_code": login_code,
                "phone": _mask_phone(rng),
                "member_level": rng.choices(
                    ["普通会员", "银牌会员", "金牌会员", "钻石会员"],
                    weights=[45, 30, 18, 7],
                    k=1,
                )[0],
                "city": f"{city[1]}{city[2]}",
                "registered_at": _iso(registered),
                "default_address": _address(rng, city),
                "order_count": 0,
            }
        )
    return buyers


def _weighted_statuses(rng: random.Random, count: int) -> list[str]:
    names = [item[0] for item in STATUS_WEIGHTS]
    weights = [item[1] for item in STATUS_WEIGHTS]
    return rng.choices(names, weights=weights, k=count)


def _build_items(
    rng: random.Random, products: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    chosen = rng.sample(products, rng.randint(1, 3))
    items: list[dict[str, Any]] = []
    for product in chosen:
        quantity = rng.choices([1, 2], weights=[85, 15], k=1)[0]
        price = int(product["price"])
        items.append(
            {
                "product_id": product["id"],
                "model": product["model"],
                "name": product["name"],
                "quantity": quantity,
                "unit_price": price,
                "subtotal": price * quantity,
            }
        )
    return items


def _build_logistics(
    order: dict[str, Any], rng: random.Random, now: datetime
) -> dict[str, Any] | None:
    status = order["status"]
    if status in {"pending_payment", "paid", "canceled"}:
        return None

    shipped_at = datetime.fromisoformat(order["shipped_at"])
    expected = datetime.fromisoformat(order["expected_delivery"])
    city = order["address"]["city"]
    events: list[dict[str, str]] = [
        {
            "time": _iso(shipped_at),
            "status": "已揽收",
            "description": f"{order['carrier']}已揽收，包裹准备发出",
            "location": f"{city}集散中心",
        }
    ]
    events.append(
        {
            "time": _iso(shipped_at + timedelta(hours=rng.randint(4, 8))),
            "status": "运输中",
            "description": "包裹已发出，正在运往目的地",
            "location": f"{city}转运中心",
        }
    )
    events.append(
        {
            "time": _iso(shipped_at + timedelta(hours=rng.randint(16, 28))),
            "status": "到达分拨",
            "description": "包裹已到达目的地分拨中心",
            "location": f"{city}分拨中心",
        }
    )

    if status == "exception":
        events.append(
            {
                "time": _iso(shipped_at + timedelta(hours=rng.randint(30, 40))),
                "status": "物流异常",
                "description": "受天气影响，运输时效可能延迟",
                "location": f"{city}转运中心",
            }
        )
    elif status in {"in_transit", "delivered", "completed", "refunding"}:
        events.append(
            {
                "time": _iso(expected - timedelta(hours=rng.randint(4, 10))),
                "status": "派送中",
                "description": "快递员正在派送，请保持电话畅通",
                "location": f"{city}{order['address']['district']}",
            }
        )
        if status in {"delivered", "completed", "refunding"}:
            events.append(
                {
                    "time": order["delivered_at"],
                    "status": "已签收",
                    "description": "包裹已由本人签收，感谢使用",
                    "location": f"{city}{order['address']['district']}",
                }
            )

    current = events[-1]
    return {
        "tracking_no": order["tracking_no"],
        "order_id": order["order_id"],
        "carrier": order["carrier"],
        "status": status,
        "status_label": STATUS_LABELS[status],
        "current_node": current["description"],
        "expected_delivery": order["expected_delivery"],
        "updated_at": current["time"],
        "events": events,
    }


def _build_aftersale(
    order: dict[str, Any],
    rng: random.Random,
    now: datetime,
    aftersale_type: tuple[str, str],
    status: str,
) -> dict[str, Any]:
    created = now - timedelta(hours=rng.randint(8, 72))
    timeline = [
        {
            "time": _iso(created),
            "status": "已提交",
            "description": "售后申请已提交，等待商家处理",
        }
    ]
    if status in {"approved", "completed"}:
        timeline.append(
            {
                "time": _iso(created + timedelta(hours=rng.randint(2, 12))),
                "status": "商家已同意",
                "description": "商家已同意申请，请按指引寄回商品",
            }
        )
    if status == "completed":
        timeline.append(
            {
                "time": _iso(created + timedelta(hours=rng.randint(20, 60))),
                "status": "已完成",
                "description": "售后处理完成，退款已原路退回",
            }
        )
    if status == "rejected":
        timeline.append(
            {
                "time": _iso(created + timedelta(hours=rng.randint(2, 12))),
                "status": "商家已拒绝",
                "description": "商品已超过售后期限，申请未通过",
            }
        )
    refund_amount = order["payable"] if aftersale_type[0] != "换货" else 0
    return {
        "aftersale_id": f"AS-{order['order_id'][-8:]}",
        "order_id": order["order_id"],
        "buyer_id": order["buyer_id"],
        "type": aftersale_type[0],
        "reason": aftersale_type[1],
        "status": status,
        "status_label": AFTERSALE_STATUS[status],
        "created_at": _iso(created),
        "updated_at": timeline[-1]["time"],
        "refund_amount": refund_amount,
        "timeline": timeline,
    }


def _build_coupons(
    buyers: list[dict[str, Any]], now: datetime, rng: random.Random
) -> list[dict[str, Any]]:
    coupons: list[dict[str, Any]] = []
    scopes = ["全场", "键盘", "鼠标", "耳机"]
    for buyer in buyers:
        templates = rng.sample(COUPON_TEMPLATES, 2)
        for index, template in enumerate(templates, 1):
            status = rng.choices(
                ["active", "used", "expired"], weights=[65, 20, 15], k=1
            )[0]
            if status == "expired":
                valid_from = now - timedelta(days=60)
                valid_to = now - timedelta(days=rng.randint(1, 20))
            elif status == "used":
                valid_from = now - timedelta(days=rng.randint(10, 40))
                valid_to = now + timedelta(days=rng.randint(10, 40))
            else:
                valid_from = now - timedelta(days=rng.randint(0, 10))
                valid_to = now + timedelta(days=rng.randint(10, 45))
            coupons.append(
                {
                    "coupon_id": f"CP-{buyer['buyer_id'][-4:]}-{index}",
                    "buyer_id": buyer["buyer_id"],
                    "title": template["title"],
                    "type": template["type"],
                    "threshold": template.get("threshold", 0),
                    "amount": template.get("amount", 0),
                    "discount": template.get("discount"),
                    "scope": rng.choice(scopes),
                    "status": status,
                    "status_label": {
                        "active": "可使用",
                        "used": "已使用",
                        "expired": "已过期",
                    }[status],
                    "valid_from": _iso(valid_from),
                    "valid_to": _iso(valid_to),
                    "code": f"EMBER{buyer['buyer_id'][-4:]}{index}{rng.randint(100, 999)}",
                }
            )
    return coupons


def build_data(
    *, seed: int = 20261026, buyer_count: int = 24, order_count: int = 60
) -> dict[str, Any]:
    rng = random.Random(seed)
    products = _load_products()
    now = datetime.now(TIMEZONE)
    buyers = _build_buyers(now, rng)[:buyer_count]

    buyer_indices = list(range(len(buyers)))
    while len(buyer_indices) < order_count:
        buyer_indices.append(rng.randrange(len(buyers)))
    rng.shuffle(buyer_indices)

    statuses = _weighted_statuses(rng, order_count)
    orders: list[dict[str, Any]] = []
    shipments: list[dict[str, Any]] = []
    aftersales: list[dict[str, Any]] = []

    for index, (buyer_index, status) in enumerate(
        zip(buyer_indices[:order_count], statuses, strict=True), 1
    ):
        buyer = buyers[buyer_index]
        items = _build_items(rng, products)
        amount = sum(item["subtotal"] for item in items)
        discount = rng.choices([0, 20, 50, 80], weights=[45, 25, 20, 10], k=1)[0]
        shipping_fee = rng.choices([0, 8, 12], weights=[75, 15, 10], k=1)[0]

        if status in {"delivered", "completed", "refunding"}:
            recent_hours = rng.randint(12, 140)
            old_hours = rng.randint(140, 24 * 30)
            delivered = now - timedelta(
                hours=rng.choice([recent_hours, old_hours])
            )
            shipped = delivered - timedelta(
                days=rng.randint(1, 4), hours=rng.randint(0, 20)
            )
            created = shipped - timedelta(hours=rng.randint(6, 36))
            paid = created + timedelta(minutes=rng.randint(3, 40))
            expected = delivered - timedelta(hours=rng.randint(2, 10))
        else:
            if status in {"pending_payment", "paid"}:
                days_ago = rng.randint(0, 3)
            elif status == "canceled":
                days_ago = rng.randint(1, 12)
            else:
                days_ago = rng.randint(5, 30)
            created = now - timedelta(
                days=days_ago,
                hours=rng.randint(0, 20),
                minutes=rng.randint(0, 59),
            )
            paid = created + timedelta(minutes=rng.randint(3, 40))
            shipped = paid + timedelta(hours=rng.randint(6, 36))
            expected = shipped + timedelta(days=rng.randint(2, 5))
            delivered = expected - timedelta(hours=rng.randint(0, 8))
        carrier, prefix = rng.choice(CARRIERS)
        tracking = _tracking_no(rng, prefix) if status not in {
            "pending_payment",
            "paid",
            "canceled",
        } else None

        address = buyer["default_address"]
        order_id = f"ORD-{created.strftime('%Y%m%d')}-{index:04d}"
        order: dict[str, Any] = {
            "order_id": order_id,
            "buyer_id": buyer["buyer_id"],
            "status": status,
            "status_label": STATUS_LABELS[status],
            "items": items,
            "item_count": sum(item["quantity"] for item in items),
            "amount": amount,
            "discount": discount,
            "shipping_fee": shipping_fee,
            "payable": amount - discount + shipping_fee,
            "payment_method": (
                None
                if status == "pending_payment"
                else rng.choice(PAYMENT_METHODS)
            ),
            "created_at": _iso(created),
            "paid_at": (
                None if status == "pending_payment" else _iso(paid)
            ),
            "shipped_at": (
                None
                if status in {"pending_payment", "paid", "canceled"}
                else _iso(shipped)
            ),
            "delivered_at": (
                _iso(delivered)
                if status in {"delivered", "completed", "refunding"}
                else None
            ),
            "canceled_at": (
                _iso(created + timedelta(minutes=rng.randint(5, 90)))
                if status == "canceled"
                else None
            ),
            "tracking_no": tracking,
            "carrier": carrier if tracking else None,
            "expected_delivery": (
                _iso(expected)
                if status in {"shipped", "in_transit", "delivered", "completed", "exception", "refunding"}
                else None
            ),
            "address": address,
            "address_text": _masked_address(address),
            "aftersale_id": None,
            "remark": "",
        }
        orders.append(order)

        shipment = _build_logistics(order, rng, now)
        if shipment:
            shipments.append(shipment)

    buyer_order_count: dict[str, int] = {}
    for order in orders:
        buyer_order_count[order["buyer_id"]] = (
            buyer_order_count.get(order["buyer_id"], 0) + 1
        )

    aftersale_targets = [order for order in orders if order["status"] == "refunding"]
    extras = [
        order
        for order in orders
        if order["status"] in {"delivered", "completed", "exception"}
    ]
    rng.shuffle(extras)
    aftersale_targets.extend(extras[: max(0, 8 - len(aftersale_targets))])

    aftersale_statuses = ["pending", "approved", "completed", "rejected"]
    for index, order in enumerate(aftersale_targets):
        status = (
            "pending"
            if order["status"] == "refunding"
            else aftersale_statuses[index % len(aftersale_statuses)]
        )
        aftersale = _build_aftersale(
            order, rng, now, AFTERSALE_TYPES[index % len(AFTERSALE_TYPES)], status
        )
        aftersales.append(aftersale)
        order["aftersale_id"] = aftersale["aftersale_id"]

    for buyer in buyers:
        buyer["order_count"] = buyer_order_count.get(buyer["buyer_id"], 0)

    coupons = _build_coupons(buyers, now, rng)

    return {
        "generated_at": _iso(now),
        "seed": seed,
        "buyers": buyers,
        "orders": orders,
        "shipments": shipments,
        "aftersales": aftersales,
        "coupons": coupons,
    }


def write_data(data: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    files = {
        "buyers.json": {"generated_at": data["generated_at"], "buyers": data["buyers"]},
        "orders.json": {"generated_at": data["generated_at"], "orders": data["orders"]},
        "logistics.json": {
            "generated_at": data["generated_at"],
            "shipments": data["shipments"],
        },
        "aftersales.json": {
            "generated_at": data["generated_at"],
            "aftersales": data["aftersales"],
        },
        "coupons.json": {
            "generated_at": data["generated_at"],
            "coupons": data["coupons"],
        },
    }
    for name, payload in files.items():
        path = OUTPUT_DIR / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    try:
        from services import orders as order_service

        order_service.reset_store()
    except Exception as exc:
        print(f"警告：重置订单存储失败（{exc}），请手动重置")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="生成 mock 买家、订单、物流和售后数据")
    parser.add_argument("--seed", type=int, default=20261026)
    parser.add_argument("--buyers", type=int, default=24)
    parser.add_argument("--orders", type=int, default=60)
    args = parser.parse_args(argv)

    data = build_data(
        seed=args.seed,
        buyer_count=args.buyers,
        order_count=args.orders,
    )
    write_data(data)

    print(
        f"已生成买家 {len(data['buyers'])} 位、订单 {len(data['orders'])} 笔、"
        f"物流 {len(data['shipments'])} 条、售后 {len(data['aftersales'])} 条、"
        f"优惠券 {len(data['coupons'])} 张"
    )
    print(f"输出目录：{OUTPUT_DIR}")
    for buyer in data["buyers"][:8]:
        print(f"  {buyer['buyer_id']}  {buyer['nickname']}  订单 {buyer['order_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
