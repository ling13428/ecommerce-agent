from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any


class AuthError(RuntimeError):
    pass


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def create_claims(claims: dict[str, Any], secret: str) -> str:
    if not secret:
        raise AuthError("签名密钥未配置")
    body = _b64encode(
        json.dumps(claims, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    )
    signature = _b64encode(
        hmac.new(
            secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256
        ).digest()
    )
    return f"{body}.{signature}"


def verify_claims(
    token: str,
    secret: str,
    *,
    required: tuple[str, ...] = ("sub",),
) -> dict[str, Any]:
    if not secret:
        raise AuthError("签名密钥未配置")
    try:
        body, signature = token.split(".", 1)
    except ValueError as exc:
        raise AuthError("Token 格式不合法") from exc

    expected = _b64encode(
        hmac.new(
            secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256
        ).digest()
    )
    if not secrets.compare_digest(signature, expected):
        raise AuthError("Token 签名不合法")

    try:
        payload = json.loads(_b64decode(body))
    except (ValueError, json.JSONDecodeError) as exc:
        raise AuthError("Token 内容不合法") from exc
    if not isinstance(payload, dict):
        raise AuthError("Token 内容不合法")
    if int(payload.get("exp", 0)) < int(time.time()):
        raise AuthError("Token 已过期")
    for claim in required:
        if not str(payload.get(claim) or "").strip():
            raise AuthError(f"Token 缺少 {claim}")
    return payload


def create_token(
    subject: str,
    secret: str,
    *,
    role: str = "buyer",
    ttl_seconds: int = 24 * 60 * 60,
) -> str:
    if not secret:
        raise AuthError("AUTH_SECRET 未配置")
    return create_claims(
        {
            "sub": subject,
            "role": role,
            "exp": int(time.time()) + max(1, ttl_seconds),
        },
        secret,
    )


def verify_token(token: str, secret: str) -> dict[str, Any]:
    return verify_claims(token, secret, required=("sub",))


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError("Authorization 头不合法")
    return token.strip()
