from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Mapping

from core.auth import AuthError, create_claims, verify_claims

CONTEXT_TYPE = "tool_context"
APPROVAL_TYPE = "write_approval"


def canonical_args(args: Mapping[str, Any] | None) -> dict[str, Any]:
    return {key: value for key, value in dict(args or {}).items() if value is not None}


def args_digest(args: Mapping[str, Any] | None) -> str:
    payload = json.dumps(
        canonical_args(args), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_context_token(
    secret: str,
    *,
    buyer_id: str | None,
    session_id: str | None,
    ttl_seconds: int,
) -> str:
    return create_claims(
        {
            "typ": CONTEXT_TYPE,
            "sub": buyer_id or "",
            "sid": session_id or "",
            "scopes": ["read", "write"],
            "exp": int(time.time()) + max(1, ttl_seconds),
        },
        secret,
    )


def verify_context_token(token: str, secret: str) -> dict[str, Any]:
    claims = verify_claims(token, secret, required=())
    if claims.get("typ") != CONTEXT_TYPE:
        raise AuthError("Token 类型不是工具上下文")
    return claims


def create_approval_token(
    secret: str,
    *,
    buyer_id: str | None,
    session_id: str | None,
    tool: str,
    arguments: Mapping[str, Any] | None,
    idempotency_key: str,
    ttl_seconds: int,
) -> str:
    if not idempotency_key:
        raise AuthError("缺少幂等键")
    return create_claims(
        {
            "typ": APPROVAL_TYPE,
            "sub": buyer_id or "",
            "sid": session_id or "",
            "tool": tool,
            "args_digest": args_digest(arguments),
            "jti": idempotency_key,
            "exp": int(time.time()) + max(1, ttl_seconds),
        },
        secret,
    )


def verify_approval_token(
    token: str,
    secret: str,
    *,
    tool: str,
    arguments: Mapping[str, Any] | None,
) -> dict[str, Any]:
    claims = verify_claims(token, secret, required=("jti",))
    if claims.get("typ") != APPROVAL_TYPE:
        raise AuthError("Token 类型不是写操作审批")
    if claims.get("tool") != tool:
        raise AuthError("审批令牌与工具不匹配")
    if claims.get("args_digest") != args_digest(arguments):
        raise AuthError("审批令牌与操作参数不匹配")
    return claims
