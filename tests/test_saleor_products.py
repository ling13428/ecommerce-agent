import httpx
import respx

from core.config import get_settings
from services.saleor_client import reset_saleor_client
from services.saleor_products import get_saleor_product

URL = "http://saleor.test/graphql/"

LOGIN_OK = {
    "data": {"tokenCreate": {"token": "token-1", "errors": []}}
}

LOOKUP_OK = {
    "data": {
        "productVariant": {
            "sku": "P2001",
            "name": "VK75 Pro",
            "product": {
                "slug": "p2001",
                "name": "烬狐 VK75 Pro 磁轴键盘",
                "category": {"name": "键盘"},
            },
        }
    }
}

PRODUCT_OK = {
    "data": {
        "product": {
            "name": "烬狐 VK75 Pro 磁轴键盘",
            "slug": "p2001",
            "category": {"name": "键盘"},
            "variants": [
                {
                    "sku": "P2001",
                    "name": "VK75 Pro",
                    "quantityAvailable": 0,
                    "stocks": [{"quantity": 56, "warehouse": {"slug": "w"}}],
                    "channelListings": [
                        {"price": {"amount": 969.0, "currency": "CNY"}}
                    ],
                }
            ],
        }
    }
}


def use_saleor(monkeypatch):
    monkeypatch.setenv("PRODUCT_PROVIDER", "saleor")
    monkeypatch.setenv("SALEOR_API_URL", URL)
    monkeypatch.setenv("SALEOR_EMAIL", "admin@example.com")
    monkeypatch.setenv("SALEOR_PASSWORD", "secret")
    monkeypatch.setenv("SALEOR_TOKEN", "")
    get_settings.cache_clear()
    reset_saleor_client()


def cleanup():
    reset_saleor_client()
    get_settings.cache_clear()


@respx.mock
def test_maps_saleor_variant_to_product_schema(monkeypatch):
    use_saleor(monkeypatch)
    try:
        respx.post(URL).mock(
            side_effect=[
                httpx.Response(200, json=LOGIN_OK),
                httpx.Response(200, json=LOOKUP_OK),
                httpx.Response(200, json=PRODUCT_OK),
            ]
        )
        result = get_saleor_product(
            "P2001", {"specs": "磁轴", "activity": "满 800 减 80"}
        )

        assert result["found"] is True
        product = result["product"]
        assert product["id"] == "P2001"
        assert product["model"] == "VK75 Pro"
        assert product["name"] == "烬狐 VK75 Pro 磁轴键盘"
        assert product["price"] == 969
        assert product["stock"] == 56
        assert product["currency"] == "CNY"
        assert product["source"] == "saleor"
        assert product["specs"] == "磁轴"
    finally:
        cleanup()


@respx.mock
def test_timeout_returns_handoff_message(monkeypatch):
    use_saleor(monkeypatch)
    try:
        respx.post(URL).mock(
            side_effect=httpx.ConnectTimeout("connect timeout")
        )
        result = get_saleor_product("P2001")

        assert result["found"] is False
        assert "超时" in result["message"]
    finally:
        cleanup()


@respx.mock
def test_server_error_returns_handoff_message(monkeypatch):
    use_saleor(monkeypatch)
    try:
        respx.post(URL).mock(return_value=httpx.Response(500))
        result = get_saleor_product("P2001")

        assert result["found"] is False
        assert "暂时不可用" in result["message"]
    finally:
        cleanup()


@respx.mock
def test_missing_variant_returns_not_found(monkeypatch):
    use_saleor(monkeypatch)
    try:
        respx.post(URL).mock(
            side_effect=[
                httpx.Response(200, json=LOGIN_OK),
                httpx.Response(200, json={"data": {"productVariant": None}}),
            ]
        )
        result = get_saleor_product("P9999")

        assert result["found"] is False
        assert "未找到" in result["message"]
    finally:
        cleanup()
