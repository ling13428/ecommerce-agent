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


class SaleorError(RuntimeError):
    pass


def gql(url: str, token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    response = httpx.post(
        url,
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    payload = response.json()
    if response.status_code >= 400 or payload.get("errors"):
        messages = [
            str(item.get("message"))
            for item in payload.get("errors") or []
            if isinstance(item, dict)
        ]
        raise SaleorError("\n".join(messages) or response.text[:500])
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


def aftersale_metadata(aftersale: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"key": "aftersale_id", "value": str(aftersale["aftersale_id"])},
        {"key": "aftersale_order_id", "value": str(aftersale["order_id"])},
        {"key": "aftersale_buyer_id", "value": str(aftersale["buyer_id"])},
        {"key": "aftersale_type", "value": str(aftersale["type"])},
        {"key": "aftersale_reason", "value": str(aftersale["reason"])},
        {"key": "aftersale_status", "value": str(aftersale["status"])},
        {
            "key": "aftersale_status_label",
            "value": str(aftersale["status_label"]),
        },
        {"key": "aftersale_created_at", "value": str(aftersale["created_at"])},
        {"key": "aftersale_updated_at", "value": str(aftersale["updated_at"])},
        {
            "key": "aftersale_refund_amount",
            "value": str(aftersale.get("refund_amount") or 0),
        },
        {
            "key": "aftersale_timeline",
            "value": json.dumps(
                aftersale.get("timeline") or [], ensure_ascii=False
            ),
        },
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把售后数据写入 Saleor 订单 metadata")
    parser.add_argument("--url", default="http://127.0.0.1:8001/graphql/")
    parser.add_argument("--email", default="admin@example.com")
    parser.add_argument("--password", default="admin123")
    args = parser.parse_args(argv)

    token = login(args.url, args.email, args.password)
    aftersales = json.loads(
        (ORDER_DIR / "aftersales.json").read_text(encoding="utf-8")
    )["aftersales"]

    updated = 0
    for aftersale in aftersales:
        data = gql(
            args.url,
            token,
            "query($ref:String!){ order(externalReference:$ref){ id } }",
            {"ref": aftersale["order_id"]},
        )
        order = data.get("order")
        if not order:
            print(f"跳过：Saleor 中不存在订单 {aftersale['order_id']}")
            continue
        gql(
            args.url,
            token,
            "mutation($id:ID!,$input:[MetadataInput!]!){"
            " updateMetadata(id:$id,input:$input){ errors{message} } }",
            {"id": order["id"], "input": aftersale_metadata(aftersale)},
        )
        updated += 1
        print(f"已写入 {aftersale['aftersale_id']} → {aftersale['order_id']}")

    print(f"完成：写入 {updated} 条售后")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
