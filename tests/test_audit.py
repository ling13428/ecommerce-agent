from pydantic import BaseModel

from core.audit import reset_audit, set_audit_sink
from tools.context import ToolContext
from tools.registry import ToolSpec, execute_tool, register_tool, unregister_tool


class WriteArgs(BaseModel):
    order_id: str


def _capture():
    rows: list[dict] = []
    set_audit_sink(rows.append)
    return rows


def _context():
    return ToolContext(buyer_id="BUY-0001", session_id="audit-test")


def test_write_attempt_and_execution_are_audited():
    rows = _capture()
    register_tool(
        ToolSpec(
            name="_audit_write",
            description="test",
            args_model=WriteArgs,
            func=lambda order_id: {"cancelled": order_id},
            kind="write",
        )
    )
    try:
        execute_tool(
            "_audit_write",
            {"order_id": "A100"},
            confirmed=False,
            context=_context(),
        )
        execute_tool(
            "_audit_write",
            {"order_id": "A100"},
            confirmed=True,
            idempotency_key="key-1",
            context=_context(),
        )

        assert len(rows) == 2
        assert rows[0]["action"] == "write"
        assert rows[0]["ok"] is False
        assert rows[0]["detail"]
        assert rows[1]["ok"] is True
        assert rows[1]["target"] == "A100"
        assert rows[1]["actor"] == "BUY-0001"
        assert rows[1]["session_id"] == "audit-test"
    finally:
        unregister_tool("_audit_write")
        reset_audit()


def test_sensitive_read_is_audited():
    rows = _capture()
    try:
        execute_tool("get_order", {}, context=_context())
        assert len(rows) == 1
        assert rows[0]["action"] == "read_sensitive"
        assert rows[0]["tool"] == "get_order"
    finally:
        reset_audit()


def test_non_sensitive_read_is_not_audited():
    rows = _capture()
    try:
        execute_tool("get_product", {"product_id": "P2001"})
        assert rows == []
    finally:
        reset_audit()
