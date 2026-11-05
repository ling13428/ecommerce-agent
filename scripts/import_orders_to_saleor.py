from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ORDER_DIR = ROOT / "data" / "orders"
CHANNEL = "emberfox"
WAREHOUSE_SLUG = "emberfox-warehouse"


class SaleorError(RuntimeError):
    pass


def gql(url: str, token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    response = httpx.post(
        url,
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    payload = response.json()
    if response.status_code >= 400 or payload.get("errors"):
        messages = [
            str(item.get("message"))
            for item in payload.get("errors") or []
            if isinstance(item, dict)
        ]
        raise SaleorError("\n".join(messages) or response.text[:1000])
    return payload["data"]


def login(url: str, email: str, password: str) -> str:
    response = httpx.post(
        url,
        json={
            "query": "mutation($email:String!,$password:String!){"
            " tokenCreate(email:$email,password:$password){ token errors{message} } }",
            "variables": {"email": email, "password": password},
        },
        timeout=30,
    )
    payload = response.json()["data"]["tokenCreate"]
    if not payload.get("token"):
        raise SaleorError(f"登录失败：{payload.get('errors')}")
    return payload["token"]


def load_json(name: str) -> dict[str, Any]:
    return json.loads((ORDER_DIR / name).read_text(encoding="utf-8"))


def saleor_status(order: dict[str, Any]) -> str:
    status = order["status"]
    if status == "canceled":
        return "CANCELED"
    if status == "pending_payment":
        return "UNCONFIRMED"
    if order.get("shipped_at") or order.get("delivered_at"):
        return "FULFILLED"
    return "UNFULFILLED"


def address_input(order: dict[str, Any], buyer: dict[str, Any]) -> dict[str, Any]:
    address = order.get("address") or {}
    detail = address.get("detail") or order.get("address_text") or "测试地址"
    return {
        "firstName": str(buyer.get("nickname") or "买家")[:50],
        "lastName": str(order["buyer_id"]),
        "streetAddress1": str(detail)[:200],
        "city": str(address.get("city") or "深圳")[:100],
        "countryArea": str(address.get("province") or "广东")[:100],
        "postalCode": "518000",
        "country": "CN",
        "skipValidation": True,
    }


def ensure_tax_class(url: str, token: str) -> str:
    data = gql(
        url,
        token,
        "{ taxClasses(first: 10) { edges { node { id name } } } }",
        {},
    )
    for edge in data["taxClasses"]["edges"]:
        if edge["node"]["name"] == "Default":
            return edge["node"]["id"]
    data = gql(
        url,
        token,
        "mutation($input:TaxClassCreateInput!){"
        " taxClassCreate(input:$input){ taxClass{id} errors{field message} } }",
        {"input": {"name": "Default"}},
    )
    result = data["taxClassCreate"]
    if result.get("errors"):
        raise SaleorError(f"创建税类失败：{result['errors']}")
    return result["taxClass"]["id"]


def variant_ids(url: str, token: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    cursor: str | None = None
    while True:
        after = f', after: "{cursor}"' if cursor else ""
        data = gql(
            url,
            token,
            "{ products(first: 100"
            + after
            + ") { pageInfo { hasNextPage endCursor } "
            "edges { node { variants { sku id } } } } }",
            {},
        )
        connection = data["products"]
        for edge in connection["edges"]:
            for variant in edge["node"].get("variants") or []:
                if variant.get("sku"):
                    mapping[variant["sku"]] = variant["id"]
        if not connection["pageInfo"]["hasNextPage"]:
            break
        cursor = connection["pageInfo"]["endCursor"]
    return mapping


def build_order(
    order: dict[str, Any],
    buyer: dict[str, Any],
    warehouse_id: str,
    variants: dict[str, str],
    tax_class_id: str,
) -> dict[str, Any]:
    lines = [
        {
            "variantId": variants[item["product_id"]],
            "productName": item["name"],
            "variantName": item["model"],
            "quantity": int(item["quantity"]),
            "createdAt": order["created_at"],
            "isShippingRequired": True,
            "isGiftCard": False,
            "totalPrice": {
                "gross": float(item["subtotal"]),
                "net": float(item["subtotal"]),
            },
            "undiscountedTotalPrice": {
                "gross": float(item["subtotal"]),
                "net": float(item["subtotal"]),
            },
            "warehouse": warehouse_id,
            "taxClassId": tax_class_id,
        }
        for item in order["items"]
    ]
    metadata = [
        {"key": "buyer_id", "value": str(order["buyer_id"])},
        {"key": "legacy_status", "value": str(order["status"])},
        {"key": "legacy_status_label", "value": str(order["status_label"])},
        {"key": "payment_method", "value": str(order.get("payment_method") or "")},
        {"key": "carrier", "value": str(order.get("carrier") or "")},
        {"key": "tracking_no", "value": str(order.get("tracking_no") or "")},
        {"key": "address_text", "value": str(order.get("address_text") or "")},
        {"key": "shipped_at", "value": str(order.get("shipped_at") or "")},
        {"key": "delivered_at", "value": str(order.get("delivered_at") or "")},
        {"key": "aftersale_id", "value": str(order.get("aftersale_id") or "")},
    ]
    payload: dict[str, Any] = {
        "externalReference": order["order_id"],
        "channel": CHANNEL,
        "createdAt": order["created_at"],
        "status": saleor_status(order),
        "user": {"email": f"{str(order['buyer_id']).lower()}@example.com"},
        "billingAddress": address_input(order, buyer),
        "shippingAddress": address_input(order, buyer),
        "currency": "CNY",
        "languageCode": "EN",
        "metadata": metadata,
        "lines": lines,
        "deliveryMethod": {
            "warehouseId": warehouse_id,
            "warehouseName": "Emberfox Warehouse",
            "shippingPrice": {
                "gross": float(order.get("shipping_fee") or 0),
                "net": float(order.get("shipping_fee") or 0),
            },
        },
    }
    if order.get("tracking_no") and order["status"] not in {"canceled"}:
        payload["fulfillments"] = [
            {
                "trackingCode": order["tracking_no"],
                "lines": [
                    {
                        "variantId": variants[item["product_id"]],
                        "quantity": int(item["quantity"]),
                        "warehouse": warehouse_id,
                        "orderLineIndex": index,
                    }
                    for index, item in enumerate(order["items"])
                ],
            }
        ]
    return payload


def warehouse_id(url: str, token: str) -> str:
    data = gql(
        url,
        token,
        "{ warehouses(first: 100) { edges { node { id slug } } } }",
        {},
    )
    for edge in data["warehouses"]["edges"]:
        if edge["node"]["slug"] == WAREHOUSE_SLUG:
            return edge["node"]["id"]
    raise SaleorError(f"未找到仓库 {WAREHOUSE_SLUG}")


def order_exists(url: str, token: str, reference: str) -> bool:
    data = gql(
        url,
        token,
        "query($ref:String!){ order(externalReference:$ref){ id } }",
        {"ref": reference},
    )
    return bool(data.get("order"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把本地 mock 订单导入 Saleor")
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8001/graphql/",
    )
    parser.add_argument("--email", default="admin@example.com")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)

    token = login(args.url, args.email, args.password)
    wh_id = warehouse_id(args.url, token)
    orders = load_json("orders.json")["orders"]
    buyers = {
        item["buyer_id"]: item
        for item in load_json("buyers.json")["buyers"]
    }
    if args.limit:
        orders = orders[: args.limit]

    variants = variant_ids(args.url, token)
    tax_class = ensure_tax_class(args.url, token)
    missing = {
        item["product_id"]
        for order in orders
        for item in order["items"]
        if item["product_id"] not in variants
    }
    if missing:
        raise SaleorError(f"Saleor 缺少商品变体：{sorted(missing)[:10]}")

    pending = [
        order
        for order in orders
        if not order_exists(args.url, token, order["order_id"])
    ]
    print(f"待导入 {len(pending)} 笔（共 {len(orders)} 笔）")

    created = 0
    mutation = """
    mutation($orders: [OrderBulkCreateInput!]!) {
      orderBulkCreate(
        orders: $orders
        errorPolicy: REJECT_EVERYTHING
        stockUpdatePolicy: SKIP
      ) {
        count
        results {
          order { id externalReference }
          errors { path message code }
        }
        errors { path message code }
      }
    }
    """
    for start in range(0, len(pending), 5):
        batch = [
            build_order(
                order, buyers[order["buyer_id"]], wh_id, variants, tax_class
            )
            for order in pending[start : start + 5]
        ]
        data = gql(args.url, token, mutation, {"orders": batch})
        result = data["orderBulkCreate"]
        errors = result.get("errors") or []
        if errors:
            raise SaleorError(f"导入失败：{errors}")
        for item in result.get("results") or []:
            item_errors = item.get("errors") or []
            if item_errors:
                raise SaleorError(f"订单导入失败：{item_errors}")
            if item.get("order"):
                created += 1
        print(f"已导入 {created}/{len(pending)}")

    print(f"完成：新建 {created}，跳过 {len(orders) - len(pending)}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
