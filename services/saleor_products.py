from __future__ import annotations

import logging
from typing import Any

import httpx

from core.config import get_settings
from services.saleor_client import SaleorClient, SaleorError, get_saleor_client

logger = logging.getLogger("ecommerce_agent.saleor")

_VARIANT_LOOKUP = """
query($sku: String!) {
  productVariant(sku: $sku) {
    sku
    name
    product { slug name category { name } }
  }
}
"""

_PRODUCT_QUERY = """
query($slug: String!) {
  product(slug: $slug) {
    name
    slug
    category { name }
    variants {
      sku
      name
      quantityAvailable
      stocks { quantity warehouse { slug } }
      channelListings {
        channel { slug }
        price { amount currency }
      }
    }
  }
}
"""


def _get_variant(
    client: SaleorClient, sku: str
) -> dict[str, Any] | None:
    lookup = client.query(_VARIANT_LOOKUP, {"sku": sku})
    variant = lookup.get("productVariant")
    if not variant:
        return None
    product_ref = variant.get("product") or {}
    slug = product_ref.get("slug")
    if not slug:
        return None
    data = client.query(_PRODUCT_QUERY, {"slug": slug})
    product = data.get("product")
    if not product:
        return None
    variants = product.get("variants") or []
    chosen = next(
        (item for item in variants if item.get("sku") == sku),
        variants[0] if variants else None,
    )
    if chosen is None:
        return None
    chosen["product"] = {
        "name": product.get("name"),
        "slug": product.get("slug"),
        "category": product.get("category"),
    }
    return chosen


def _map_variant(
    variant: dict[str, Any],
    local_product: dict[str, Any] | None,
    channel: str,
) -> dict[str, Any]:
    product_node = variant.get("product") or {}
    listings = variant.get("channelListings") or []
    listing = next(
        (
            item
            for item in listings
            if (item.get("channel") or {}).get("slug") == channel
        ),
        listings[0] if listings else None,
    )
    price: float | int | None = None
    currency: str | None = None
    if listing:
        price_info = listing.get("price") or {}
        amount = price_info.get("amount")
        if amount is not None:
            price = int(amount) if float(amount).is_integer() else amount
        currency = price_info.get("currency")

    stock = sum(
        int(item.get("quantity") or 0) for item in (variant.get("stocks") or [])
    )
    if not variant.get("stocks"):
        stock = int(variant.get("quantityAvailable") or 0)

    product: dict[str, Any] = dict(local_product or {})
    product.update(
        {
            "id": variant.get("sku"),
            "model": variant.get("name") or product.get("model"),
            "name": product_node.get("name") or product.get("name"),
            "category": (product_node.get("category") or {}).get("name")
            or product.get("category"),
            "price": price,
            "stock": stock,
            "currency": currency,
            "source": "saleor",
        }
    )
    return product


def get_saleor_product(
    sku: str,
    local_product: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        variant = _get_variant(get_saleor_client(), sku.upper())
    except httpx.TimeoutException:
        logger.warning("Saleor 商品查询超时：%s", sku)
        return {
            "found": False,
            "message": "商品服务响应超时，请稍后重试或转人工。",
        }
    except (httpx.HTTPError, SaleorError) as exc:
        logger.warning("Saleor 商品查询失败：%s", exc)
        return {
            "found": False,
            "message": "商品服务暂时不可用，请稍后重试或转人工。",
        }

    if variant is None:
        return {"found": False, "message": f"未找到商品编号 {sku}"}
    return {
        "found": True,
        "product": _map_variant(
            variant, local_product, get_settings().saleor_channel
        ),
    }
