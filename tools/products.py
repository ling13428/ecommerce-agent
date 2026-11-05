from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from core.config import get_settings

CATALOG_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "products" / "catalog.json"
)


def _load_products(path: Path = CATALOG_PATH) -> dict[str, dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(
            f"商品目录不存在：{path}，请先运行 scripts/generate_catalog.py"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    products = payload.get("products")
    if not isinstance(products, list) or not products:
        raise ValueError(f"{path} 缺少有效的 products 列表")
    return {str(product["id"]).upper(): product for product in products}


PRODUCTS: dict[str, dict[str, Any]] = _load_products()

PRODUCT_ID_PATTERN = re.compile(r"[Pp](\d{4})")
MODEL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z]{2})(\d{1,3})"
    r"(?:\s*(Pro|Ultra|SE|Plus|Mini|Wireless))?(?![A-Za-z0-9])",
    re.IGNORECASE,
)
SERIES_PATTERN = re.compile(r"^([A-Za-z]{2}\d{1,3})")


def _normalize(text: str) -> str:
    return re.sub(r"[\s\-_]+", "", text).lower()


def _model_index() -> dict[str, str]:
    return {_normalize(product["model"]): pid for pid, product in PRODUCTS.items()}


def _series_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for pid, product in PRODUCTS.items():
        match = SERIES_PATTERN.match(product["model"])
        if match is None:
            continue
        key = _normalize(match.group(1))
        current = index.get(key)
        if current is None:
            index[key] = pid
            continue
        current_model = _normalize(PRODUCTS[current]["model"])
        if current_model != key and _normalize(product["model"]) == key:
            index[key] = pid
    return index


MODEL_INDEX = _model_index()
SERIES_INDEX = _series_index()


def detect_product_id(text: str) -> str | None:
    if not text:
        return None

    match = PRODUCT_ID_PATTERN.search(text)
    if match:
        candidate = f"P{match.group(1)}"
        return candidate if candidate in PRODUCTS else None

    for match in MODEL_PATTERN.finditer(text):
        prefix, number, suffix = match.group(1), match.group(2), match.group(3)
        model_key = _normalize(f"{prefix}{number}{suffix or ''}")
        product_id = MODEL_INDEX.get(model_key)
        if product_id is not None:
            return product_id
        series_key = _normalize(f"{prefix}{number}")
        product_id = SERIES_INDEX.get(series_key)
        if product_id is not None:
            return product_id

    query = _normalize(text)
    best: tuple[int, str] | None = None
    for product_id, product in PRODUCTS.items():
        for candidate in (product["name"], product["model"]):
            key = _normalize(candidate)
            if key and key in query:
                if best is None or len(key) > best[0]:
                    best = (len(key), product_id)
    return best[1] if best is not None else None


def get_product(product_id: str | None = None, name: str | None = None) -> dict:
    provider = (get_settings().product_provider or "mock").strip().lower()
    if provider == "saleor":
        if product_id:
            sku: str | None = product_id.strip().upper()
        elif name:
            sku = detect_product_id(name)
        else:
            sku = None
        if not sku:
            return {
                "found": False,
                "message": f"未找到与“{name or product_id}”匹配的商品",
            }
        from services.saleor_products import get_saleor_product

        return get_saleor_product(sku, PRODUCTS.get(sku))

    if product_id:
        product = PRODUCTS.get(product_id.upper())
        if product is not None:
            return {"found": True, "product": product}
        return {"found": False, "message": f"未找到商品编号 {product_id}"}

    if not name:
        return {"found": False, "message": "请提供商品编号或商品名称"}

    detected = detect_product_id(name)
    if detected is not None:
        return {"found": True, "product": PRODUCTS[detected]}

    return {"found": False, "message": f"未找到与“{name}”匹配的商品"}
