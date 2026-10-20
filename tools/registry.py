from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from core.logging import log_exception
from tools.products import get_product


class GetProductArgs(BaseModel):
    product_id: str | None = Field(
        default=None,
        description="商品编号，例如 P1001。已知编号时优先传这个字段。",
    )
    name: str | None = Field(
        default=None,
        description="商品名称或别名，例如 蓝牙耳机。不知道编号时传这个字段。",
    )

    @model_validator(mode="after")
    def require_one_lookup_key(self) -> "GetProductArgs":
        if not (self.product_id and self.product_id.strip()) and not (
            self.name and self.name.strip()
        ):
            raise ValueError("product_id 与 name 至少提供一个")
        return self


class TransferToHumanArgs(BaseModel):
    reason: str = Field(
        description="转人工原因，例如：用户要求人工、情绪负面、信息不足、敏感操作。",
    )
    summary: str = Field(
        default="",
        description="给人工客服的会话摘要，包含用户诉求和已尝试的处理。",
    )


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    func: Callable[..., Any]
    kind: Literal["read", "write", "handoff"] = "read"
    confirm_summary: Callable[[BaseModel], str] | None = None


def _transfer_to_human(reason: str, summary: str = "") -> dict[str, Any]:
    return {
        "status": "handoff",
        "reason": reason,
        "summary": summary or "用户需要人工协助。",
    }


TOOLS: dict[str, ToolSpec] = {
    "get_product": ToolSpec(
        name="get_product",
        description="按商品编号或名称查询商品的真实价格、库存、规格、活动和发货时效。",
        args_model=GetProductArgs,
        func=get_product,
        kind="read",
    ),
    "transfer_to_human": ToolSpec(
        name="transfer_to_human",
        description="当用户要求人工、情绪负面、信息不足或涉及敏感操作时，转接人工客服。",
        args_model=TransferToHumanArgs,
        func=_transfer_to_human,
        kind="handoff",
    ),
}


def register_tool(spec: ToolSpec, *, override: bool = False) -> None:
    if spec.name in TOOLS and not override:
        raise ValueError(f"工具已存在：{spec.name}")
    TOOLS[spec.name] = spec


def unregister_tool(name: str) -> None:
    TOOLS.pop(name, None)


def openai_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.args_model.model_json_schema(),
            },
        }
        for spec in TOOLS.values()
    ]


def _default_confirm_summary(name: str, args: BaseModel) -> str:
    payload = json.dumps(args.model_dump(exclude_none=True), ensure_ascii=False)
    return f"即将执行写操作 {name}，参数：{payload}"


_IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60
_IDEMPOTENCY_MAX_ENTRIES = 1000
_idempotency_cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
_idempotency_lock = threading.Lock()


def _get_cached_result(key: str) -> dict[str, Any] | None:
    now = time.monotonic()
    with _idempotency_lock:
        cached = _idempotency_cache.get(key)
        if cached is None:
            return None
        created_at, result = cached
        if now - created_at > _IDEMPOTENCY_TTL_SECONDS:
            _idempotency_cache.pop(key, None)
            return None
        _idempotency_cache.move_to_end(key)
        return copy.deepcopy(result)


def _cache_result(key: str, result: dict[str, Any]) -> None:
    with _idempotency_lock:
        _idempotency_cache[key] = (time.monotonic(), copy.deepcopy(result))
        _idempotency_cache.move_to_end(key)
        while len(_idempotency_cache) > _IDEMPOTENCY_MAX_ENTRIES:
            _idempotency_cache.popitem(last=False)


def execute_tool(
    name: str,
    raw_args: dict[str, Any] | None,
    *,
    confirmed: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    spec = TOOLS.get(name)
    if spec is None:
        return {"ok": False, "error": f"不允许调用未注册的工具：{name}"}

    try:
        args = spec.args_model.model_validate(raw_args or {})
    except ValidationError as exc:
        return {
            "ok": False,
            "error": "工具参数校验失败，请根据 schema 修正后重试",
            "details": exc.errors(include_url=False),
        }

    if spec.kind == "write" and not confirmed:
        summary = (
            spec.confirm_summary(args)
            if spec.confirm_summary is not None
            else _default_confirm_summary(name, args)
        )
        return {
            "ok": False,
            "status": "confirm_required",
            "message": summary,
            "args": args.model_dump(exclude_none=True),
        }

    cache_key = ""
    if spec.kind == "write":
        if not idempotency_key:
            return {"ok": False, "error": "写操作缺少幂等键，已拒绝执行"}
        args_digest = hashlib.sha256(
            json.dumps(
                args.model_dump(exclude_none=True), sort_keys=True, ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
        cache_key = f"{name}:{idempotency_key}:{args_digest}"
        cached = _get_cached_result(cache_key)
        if cached is not None:
            return cached

    try:
        result = spec.func(**args.model_dump())
    except Exception as exc:
        log_exception("tool.execute", exc)
        return {"ok": False, "error": "工具执行失败，请稍后重试"}

    if isinstance(result, dict) and result.get("status") == "handoff":
        final_result = {"ok": True, **result}
    else:
        final_result = {"ok": True, "result": result}

    if spec.kind == "write" and final_result.get("ok"):
        _cache_result(cache_key, final_result)
    return final_result
