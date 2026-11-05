import time

import pytest

from core.auth import AuthError, create_claims
from core.tool_auth import (
    args_digest,
    create_approval_token,
    create_context_token,
    verify_approval_token,
    verify_context_token,
)

SECRET = "unit-test-secret"


def test_context_token_roundtrip():
    token = create_context_token(
        SECRET, buyer_id="BUY-0001", session_id="s-1", ttl_seconds=60
    )

    claims = verify_context_token(token, SECRET)

    assert claims["sub"] == "BUY-0001"
    assert claims["sid"] == "s-1"
    assert claims["typ"] == "tool_context"


def test_context_token_allows_empty_buyer():
    token = create_context_token(
        SECRET, buyer_id=None, session_id="s-1", ttl_seconds=60
    )

    assert verify_context_token(token, SECRET)["sub"] == ""


def test_context_token_rejects_tamper_and_expiry():
    token = create_context_token(
        SECRET, buyer_id="BUY-0001", session_id="s-1", ttl_seconds=60
    )
    body, signature = token.split(".", 1)

    with pytest.raises(AuthError):
        verify_context_token(f"{body}x.{signature}", SECRET)

    expired = create_claims(
        {
            "typ": "tool_context",
            "sub": "BUY-0001",
            "sid": "s-1",
            "exp": int(time.time()) - 1,
        },
        SECRET,
    )
    with pytest.raises(AuthError):
        verify_context_token(expired, SECRET)


def test_approval_token_is_bound_to_tool_and_args():
    token = create_approval_token(
        SECRET,
        buyer_id="BUY-0001",
        session_id="s-1",
        tool="cancel_order",
        arguments={"order_id": "ORD-1"},
        idempotency_key="jti-1",
        ttl_seconds=60,
    )

    claims = verify_approval_token(
        token, SECRET, tool="cancel_order", arguments={"order_id": "ORD-1"}
    )
    assert claims["jti"] == "jti-1"

    with pytest.raises(AuthError):
        verify_approval_token(
            token, SECRET, tool="update_address", arguments={"order_id": "ORD-1"}
        )
    with pytest.raises(AuthError):
        verify_approval_token(
            token, SECRET, tool="cancel_order", arguments={"order_id": "ORD-2"}
        )


def test_args_digest_ignores_none_and_order():
    assert args_digest({"a": 1, "b": None}) == args_digest({"a": 1})
    assert args_digest({"a": 1, "b": 2}) == args_digest({"b": 2, "a": 1})


def test_requires_secret():
    with pytest.raises(AuthError):
        create_context_token("", buyer_id="BUY-0001", session_id="s-1", ttl_seconds=60)
    with pytest.raises(AuthError):
        create_approval_token(
            "",
            buyer_id="BUY-0001",
            session_id="s-1",
            tool="cancel_order",
            arguments={},
            idempotency_key="jti-1",
            ttl_seconds=60,
        )
