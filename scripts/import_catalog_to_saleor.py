from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CATALOG = ROOT / "data" / "products" / "catalog.json"
CATEGORY_SLUGS = {"键盘": "keyboard", "鼠标": "mouse", "耳机": "headset"}
CHANNEL_SLUG = os.environ.get("SALEOR_CHANNEL_SLUG", "emberfox")
WAREHOUSE_SLUG = "emberfox-warehouse"
PRODUCT_TYPE_SLUG = "emberfox"


class SaleorError(RuntimeError):
    pass


class SaleorClient:
    def __init__(self, url: str, token: str):
        self.url = url
        self.client = httpx.Client(
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )

    def gql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.client.post(
            self.url, json={"query": query, "variables": variables or {}}
        )
        if response.status_code >= 400:
            raise SaleorError(
                f"HTTP {response.status_code}: {response.text[:800]}"
            )
        payload = response.json()
        if payload.get("errors"):
            raise SaleorError(str(payload["errors"]))
        return payload["data"]

    def mutation(self, name: str, field: str, query: str, variables: dict[str, Any]):
        data = self.gql(query, variables)
        result = data.get(name) or {}
        errors = result.get("errors") or []
        if errors:
            raise SaleorError(f"{name}: {errors}")
        return result.get(field)

    def close(self) -> None:
        self.client.close()


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
    response.raise_for_status()
    payload = response.json()["data"]["tokenCreate"]
    if not payload.get("token"):
        raise SaleorError(f"登录失败：{payload.get('errors')}")
    return payload["token"]


def ensure_warehouse(client: SaleorClient) -> str:
    data = client.gql("{ warehouses(first: 100) { edges { node { id slug } } } }")
    for edge in data["warehouses"]["edges"]:
        if edge["node"]["slug"] == WAREHOUSE_SLUG:
            return edge["node"]["id"]
    result = client.mutation(
        "createWarehouse",
        "warehouse",
        "mutation($input:WarehouseCreateInput!){"
        " createWarehouse(input:$input){ warehouse{id} errors{field message} } }",
        {
            "input": {
                "name": "Emberfox Warehouse",
                "slug": WAREHOUSE_SLUG,
                "email": "ops@example.com",
                "address": {
                    "firstName": "Emberfox",
                    "lastName": "Ops",
                    "streetAddress1": "1 Test Road",
                    "city": "Shenzhen",
                    "countryArea": "Guangdong",
                    "postalCode": "518000",
                    "country": "CN",
                    "skipValidation": True,
                },
            }
        },
    )
    return result["id"]


def ensure_channel(client: SaleorClient, warehouse_id: str) -> str:
    data = client.gql("{ channels { id slug currencyCode } }")
    for channel in data["channels"]:
        if channel["slug"] == CHANNEL_SLUG:
            return channel["id"]
    result = client.mutation(
        "channelCreate",
        "channel",
        "mutation($input:ChannelCreateInput!){"
        " channelCreate(input:$input){ channel{id} errors{field message code} } }",
        {
            "input": {
                "name": "Emberfox",
                "slug": CHANNEL_SLUG,
                "currencyCode": "CNY",
                "defaultCountry": "CN",
                "addWarehouses": [warehouse_id],
            }
        },
    )
    return result["id"]


def ensure_product_type(client: SaleorClient) -> str:
    data = client.gql("{ productTypes(first: 100) { edges { node { id slug } } } }")
    for edge in data["productTypes"]["edges"]:
        if edge["node"]["slug"] == PRODUCT_TYPE_SLUG:
            return edge["node"]["id"]
    result = client.mutation(
        "productTypeCreate",
        "productType",
        "mutation($input:ProductTypeInput!){"
        " productTypeCreate(input:$input){ productType{id} errors{field message} } }",
        {
            "input": {
                "name": "Emberfox",
                "slug": PRODUCT_TYPE_SLUG,
                "kind": "NORMAL",
                "hasVariants": True,
                "isShippingRequired": True,
            }
        },
    )
    return result["id"]


def ensure_category(client: SaleorClient, name: str) -> str:
    slug = CATEGORY_SLUGS.get(name, "misc")
    data = client.gql(
        "query($slug:String!){ category(slug:$slug){ id } }", {"slug": slug}
    )
    if data.get("category"):
        return data["category"]["id"]
    result = client.mutation(
        "categoryCreate",
        "category",
        "mutation($input:CategoryInput!){"
        " categoryCreate(input:$input){ category{id} errors{field message} } }",
        {"input": {"name": name, "slug": slug}},
    )
    return result["id"]


def find_product(
    client: SaleorClient, slug: str
) -> tuple[str, str | None] | None:
    data = client.gql(
        "query($slug:String!){ products(first:1, filter:{slugs:[$slug]})"
        " { edges { node { id variants { id } } } } }",
        {"slug": slug},
    )
    edges = data["products"]["edges"]
    if not edges:
        return None
    node = edges[0]["node"]
    variants = node.get("variants") or []
    return node["id"], (variants[0]["id"] if variants else None)


def import_product(
    client: SaleorClient,
    product: dict[str, Any],
    channel_id: str,
    warehouse_id: str,
    product_type_id: str,
    category_id: str,
) -> str:
    slug = product["id"].lower()
    existing = find_product(client, slug)
    is_new = existing is None
    variant_created = False
    if existing is not None:
        product_id, variant_id = existing
    else:
        variant_id = None
        created = client.mutation(
            "productCreate",
            "product",
            "mutation($input:ProductCreateInput!){"
            " productCreate(input:$input){ product{id} errors{field message} } }",
            {
                "input": {
                    "name": product["name"],
                    "slug": slug,
                    "productType": product_type_id,
                    "category": category_id,
                    "chargeTaxes": True,
                }
            },
        )
        product_id = created["id"]

    if variant_id is None:
        variant = client.mutation(
            "productVariantCreate",
            "productVariant",
            "mutation($input:ProductVariantCreateInput!){"
            " productVariantCreate(input:$input){ productVariant{id} errors{field message} } }",
            {
                "input": {
                    "product": product_id,
                    "sku": product["id"],
                    "name": product["model"],
                    "trackInventory": True,
                    "attributes": [],
                }
            },
        )
        variant_id = variant["id"]
        variant_created = True

    channel_listing = {
        "channelId": channel_id,
        "isPublished": True,
        "visibleInListings": True,
        "isAvailableForPurchase": True,
    }
    if variant_created:
        channel_listing["addVariants"] = [variant_id]
    client.mutation(
        "productChannelListingUpdate",
        "errors",
        "mutation($id:ID!,$input:ProductChannelListingUpdateInput!){"
        " productChannelListingUpdate(id:$id,input:$input){"
        " errors{field message} } }",
        {
            "id": product_id,
            "input": {"updateChannels": [channel_listing]},
        },
    )

    client.mutation(
        "productVariantChannelListingUpdate",
        "errors",
        "mutation($id:ID!,$input:[ProductVariantChannelListingAddInput!]!){"
        " productVariantChannelListingUpdate(id:$id,input:$input){"
        " errors{field message} } }",
        {
            "id": variant_id,
            "input": [
                {
                    "channelId": channel_id,
                    "price": product["price"],
                    "isAvailableForPurchase": True,
                }
            ],
        },
    )

    if variant_created:
        stock_query = (
            "mutation($variantId:ID!,$stocks:[StockInput!]!){"
            " productVariantStocksCreate(variantId:$variantId, stocks:$stocks){"
            " errors{field message} } }"
        )
        stock_name = "productVariantStocksCreate"
    else:
        stock_query = (
            "mutation($variantId:ID!,$stocks:[StockInput!]!){"
            " productVariantStocksUpdate(variantId:$variantId, stocks:$stocks){"
            " errors{field message} } }"
        )
        stock_name = "productVariantStocksUpdate"
    client.mutation(
        stock_name,
        "errors",
        stock_query,
        {
            "variantId": variant_id,
            "stocks": [{"warehouse": warehouse_id, "quantity": product["stock"]}],
        },
    )
    return "created" if (is_new or variant_created) else "updated"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把本地商品目录导入 Saleor")
    parser.add_argument(
        "--url",
        default=os.environ.get("SALEOR_API_URL", "http://127.0.0.1:8001/graphql/"),
    )
    parser.add_argument(
        "--email", default=os.environ.get("SALEOR_EMAIL", "admin@example.com")
    )
    parser.add_argument(
        "--password", default=os.environ.get("SALEOR_PASSWORD", "admin123")
    )
    parser.add_argument("--limit", type=int, default=0, help="0 表示全部导入")
    args = parser.parse_args(argv)

    token = login(args.url, args.email, args.password)
    client = SaleorClient(args.url, token)
    try:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))["products"]
        if args.limit:
            catalog = catalog[: args.limit]

        warehouse_id = ensure_warehouse(client)
        channel_id = ensure_channel(client, warehouse_id)
        product_type_id = ensure_product_type(client)
        categories = {
            name: ensure_category(client, name)
            for name in {item["category"] for item in catalog}
        }

        created = skipped = 0
        started = time.perf_counter()
        for index, product in enumerate(catalog, start=1):
            result = import_product(
                client,
                product,
                channel_id,
                warehouse_id,
                product_type_id,
                categories[product["category"]],
            )
            if result == "created":
                created += 1
            else:
                skipped += 1
            if index % 10 == 0:
                print(f"进度 {index}/{len(catalog)}")

        elapsed = time.perf_counter() - started
        print(
            f"完成：新建 {created}，跳过 {skipped}，"
            f"耗时 {elapsed:.1f}s，渠道 {CHANNEL_SLUG}"
        )
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
