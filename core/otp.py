from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import threading
import time

from core.cache import get_redis
from core.config import get_settings

logger = logging.getLogger("ecommerce_agent.otp")

_lock = threading.Lock()
_memory: dict[str, dict[str, float | str]] = {}


class OtpError(RuntimeError):
    pass


class OtpCooldown(OtpError):
    pass


def mask_phone(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) < 7:
        return "***"
    return f"{digits[:3]}****{digits[-4:]}"


def _hash(phone: str, code: str) -> str:
    return hmac.new(
        b"ecommerce-agent-otp",
        f"{phone}:{code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _key(phone: str) -> str:
    return f"otp:{phone}"


def _cooldown_key(phone: str) -> str:
    return f"otp:cooldown:{phone}"


def _store(phone: str, payload: str, ttl: int) -> None:
    client = get_redis()
    if client is not None:
        client.set(_key(phone), payload, ex=ttl + 60)
        return
    with _lock:
        _memory[phone] = {"payload": payload, "sent_at": time.time()}


def _load(phone: str) -> str | None:
    client = get_redis()
    if client is not None:
        return client.get(_key(phone))
    with _lock:
        entry = _memory.get(phone)
        return str(entry["payload"]) if entry else None


def _delete(phone: str) -> None:
    client = get_redis()
    if client is not None:
        client.delete(_key(phone))
        return
    with _lock:
        _memory.pop(phone, None)


def _take_cooldown(phone: str) -> bool:
    settings = get_settings()
    client = get_redis()
    if client is not None:
        return bool(
            client.set(
                _cooldown_key(phone),
                "1",
                nx=True,
                ex=settings.otp_send_cooldown,
            )
        )
    with _lock:
        entry = _memory.get(phone)
        now = time.time()
        if entry and now - float(entry.get("sent_at") or 0) < (
            settings.otp_send_cooldown
        ):
            return False
        return True


def issue_code(phone: str) -> tuple[str, int]:
    settings = get_settings()
    if not _take_cooldown(phone):
        raise OtpCooldown("验证码发送过于频繁，请稍后再试")

    code = f"{secrets.randbelow(1_000_000):06d}"
    payload = json.dumps(
        {
            "hash": _hash(phone, code),
            "expires": time.time() + settings.otp_ttl_seconds,
            "attempts": 0,
        }
    )
    _store(phone, payload, settings.otp_ttl_seconds)
    return code, settings.otp_ttl_seconds


def verify_code(phone: str, code: str) -> bool:
    settings = get_settings()
    raw = _load(phone)
    if not raw:
        return False
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        _delete(phone)
        return False

    if (
        time.time() > float(data.get("expires") or 0)
        or int(data.get("attempts") or 0) >= settings.otp_max_attempts
    ):
        _delete(phone)
        return False

    if hmac.compare_digest(str(data.get("hash")), _hash(phone, code)):
        _delete(phone)
        return True

    data["attempts"] = int(data.get("attempts") or 0) + 1
    remaining = max(
        1, int(float(data.get("expires") or 0) - time.time())
    )
    _store(phone, json.dumps(data), remaining)
    return False


def reset_otp_store() -> None:
    with _lock:
        _memory.clear()
    client = get_redis()
    if client is not None:
        try:
            keys = client.keys("otp:*")
            if keys:
                client.delete(*keys)
        except Exception as exc:
            logger.warning("清空 OTP 缓存失败：%s", exc)
