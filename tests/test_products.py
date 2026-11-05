from tools.products import PRODUCTS, detect_product_id, get_product


def test_detect_by_product_id_pattern():
    assert detect_product_id("P2001 续航多久") == "P2001"
    assert detect_product_id("帮我查 p2041 的价格") == "P2041"


def test_detect_by_model():
    assert detect_product_id("VK75 Pro 的触发键程") == "P2001"
    assert detect_product_id("vk75 pro 怎么连接") == "P2001"
    assert detect_product_id("VM9 Pro 多重") == "P2041"
    assert detect_product_id("AH9 Wireless 延迟") == "P2078"


def test_detect_series_falls_back_to_base_model():
    assert detect_product_id("VK75 续航多久") == "P2002"
    assert detect_product_id("VM9 适合什么握姿") == "P2042"


def test_detect_returns_none_for_generic_or_unknown():
    assert detect_product_id("耳机续航多久") is None
    assert detect_product_id("退货政策是什么") is None
    assert detect_product_id("P9999 价格") is None
    assert detect_product_id("") is None


def test_get_product_by_id_model_and_name():
    assert get_product(product_id="P2001")["product"]["price"] == (
        PRODUCTS["P2001"]["price"]
    )
    assert get_product(name="VK75 Pro")["product"]["id"] == "P2001"
    assert get_product(name="烬狐 VK75 Pro 磁轴键盘")["product"]["id"] == "P2001"
    assert get_product(product_id="P9999")["found"] is False
