from pydantic import BaseModel, Field

from tools.products import PRODUCTS
from tools.registry import (
    ToolSpec,
    execute_tool,
    openai_tools,
    register_tool,
    unregister_tool,
)


class WriteArgs(BaseModel):
    quantity: int = Field(ge=1)


def test_get_product_tool_validates_and_returns_data():
    result = execute_tool("get_product", {"product_id": "P2001"})
    assert result["ok"] is True
    assert result["result"]["product"]["price"] == PRODUCTS["P2001"]["price"]


def test_get_product_requires_a_lookup_key():
    result = execute_tool("get_product", {})
    assert result["ok"] is False
    assert "参数校验失败" in result["error"]


def test_unknown_tool_is_rejected():
    result = execute_tool("rm_rf", {"path": "/"})
    assert result["ok"] is False


def test_write_tool_requires_confirmation():
    calls = []

    def write(quantity):
        calls.append(quantity)
        return {"done": quantity}

    spec = ToolSpec(
        name="_test_write",
        description="test only",
        args_model=WriteArgs,
        func=write,
        kind="write",
    )
    register_tool(spec)
    try:
        blocked = execute_tool("_test_write", {"quantity": 2})
        assert blocked["ok"] is False
        assert blocked["status"] == "confirm_required"

        missing_key = execute_tool("_test_write", {"quantity": 2}, confirmed=True)
        assert missing_key["ok"] is False
        assert "幂等键" in missing_key["error"]

        executed = execute_tool(
            "_test_write",
            {"quantity": 2},
            confirmed=True,
            idempotency_key="test-key",
        )
        assert executed == {"ok": True, "result": {"done": 2}}

        repeated = execute_tool(
            "_test_write",
            {"quantity": 2},
            confirmed=True,
            idempotency_key="test-key",
        )
        assert repeated == executed
        assert calls == [2]
    finally:
        unregister_tool("_test_write")


def test_openai_tools_only_expose_registered_tools():
    names = {tool["function"]["name"] for tool in openai_tools()}
    assert names == {
        "get_product",
        "search_knowledge",
        "get_order",
        "get_logistics",
        "get_aftersale",
        "cancel_order",
        "update_address",
        "intercept_parcel",
        "create_aftersale",
        "get_payment_methods",
        "get_coupons",
        "recommend_products",
        "transfer_to_human",
    }
