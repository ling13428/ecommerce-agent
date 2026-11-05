import httpx
import respx

from core.config import get_settings
from services.saleor_client import reset_saleor_client
from services.saleor_orders import (
    get_saleor_aftersale,
    get_saleor_order,
    get_saleor_shipment,
    list_saleor_aftersales,
    list_saleor_orders,
    list_saleor_shipments,
)

URL = "http://saleor.test/graphql/"

LOGIN_OK = {"data": {"tokenCreate": {"token": "token-1", "errors": []}}}

ORDER_OK = {
    "data": {
        "order": {
            "id": "order-id",
            "number": "1001",
            "externalReference": "ORD-20261014-0001",
            "status": "FULFILLED",
            "created": "2026-10-14T03:24:00+08:00",
            "total": {"gross": {"amount": 1448.0, "currency": "CNY"}},
            "user": {"email": "buy-0023@example.com"},
            "metadata": [
                {"key": "buyer_id", "value": "BUY-0023"},
                {"key": "legacy_status", "value": "delivered"},
                {"key": "legacy_status_label", "value": "已签收"},
                {"key": "payment_method", "value": "在线支付"},
                {"key": "carrier", "value": "中通快递"},
                {"key": "tracking_no", "value": "ZTO972869222440"},
                {"key": "shipped_at", "value": "2026-10-14T22:24:00+08:00"},
                {"key": "delivered_at", "value": "2026-10-16T01:24:00+08:00"},
                {"key": "address_text", "value": "广东省深圳市南山区"},
                {"key": "aftersale_id", "value": "AS-014-0001"},
                {"key": "aftersale_order_id", "value": "ORD-20261014-0001"},
                {"key": "aftersale_buyer_id", "value": "BUY-0023"},
                {"key": "aftersale_type", "value": "退货退款"},
                {"key": "aftersale_reason", "value": "收到商品后不喜欢"},
                {"key": "aftersale_status", "value": "pending"},
                {"key": "aftersale_status_label", "value": "待商家处理"},
                {"key": "aftersale_created_at", "value": "2026-10-16T02:24:00+08:00"},
                {"key": "aftersale_updated_at", "value": "2026-10-16T02:24:00+08:00"},
                {"key": "aftersale_refund_amount", "value": "1448"},
                {"key": "aftersale_timeline", "value": "[]"},
            ],
            "lines": [
                {
                    "productName": "烬狐 VM9 电竞游戏鼠标",
                    "quantity": 1,
                    "variant": {"sku": "P2042", "name": "VM9"},
                    "unitPrice": {"gross": {"amount": 549.0}},
                    "totalPrice": {"gross": {"amount": 549.0}},
                },
                {
                    "productName": "烬狐 AH7 头戴式游戏耳机",
                    "quantity": 1,
                    "variant": {"sku": "P2079", "name": "AH7"},
                    "unitPrice": {"gross": {"amount": 899.0}},
                    "totalPrice": {"gross": {"amount": 899.0}},
                },
            ],
            "fulfillments": [
                {"trackingNumber": "ZTO972869222440", "created": "2026-10-14T22:24:00+08:00"}
            ],
        }
    }
}


def use_saleor(monkeypatch):
    monkeypatch.setenv("ORDER_PROVIDER", "saleor")
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
def test_maps_saleor_order(monkeypatch):
    use_saleor(monkeypatch)
    try:
        respx.post(URL).mock(
            side_effect=[
                httpx.Response(200, json=LOGIN_OK),
                httpx.Response(200, json=ORDER_OK),
            ]
        )
        order = get_saleor_order("ORD-20261014-0001", "BUY-0023")

        assert order is not None
        assert order["order_id"] == "ORD-20261014-0001"
        assert order["buyer_id"] == "BUY-0023"
        assert order["status"] == "delivered"
        assert order["status_label"] == "已签收"
        assert order["payable"] == 1448
        assert order["item_count"] == 2
        assert order["tracking_no"] == "ZTO972869222440"
        assert order["items"][0]["product_id"] == "P2042"
        assert order["source"] == "saleor"
    finally:
        cleanup()


@respx.mock
def test_rejects_other_buyer(monkeypatch):
    use_saleor(monkeypatch)
    try:
        respx.post(URL).mock(
            side_effect=[
                httpx.Response(200, json=LOGIN_OK),
                httpx.Response(200, json=ORDER_OK),
            ]
        )
        assert get_saleor_order("ORD-20261014-0001", "BUY-0009") is None
    finally:
        cleanup()


@respx.mock
def test_timeout_returns_none(monkeypatch):
    use_saleor(monkeypatch)
    try:
        respx.post(URL).mock(
            side_effect=httpx.ConnectTimeout("timeout")
        )
        assert get_saleor_order("ORD-20261014-0001", "BUY-0023") is None
    finally:
        cleanup()


@respx.mock
def test_lists_orders_for_buyer(monkeypatch):
    use_saleor(monkeypatch)
    try:
        respx.post(URL).mock(
            side_effect=[
                httpx.Response(200, json=LOGIN_OK),
                httpx.Response(
                    200,
                    json={"data": {"orders": {"edges": [{"node": ORDER_OK["data"]["order"]}]}}},
                ),
            ]
        )
        orders = list_saleor_orders("BUY-0023", limit=5)

        assert len(orders) == 1
        assert orders[0]["order_id"] == "ORD-20261014-0001"
    finally:
        cleanup()


@respx.mock
def test_maps_shipment_from_fulfillment(monkeypatch):
    use_saleor(monkeypatch)
    try:
        respx.post(URL).mock(
            side_effect=[
                httpx.Response(200, json=LOGIN_OK),
                httpx.Response(200, json=ORDER_OK),
            ]
        )
        shipment = get_saleor_shipment(
            "BUY-0023", order_id="ORD-20261014-0001"
        )

        assert shipment is not None
        assert shipment["tracking_no"] == "ZTO972869222440"
        assert shipment["order_id"] == "ORD-20261014-0001"
        assert shipment["carrier"] == "中通快递"
        assert shipment["status"] == "delivered"
        assert shipment["status_label"] == "已签收"
    finally:
        cleanup()


@respx.mock
def test_shipment_rejects_other_buyer(monkeypatch):
    use_saleor(monkeypatch)
    try:
        respx.post(URL).mock(
            side_effect=[
                httpx.Response(200, json=LOGIN_OK),
                httpx.Response(200, json=ORDER_OK),
            ]
        )
        assert (
            get_saleor_shipment("BUY-0009", order_id="ORD-20261014-0001")
            is None
        )
    finally:
        cleanup()


@respx.mock
def test_lists_shipments(monkeypatch):
    use_saleor(monkeypatch)
    try:
        respx.post(URL).mock(
            side_effect=[
                httpx.Response(200, json=LOGIN_OK),
                httpx.Response(
                    200,
                    json={
                        "data": {
                            "orders": {
                                "edges": [{"node": ORDER_OK["data"]["order"]}]
                            }
                        }
                    },
                ),
            ]
        )
        shipments = list_saleor_shipments("BUY-0023", limit=5)

        assert len(shipments) == 1
        assert shipments[0]["tracking_no"] == "ZTO972869222440"
    finally:
        cleanup()


@respx.mock
def test_maps_aftersale_from_metadata(monkeypatch):
    use_saleor(monkeypatch)
    try:
        respx.post(URL).mock(
            side_effect=[
                httpx.Response(200, json=LOGIN_OK),
                httpx.Response(200, json=ORDER_OK),
            ]
        )
        aftersale = get_saleor_aftersale(
            "ORD-20261014-0001", "BUY-0023"
        )

        assert aftersale is not None
        assert aftersale["aftersale_id"] == "AS-014-0001"
        assert aftersale["type"] == "退货退款"
        assert aftersale["status"] == "pending"
        assert aftersale["refund_amount"] == 1448
        assert aftersale["source"] == "saleor"
    finally:
        cleanup()


@respx.mock
def test_aftersale_rejects_other_buyer(monkeypatch):
    use_saleor(monkeypatch)
    try:
        respx.post(URL).mock(
            side_effect=[
                httpx.Response(200, json=LOGIN_OK),
                httpx.Response(200, json=ORDER_OK),
            ]
        )
        assert (
            get_saleor_aftersale("ORD-20261014-0001", "BUY-0009") is None
        )
    finally:
        cleanup()


@respx.mock
def test_lists_aftersales(monkeypatch):
    use_saleor(monkeypatch)
    try:
        respx.post(URL).mock(
            side_effect=[
                httpx.Response(200, json=LOGIN_OK),
                httpx.Response(
                    200,
                    json={
                        "data": {
                            "orders": {
                                "edges": [{"node": ORDER_OK["data"]["order"]}]
                            }
                        }
                    },
                ),
            ]
        )
        aftersales = list_saleor_aftersales("BUY-0023", limit=5)

        assert len(aftersales) == 1
        assert aftersales[0]["aftersale_id"] == "AS-014-0001"
    finally:
        cleanup()
