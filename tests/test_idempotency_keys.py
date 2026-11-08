from core.idempotency import business_idempotency_key


def test_cancel_order_key_is_stable_and_buyer_scoped():
    first = business_idempotency_key(
        "cancel_order", {"order_id": "A100"}, "buyer-1"
    )
    second = business_idempotency_key(
        "cancel_order", {"order_id": "A100"}, "buyer-1"
    )
    other_buyer = business_idempotency_key(
        "cancel_order", {"order_id": "A100"}, "buyer-2"
    )
    assert first == second
    assert first != other_buyer


def test_update_address_depends_on_address():
    first = business_idempotency_key(
        "update_address",
        {"order_id": "A100", "address": "上海市浦东新区 1 号"},
        "buyer-1",
    )
    second = business_idempotency_key(
        "update_address",
        {"order_id": "A100", "address": "上海市浦东新区 2 号"},
        "buyer-1",
    )
    assert first != second


def test_create_aftersale_key_uses_order_and_type():
    first = business_idempotency_key(
        "create_aftersale",
        {"order_id": "A100", "aftersale_type": "退货退款", "reason": "不合适"},
        "buyer-1",
    )
    second = business_idempotency_key(
        "create_aftersale",
        {"order_id": "A100", "aftersale_type": "退货退款", "reason": "质量"},
        "buyer-1",
    )
    other_type = business_idempotency_key(
        "create_aftersale",
        {"order_id": "A100", "aftersale_type": "换货", "reason": "不合适"},
        "buyer-1",
    )
    assert first == second
    assert first != other_type
