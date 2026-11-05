from __future__ import annotations

import asyncio
import copy
import functools
import hashlib
import json
import logging
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from core.audit import record_tool_audit
from core.cache import get_redis
from core.config import get_settings
from core.logging import log_exception
from core.metrics import METRICS
from core.tool_auth import create_approval_token, create_context_token
from tools.commerce import get_coupons, get_payment_methods
from tools.context import ToolContext
from tools.knowledge import search_knowledge
from tools.mcp_client import MCPToolError, call_mcp
from tools.orders import (
    cancel_order,
    create_aftersale,
    get_aftersale,
    get_logistics,
    get_order,
    intercept_parcel,
    update_address,
)
from tools.products import get_product
from tools.recommend import recommend_products

logger = logging.getLogger("ecommerce_agent.tools")


class ToolErrorCode(str, Enum):
    UNKNOWN_TOOL = "unknown_tool"
    INVALID_ARGUMENTS = "invalid_arguments"
    CONFIRMATION_REQUIRED = "confirmation_required"
    IDEMPOTENCY_KEY_MISSING = "idempotency_key_missing"
    IDEMPOTENCY_IN_PROGRESS = "idempotency_in_progress"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_SATURATED = "tool_saturated"
    TOOL_CIRCUIT_OPEN = "tool_circuit_open"
    TOOL_EXECUTION_FAILED = "tool_execution_failed"
    TOOL_UNAVAILABLE = "tool_unavailable"
    INVALID_RESULT = "invalid_result"


class ToolResult(BaseModel):
    """工具返回的统一信封；result 由各工具自行定义。"""

    model_config = ConfigDict(extra="allow")

    ok: bool
    result: Any = None
    status: str | None = None
    error: str | None = None
    error_code: str | None = None
    retryable: bool = False
    side_effect_committed: bool | None = None
    message: str | None = None
    reason: str | None = None
    summary: str | None = None
    details: Any = None
    truncated: bool = False
    original_chars: int | None = None


def _setting(name: str, default: Any) -> Any:
    return getattr(get_settings(), name, default)


def _error_result(
    code: ToolErrorCode,
    error_text: str,
    *,
    retryable: bool,
    side_effect_committed: bool | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "error": error_text,
        "error_code": code.value,
        "retryable": retryable,
        "side_effect_committed": side_effect_committed,
    }
    payload.update(extra)
    return payload


_CIRCUIT_FAILURE_CODES = {
    ToolErrorCode.TOOL_TIMEOUT.value,
    ToolErrorCode.TOOL_EXECUTION_FAILED.value,
    ToolErrorCode.TOOL_UNAVAILABLE.value,
    ToolErrorCode.INVALID_RESULT.value,
}


class _ToolCircuitBreaker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    def allow(self, name: str) -> tuple[bool, float]:
        now = time.monotonic()
        with self._lock:
            until = self._open_until.get(name, 0.0)
            if until > now:
                return False, until - now
            if until:
                self._open_until.pop(name, None)
                self._failures[name] = 0
            return True, 0.0

    def success(self, name: str) -> None:
        with self._lock:
            self._failures.pop(name, None)
            self._open_until.pop(name, None)

    def failure(self, name: str, threshold: int, cooldown: float) -> bool:
        with self._lock:
            count = self._failures.get(name, 0) + 1
            if count >= threshold:
                self._failures[name] = 0
                self._open_until[name] = time.monotonic() + cooldown
                return True
            self._failures[name] = count
            return False


_breaker = _ToolCircuitBreaker()

_executor_lock = threading.Lock()
_tool_executor: ThreadPoolExecutor | None = None


def _get_tool_executor() -> ThreadPoolExecutor:
    global _tool_executor
    with _executor_lock:
        if _tool_executor is None:
            workers = int(_setting("tool_max_workers", 16))
            _tool_executor = ThreadPoolExecutor(
                max_workers=max(1, workers),
                thread_name_prefix="tool",
            )
        return _tool_executor


_semaphore_lock = threading.Lock()
_tool_semaphores: dict[tuple[str, int], threading.BoundedSemaphore] = {}


def _get_tool_semaphore(name: str, limit: int) -> threading.BoundedSemaphore:
    key = (name, limit)
    with _semaphore_lock:
        semaphore = _tool_semaphores.get(key)
        if semaphore is None:
            semaphore = threading.BoundedSemaphore(limit)
            _tool_semaphores[key] = semaphore
        return semaphore


def _tool_timeout(spec: "ToolSpec") -> float:
    if spec.timeout is not None:
        return float(spec.timeout)
    return float(_setting("tool_timeout", 15.0))


def _tool_attempts(spec: "ToolSpec") -> int:
    if spec.kind != "read":
        return 1
    if spec.max_attempts is not None:
        return max(1, int(spec.max_attempts))
    return max(1, int(_setting("tool_retry_attempts", 2)))


def _retry_backoff() -> float:
    return max(0.0, float(_setting("tool_retry_backoff", 0.2)))


def _circuit_threshold() -> int:
    return max(1, int(_setting("tool_circuit_failures", 5)))


def _circuit_cooldown() -> float:
    return max(1.0, float(_setting("tool_circuit_cooldown", 30.0)))


def _circuit_error(name: str, retry_after: float) -> dict[str, Any]:
    retry_after = max(1, int(round(retry_after)))
    return _error_result(
        ToolErrorCode.TOOL_CIRCUIT_OPEN,
        f"工具 {name} 暂时不可用，请 {retry_after} 秒后重试",
        retryable=True,
        side_effect_committed=False,
        retry_after_seconds=retry_after,
    )


def _should_retry(
    spec: "ToolSpec", result: dict[str, Any], attempt: int, max_attempts: int
) -> bool:
    if spec.kind != "read" or attempt >= max_attempts:
        return False
    if result.get("ok"):
        return False
    code = str(result.get("error_code") or "")
    if code in {
        ToolErrorCode.TOOL_TIMEOUT.value,
        ToolErrorCode.TOOL_CIRCUIT_OPEN.value,
        ToolErrorCode.TOOL_SATURATED.value,
        ToolErrorCode.INVALID_ARGUMENTS.value,
        ToolErrorCode.UNKNOWN_TOOL.value,
        ToolErrorCode.IDEMPOTENCY_IN_PROGRESS.value,
    }:
        return False
    return bool(result.get("retryable"))


def _apply_circuit(spec: "ToolSpec", result: dict[str, Any]) -> None:
    if result.get("ok"):
        _breaker.success(spec.name)
        return
    code = str(result.get("error_code") or "")
    if code not in _CIRCUIT_FAILURE_CODES:
        return
    opened = _breaker.failure(
        spec.name, _circuit_threshold(), _circuit_cooldown()
    )
    if opened:
        METRICS.incr("tool_circuit_open_total")
        logger.warning("工具 %s 连续失败，熔断 %.0fs", spec.name, _circuit_cooldown())


def _validate_tool_result(
    spec: "ToolSpec", result: dict[str, Any]
) -> dict[str, Any]:
    try:
        ToolResult.model_validate(result)
    except ValidationError as exc:
        return _error_result(
            ToolErrorCode.INVALID_RESULT,
            f"工具 {spec.name} 返回结构不符合约定",
            retryable=True,
            side_effect_committed=None if spec.kind == "write" else False,
            details=exc.errors(include_url=False),
        )
    if spec.result_model is not None and result.get("ok"):
        payload = result.get("result")
        if payload is not None:
            try:
                spec.result_model.model_validate(payload)
            except ValidationError as exc:
                return _error_result(
                    ToolErrorCode.INVALID_RESULT,
                    f"工具 {spec.name} 返回数据不符合约定",
                    retryable=True,
                    side_effect_committed=(
                        None if spec.kind == "write" else False
                    ),
                    details=exc.errors(include_url=False),
                )
    return result


def _json_chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def _shrink_string(value: str, limit: int) -> str:
    if limit <= 0 or len(value) <= limit:
        return value
    head = max(1, int(limit * 0.7))
    tail = max(0, limit - head - 24)
    removed = len(value) - head - tail
    marker = f"…[截断 {removed} 字]…"
    return value[:head] + marker + (value[-tail:] if tail else "")


def _shrink_value(
    value: Any, string_limit: int, list_limit: int, depth: int = 0
) -> Any:
    if depth > 12:
        return "…"
    if isinstance(value, str):
        return _shrink_string(value, string_limit)
    if isinstance(value, list):
        items = [
            _shrink_value(item, string_limit, list_limit, depth + 1)
            for item in value[:list_limit]
        ]
        if len(value) > list_limit:
            items.append(f"…[截断 {len(value) - list_limit} 项]…")
        return items
    if isinstance(value, dict):
        return {
            key: _shrink_value(item, string_limit, list_limit, depth + 1)
            for key, item in value.items()
        }
    return value


def _limit_result_size(result: dict[str, Any]) -> dict[str, Any]:
    max_chars = int(_setting("tool_result_max_chars", 24000))
    if max_chars <= 0:
        return result
    try:
        original = _json_chars(result)
    except (TypeError, ValueError):
        return result
    if original <= max_chars:
        return result

    string_limit = int(_setting("tool_result_string_max_chars", 4000))
    list_limit = int(_setting("tool_result_list_max_items", 50))
    limited = dict(result)
    for key in ("result", "details", "message", "error", "reason", "summary"):
        if key in limited:
            limited[key] = _shrink_value(
                limited[key], string_limit, list_limit
            )
    if _json_chars(limited) > max_chars:
        preview = json.dumps(
            limited.get("result"), ensure_ascii=False, default=str
        )
        limited["result"] = preview[:max_chars]
    limited["truncated"] = True
    limited["original_chars"] = original
    return limited


class GetProductArgs(BaseModel):
    product_id: str | None = Field(
        default=None,
        description="商品编号，例如 P2001；已知型号时也可以传 VK75 Pro。已知编号时优先传这个字段。",
    )
    name: str | None = Field(
        default=None,
        description="商品名称、型号或别名，例如 VK75 Pro、烬狐 VK75 Pro 磁轴键盘。不知道编号时传这个字段。",
    )

    @model_validator(mode="after")
    def require_one_lookup_key(self) -> "GetProductArgs":
        if not (self.product_id and self.product_id.strip()) and not (
            self.name and self.name.strip()
        ):
            raise ValueError("product_id 与 name 至少提供一个")
        return self


class SearchKnowledgeArgs(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=1000,
        description="要检索的问题，尽量保留用户原话中的关键信息。",
    )
    product_id: str | None = Field(
        default=None,
        max_length=32,
        description="已知识别到的商品编号，例如 P2001；不确定时不要传。",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=5,
        description="返回的知识片段数量，默认 5。",
    )
    include_deprecated: bool = Field(
        default=False,
        description=(
            "是否包含已废弃的历史政策版本。默认 false；"
            "仅当用户明确询问旧版、历史年份或版本差异时传 true。"
        ),
    )

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query 不能为空")
        return value


class GetOrderArgs(BaseModel):
    order_id: str | None = Field(
        default=None,
        max_length=64,
        description="订单号，例如 ORD-20261018-0001；不知道时留空，返回当前买家最近订单。",
    )

    @field_validator("order_id")
    @classmethod
    def strip_order_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class GetLogisticsArgs(BaseModel):
    order_id: str | None = Field(
        default=None,
        max_length=64,
        description="订单号；不知道时可以传物流单号。",
    )
    tracking_no: str | None = Field(
        default=None,
        max_length=64,
        description="物流单号，例如 SF1234567890123。",
    )

    @field_validator("order_id", "tracking_no")
    @classmethod
    def strip_ids(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class GetAftersaleArgs(BaseModel):
    order_id: str | None = Field(
        default=None,
        max_length=64,
        description="订单号；不知道时留空，返回当前买家最近售后记录。",
    )

    @field_validator("order_id")
    @classmethod
    def strip_order_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class CancelOrderArgs(BaseModel):
    order_id: str = Field(
        min_length=1,
        max_length=64,
        description="要取消的订单号。",
    )

    @field_validator("order_id")
    @classmethod
    def strip_order_id(cls, value: str) -> str:
        return value.strip()


class UpdateAddressArgs(BaseModel):
    order_id: str = Field(
        min_length=1,
        max_length=64,
        description="要修改地址的订单号。",
    )
    address: str = Field(
        min_length=5,
        max_length=300,
        description="完整的新收货地址，包含省市区和详细地址。",
    )

    @field_validator("order_id", "address")
    @classmethod
    def strip_values(cls, value: str) -> str:
        return value.strip()


class InterceptParcelArgs(BaseModel):
    order_id: str = Field(
        min_length=1,
        max_length=64,
        description="要拦截快递的订单号。",
    )
    reason: str = Field(
        default="买家申请拦截",
        max_length=200,
        description="拦截原因，例如不想要了、地址填错。",
    )

    @field_validator("order_id", "reason")
    @classmethod
    def strip_values(cls, value: str) -> str:
        return value.strip()


class CreateAftersaleArgs(BaseModel):
    order_id: str = Field(
        min_length=1,
        max_length=64,
        description="要申请售后的订单号。",
    )
    aftersale_type: Literal["退货退款", "仅退款", "换货", "维修"] = Field(
        description="售后类型。"
    )
    reason: str = Field(
        min_length=1,
        max_length=200,
        description="售后原因，例如商品不合适、质量问题。",
    )
    description: str = Field(
        default="",
        max_length=500,
        description="补充说明，可选。",
    )

    @field_validator("order_id", "reason", "description")
    @classmethod
    def strip_values(cls, value: str) -> str:
        return value.strip()


class GetPaymentMethodsArgs(BaseModel):
    order_id: str | None = Field(
        default=None,
        max_length=64,
        description="订单号，可选；传入时同时返回该订单当前支付方式。",
    )

    @field_validator("order_id")
    @classmethod
    def strip_order_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class GetCouponsArgs(BaseModel):
    active_only: bool = Field(
        default=True,
        description="是否只返回当前可使用的优惠券，默认 true。",
    )


class RecommendProductsArgs(BaseModel):
    budget: int | None = Field(
        default=None,
        ge=0,
        le=100000,
        description="预算上限，单位元。用户说“500 以内”时传 500。",
    )
    category: str | None = Field(
        default=None,
        max_length=20,
        description="品类，例如键盘、鼠标、耳机。",
    )
    use_case: str | None = Field(
        default=None,
        max_length=100,
        description="使用场景，例如游戏、办公、静音、便携。",
    )
    limit: int = Field(
        default=3,
        ge=1,
        le=5,
        description="返回商品数量，默认 3。",
    )


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
    confirm_summary: Callable[[Any], str] | None = None
    uses_context: bool = False
    server: str | None = None
    timeout: float | None = None
    max_attempts: int | None = None
    result_model: type[BaseModel] | None = None


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
        server="catalog",
    ),
    "search_knowledge": ToolSpec(
        name="search_knowledge",
        description=(
            "检索店铺知识库，用于商品卖点、参数、使用方法、保养、FAQ、"
            "店铺与售后政策等描述性知识。价格、库存、活动、发货时效等"
            "实时数据请使用 get_product。"
        ),
        args_model=SearchKnowledgeArgs,
        func=search_knowledge,
        kind="read",
        server="knowledge",
    ),
    "get_order": ToolSpec(
        name="get_order",
        description=(
            "查询当前买家的订单。传订单号查单笔；不传订单号时返回最近订单列表，"
            "用于让用户选择。只能查询当前买家自己的订单。"
        ),
        args_model=GetOrderArgs,
        func=get_order,
        kind="read",
        uses_context=True,
        server="commerce",
    ),
    "get_logistics": ToolSpec(
        name="get_logistics",
        description=(
            "查询当前买家的物流状态。可用订单号或物流单号；都不传时返回最近物流记录。"
        ),
        args_model=GetLogisticsArgs,
        func=get_logistics,
        kind="read",
        uses_context=True,
        server="commerce",
    ),
    "get_aftersale": ToolSpec(
        name="get_aftersale",
        description=(
            "查询当前买家的售后进度。传订单号查该订单；不传时返回最近售后记录。"
        ),
        args_model=GetAftersaleArgs,
        func=get_aftersale,
        kind="read",
        uses_context=True,
        server="commerce",
    ),
    "get_payment_methods": ToolSpec(
        name="get_payment_methods",
        description=(
            "查询店铺支持的支付方式、是否支持花呗分期和货到付款。"
            "可选传入订单号，同时返回该订单当前支付方式。"
        ),
        args_model=GetPaymentMethodsArgs,
        func=get_payment_methods,
        kind="read",
        uses_context=True,
        server="commerce",
    ),
    "get_coupons": ToolSpec(
        name="get_coupons",
        description=(
            "查询当前买家可使用的优惠券，返回券类型、门槛、金额、有效期和使用范围。"
        ),
        args_model=GetCouponsArgs,
        func=get_coupons,
        kind="read",
        uses_context=True,
        server="commerce",
    ),
    "recommend_products": ToolSpec(
        name="recommend_products",
        description=(
            "按预算、品类和使用场景从商品库筛选真实商品，返回型号、价格、库存、活动。"
            "不要自己编造商品或价格。"
        ),
        args_model=RecommendProductsArgs,
        func=recommend_products,
        kind="read",
        server="catalog",
    ),
    "cancel_order": ToolSpec(
        name="cancel_order",
        description=(
            "取消当前买家的订单。仅在待付款或已付款未发货时可用；"
            "执行前必须经过用户确认。"
        ),
        args_model=CancelOrderArgs,
        func=cancel_order,
        kind="write",
        uses_context=True,
        server="commerce",
        confirm_summary=lambda args: (
            f"将取消订单 {args.order_id}，取消后无法恢复。"
        ),
    ),
    "update_address": ToolSpec(
        name="update_address",
        description=(
            "修改当前买家订单的收货地址。仅在发货前可用；执行前必须经过用户确认。"
        ),
        args_model=UpdateAddressArgs,
        func=update_address,
        kind="write",
        uses_context=True,
        server="commerce",
        confirm_summary=lambda args: (
            f"将把订单 {args.order_id} 的收货地址改为：{args.address}"
        ),
    ),
    "intercept_parcel": ToolSpec(
        name="intercept_parcel",
        description=(
            "为当前买家已发货的订单申请拦截快递。拦截结果以快递公司为准；"
            "执行前必须经过用户确认。"
        ),
        args_model=InterceptParcelArgs,
        func=intercept_parcel,
        kind="write",
        uses_context=True,
        server="commerce",
        confirm_summary=lambda args: (
            f"将为订单 {args.order_id} 提交快递拦截申请：{args.reason}"
        ),
    ),
    "create_aftersale": ToolSpec(
        name="create_aftersale",
        description=(
            "为当前买家已签收的订单创建售后工单，支持退货退款、仅退款、换货、维修。"
            "签收后 7 天内可申请；执行前必须经过用户确认。"
        ),
        args_model=CreateAftersaleArgs,
        func=create_aftersale,
        kind="write",
        uses_context=True,
        server="commerce",
        confirm_summary=lambda args: (
            f"将为订单 {args.order_id} 创建{args.aftersale_type}工单，"
            f"原因：{args.reason}"
        ),
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


def openai_tools(allowed: set[str] | None = None) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.args_model.model_json_schema(),
            },
        }
        for name, spec in TOOLS.items()
        if allowed is None or name in allowed
    ]


def _default_confirm_summary(name: str, args: BaseModel) -> str:
    payload = json.dumps(args.model_dump(exclude_none=True), ensure_ascii=False)
    return f"即将执行写操作 {name}，参数：{payload}"


_DEFAULT_IDEMPOTENCY_TTL = 24 * 60 * 60
_DEFAULT_IDEMPOTENCY_UNCERTAIN_TTL = 300
_DEFAULT_IDEMPOTENCY_MAX_ENTRIES = 5000
_DEFAULT_IDEMPOTENCY_LOCK_SECONDS = 60

_idempotency_cache: OrderedDict[
    str, tuple[float, int, dict[str, Any]]
] = OrderedDict()
_idempotency_lock = threading.Lock()
_memory_fallback_warned = False

_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) else return 0 end"
)
_RENEW_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('pexpire', KEYS[1], ARGV[2]) else return 0 end"
)


def _idempotency_ttl() -> int:
    return max(1, int(_setting("tool_idempotency_ttl_seconds", _DEFAULT_IDEMPOTENCY_TTL)))


def _idempotency_uncertain_ttl() -> int:
    return max(
        1,
        int(
            _setting(
                "tool_idempotency_uncertain_ttl_seconds",
                _DEFAULT_IDEMPOTENCY_UNCERTAIN_TTL,
            )
        ),
    )


def _idempotency_max_entries() -> int:
    return max(
        1,
        int(
            _setting(
                "tool_idempotency_max_entries",
                _DEFAULT_IDEMPOTENCY_MAX_ENTRIES,
            )
        ),
    )


def _warn_memory_fallback() -> None:
    global _memory_fallback_warned
    if _memory_fallback_warned:
        return
    _memory_fallback_warned = True
    logger.warning(
        "Redis 不可用，写操作幂等回退到进程内存；多实例下不保证全局去重"
    )


def _get_cached_result(key: str) -> dict[str, Any] | None:
    now = time.monotonic()
    with _idempotency_lock:
        cached = _idempotency_cache.get(key)
        if cached is None:
            return None
        created_at, ttl, result = cached
        if now - created_at > ttl:
            _idempotency_cache.pop(key, None)
            return None
        _idempotency_cache.move_to_end(key)
        return copy.deepcopy(result)


def _cache_result(key: str, result: dict[str, Any], ttl: int) -> None:
    with _idempotency_lock:
        _idempotency_cache[key] = (
            time.monotonic(),
            max(1, ttl),
            copy.deepcopy(result),
        )
        _idempotency_cache.move_to_end(key)
        limit = _idempotency_max_entries()
        while len(_idempotency_cache) > limit:
            _idempotency_cache.popitem(last=False)


def _cache_result_if_absent(
    key: str, result: dict[str, Any], ttl: int
) -> None:
    now = time.monotonic()
    with _idempotency_lock:
        cached = _idempotency_cache.get(key)
        if cached is not None and now - cached[0] <= cached[1]:
            return
        _idempotency_cache[key] = (
            now,
            max(1, ttl),
            copy.deepcopy(result),
        )
        _idempotency_cache.move_to_end(key)
        limit = _idempotency_max_entries()
        while len(_idempotency_cache) > limit:
            _idempotency_cache.popitem(last=False)


def _redis_cached_result(client: Any, key: str) -> dict[str, Any] | None:
    raw = client.get(key)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    result = data.get("result")
    return copy.deepcopy(result) if isinstance(result, dict) else None


def _redis_release(client: Any, key: str, owner: str) -> None:
    if not key or not owner:
        return
    try:
        eval_fn = getattr(client, "eval", None)
        if eval_fn is not None:
            eval_fn(_RELEASE_LUA, 1, key, owner)
            return
        if client.get(key) == owner:
            client.delete(key)
    except Exception as exc:
        logger.warning("释放写操作锁失败：%s", exc)


def _redis_renew(client: Any, key: str, owner: str, ttl: int) -> None:
    if not key or not owner:
        return
    ttl_ms = max(1000, int(ttl * 1000))
    try:
        eval_fn = getattr(client, "eval", None)
        if eval_fn is not None:
            eval_fn(_RENEW_LUA, 1, key, owner, ttl_ms)
            return
        pexpire = getattr(client, "pexpire", None)
        if pexpire is not None and client.get(key) == owner:
            pexpire(key, ttl_ms)
            return
        expire = getattr(client, "expire", None)
        if expire is not None and client.get(key) == owner:
            expire(key, int(ttl))
    except Exception as exc:
        logger.warning("续租写操作锁失败：%s", exc)


class _LockHeartbeat:
    def __init__(self, client: Any, key: str, owner: str, ttl: int) -> None:
        self._client = client
        self._key = key
        self._owner = owner
        self._ttl = max(1, int(ttl))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="tool-idempotency-lock",
        )
        self._thread.start()

    def _run(self) -> None:
        interval = max(0.5, self._ttl / 3.0)
        while not self._stop.wait(interval):
            _redis_renew(self._client, self._key, self._owner, self._ttl)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)


def _write_cache_policy(result: dict[str, Any]) -> tuple[bool, bool]:
    """返回 (是否缓存, 是否不确定结果)。"""
    if result.get("ok"):
        return True, False
    committed = result.get("side_effect_committed")
    if committed is False:
        return False, False
    if committed is None:
        return True, True
    return True, False


def _idempotency_cache_key(
    spec: ToolSpec,
    args: BaseModel,
    idempotency_key: str,
    context: ToolContext | None,
) -> str:
    digest_payload = args.model_dump(exclude_none=True)
    if context is not None and context.buyer_id:
        digest_payload["_buyer_id"] = context.buyer_id
    args_digest = hashlib.sha256(
        json.dumps(
            digest_payload, sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    return f"{spec.name}:{idempotency_key}:{args_digest}"


def _store_uncertain_write_result(
    spec: ToolSpec,
    raw_args: dict[str, Any] | None,
    idempotency_key: str | None,
    context: ToolContext | None,
    result: dict[str, Any],
) -> None:
    if spec.kind != "write" or not idempotency_key:
        return
    try:
        args = spec.args_model.model_validate(raw_args or {})
    except ValidationError:
        return
    key = _idempotency_cache_key(spec, args, idempotency_key, context)
    ttl = _idempotency_uncertain_ttl()
    client = get_redis()
    if client is not None:
        result_key = f"idempotency:result:{key}"
        try:
            if client.get(result_key):
                return
            client.set(
                result_key,
                json.dumps({"result": result}, ensure_ascii=False),
                ex=ttl,
                nx=True,
            )
            return
        except Exception as exc:
            logger.warning("缓存不确定写操作结果失败：%s", exc)
    _cache_result_if_absent(key, result, ttl)


def _prepare_call(
    name: str,
    raw_args: dict[str, Any] | None,
    *,
    confirmed: bool,
) -> tuple[ToolSpec | None, BaseModel | None, dict[str, Any] | None]:
    spec = TOOLS.get(name)
    if spec is None:
        return (
            None,
            None,
            _error_result(
                ToolErrorCode.UNKNOWN_TOOL,
                f"不允许调用未注册的工具：{name}",
                retryable=False,
                side_effect_committed=False,
            ),
        )

    try:
        args = spec.args_model.model_validate(raw_args or {})
    except ValidationError as exc:
        return spec, None, _error_result(
            ToolErrorCode.INVALID_ARGUMENTS,
            "工具参数校验失败，请根据 schema 修正后重试",
            retryable=True,
            side_effect_committed=False,
            details=exc.errors(include_url=False),
        )

    if spec.kind == "write" and not confirmed:
        summary = (
            spec.confirm_summary(args)
            if spec.confirm_summary is not None
            else _default_confirm_summary(name, args)
        )
        return (
            spec,
            args,
            _error_result(
                ToolErrorCode.CONFIRMATION_REQUIRED,
                summary,
                retryable=False,
                side_effect_committed=False,
                status="confirm_required",
                message=summary,
                args=args.model_dump(exclude_none=True),
            ),
        )
    return spec, args, None


def _finalize_result(name: str, result: Any) -> dict[str, Any]:
    if isinstance(result, dict) and result.get("status") == "handoff":
        return {"ok": True, **result}
    if (
        name == "search_knowledge"
        and isinstance(result, dict)
        and result.get("abstained")
    ):
        reason = str(result.get("reason") or "无检索结果")
        return {
            **result,
            "ok": True,
            "status": "handoff",
            "reason": f"知识库无可靠答案：{reason}",
            "summary": f"用户问题：{result.get('query')}；{reason}",
        }
    return {"ok": True, "result": result}


def _store_write_result(
    redis_client: Any,
    result_key: str,
    cache_key: str,
    result: dict[str, Any],
    ttl: int,
) -> None:
    if redis_client is not None and result_key:
        try:
            redis_client.set(
                result_key,
                json.dumps({"result": result}, ensure_ascii=False),
                ex=ttl,
            )
        except Exception as exc:
            logger.warning("写入幂等结果失败：%s", exc)
        return
    _cache_result(cache_key, result, ttl)


def _execute_prepared(
    spec: ToolSpec,
    args: BaseModel,
    *,
    idempotency_key: str | None,
    context: ToolContext | None,
) -> dict[str, Any]:
    cache_key = ""
    redis_client: Any = None
    redis_lock_key = ""
    redis_result_key = ""
    lock_owner = ""
    heartbeat: _LockHeartbeat | None = None
    lock_ttl = max(
        1,
        int(
            _setting(
                "tool_idempotency_lock_ttl_seconds",
                _DEFAULT_IDEMPOTENCY_LOCK_SECONDS,
            )
        ),
    )

    if spec.kind == "write":
        if not idempotency_key:
            return _error_result(
                ToolErrorCode.IDEMPOTENCY_KEY_MISSING,
                "写操作缺少幂等键，已拒绝执行",
                retryable=False,
                side_effect_committed=False,
            )
        cache_key = _idempotency_cache_key(
            spec, args, idempotency_key, context
        )

        redis_client = get_redis()
        if redis_client is not None:
            redis_lock_key = f"idempotency:lock:{cache_key}"
            redis_result_key = f"idempotency:result:{cache_key}"
            try:
                cached = _redis_cached_result(redis_client, redis_result_key)
                if cached is not None:
                    return cached
                fence = 0
                try:
                    fence = int(
                        redis_client.incr(f"idempotency:fence:{cache_key}")
                    )
                except Exception:
                    fence = 0
                lock_owner = f"{fence}:{uuid.uuid4().hex}"
                acquired = redis_client.set(
                    redis_lock_key,
                    lock_owner,
                    nx=True,
                    ex=lock_ttl,
                )
            except Exception as exc:
                logger.warning("Redis 幂等不可用，回退到进程内存：%s", exc)
                redis_client = None
                lock_owner = ""
            else:
                if not acquired:
                    cached = _redis_cached_result(
                        redis_client, redis_result_key
                    )
                    if cached is not None:
                        return cached
                    return _error_result(
                        ToolErrorCode.IDEMPOTENCY_IN_PROGRESS,
                        "该写操作正在处理中，请稍后重试",
                        retryable=True,
                        side_effect_committed=None,
                    )
                heartbeat = _LockHeartbeat(
                    redis_client, redis_lock_key, lock_owner, lock_ttl
                )
                heartbeat.start()
        else:
            _warn_memory_fallback()
        if redis_client is None:
            cached = _get_cached_result(cache_key)
            if cached is not None:
                return cached

    try:
        kwargs = args.model_dump()
        if spec.uses_context:
            kwargs["context"] = context or ToolContext()
        raw_result = spec.func(**kwargs)
    except Exception as exc:
        log_exception("tool.execute", exc)
        final_result = _error_result(
            ToolErrorCode.TOOL_EXECUTION_FAILED,
            "工具执行失败，请稍后重试",
            retryable=True,
            side_effect_committed=None if spec.kind == "write" else False,
        )
    else:
        final_result = _finalize_result(spec.name, raw_result)
        final_result = _validate_tool_result(spec, final_result)
        final_result = _limit_result_size(final_result)

    try:
        if spec.kind == "write":
            should_cache, uncertain = _write_cache_policy(final_result)
            ttl = (
                _idempotency_uncertain_ttl()
                if uncertain
                else _idempotency_ttl()
            )
            if should_cache:
                _store_write_result(
                    redis_client,
                    redis_result_key,
                    cache_key,
                    final_result,
                    ttl,
                )
        return final_result
    finally:
        if heartbeat is not None:
            heartbeat.stop()
        if redis_client is not None and redis_lock_key:
            _redis_release(redis_client, redis_lock_key, lock_owner)


def _execute_tool_impl(
    name: str,
    raw_args: dict[str, Any] | None,
    *,
    confirmed: bool = False,
    idempotency_key: str | None = None,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    spec, args, error = _prepare_call(name, raw_args, confirmed=confirmed)
    if error is not None:
        return error
    assert spec is not None and args is not None

    limit = max(1, int(_setting("tool_max_concurrency_per_tool", 8)))
    semaphore = _get_tool_semaphore(spec.name, limit)
    if not semaphore.acquire(timeout=_tool_timeout(spec)):
        return _error_result(
            ToolErrorCode.TOOL_SATURATED,
            f"工具 {spec.name} 并发已满，请稍后重试",
            retryable=True,
            side_effect_committed=False,
        )
    try:
        return _execute_prepared(
            spec,
            args,
            idempotency_key=idempotency_key,
            context=context,
        )
    finally:
        semaphore.release()


def _record_tool_metrics(
    name: str, started: float, result: dict[str, Any]
) -> None:
    duration_ms = (time.monotonic() - started) * 1000.0
    if not isinstance(result, dict):
        outcome = "error"
    elif result.get("ok"):
        outcome = "ok"
    elif result.get("status") == "confirm_required":
        outcome = "blocked"
    elif result.get("error_code") == ToolErrorCode.TOOL_TIMEOUT.value:
        outcome = "timeout"
    else:
        outcome = "error"
    METRICS.observe_tool(
        name,
        duration_ms,
        outcome,
        error_code=str(result.get("error_code") or ""),
    )


def _run_sync_with_policy(
    spec: ToolSpec,
    raw_args: dict[str, Any] | None,
    *,
    confirmed: bool,
    idempotency_key: str | None,
    context: ToolContext | None,
) -> dict[str, Any]:
    allowed, retry_after = _breaker.allow(spec.name)
    if not allowed:
        return _circuit_error(spec.name, retry_after)

    attempts = _tool_attempts(spec)
    timeout = _tool_timeout(spec)
    result: dict[str, Any] | None = None
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            METRICS.incr("tool_retry_total")
            time.sleep(_retry_backoff() * (2 ** (attempt - 2)))
        try:
            future = _get_tool_executor().submit(
                _execute_tool_impl,
                spec.name,
                raw_args,
                confirmed=confirmed,
                idempotency_key=idempotency_key,
                context=context,
            )
            result = future.result(timeout=timeout)
        except FutureTimeoutError:
            result = _error_result(
                ToolErrorCode.TOOL_TIMEOUT,
                f"工具 {spec.name} 执行超时",
                retryable=True,
                side_effect_committed=None if spec.kind == "write" else False,
            )
            _store_uncertain_write_result(
                spec, raw_args, idempotency_key, context, result
            )
            break
        except Exception as exc:
            log_exception("tool.execute", exc)
            result = _error_result(
                ToolErrorCode.TOOL_EXECUTION_FAILED,
                "工具执行失败，请稍后重试",
                retryable=True,
                side_effect_committed=None if spec.kind == "write" else False,
            )
            _store_uncertain_write_result(
                spec, raw_args, idempotency_key, context, result
            )
        assert result is not None
        if result.get("ok") or not _should_retry(
            spec, result, attempt, attempts
        ):
            break

    if result is None:
        result = _error_result(
            ToolErrorCode.TOOL_EXECUTION_FAILED,
            "工具执行失败，请稍后重试",
            retryable=True,
            side_effect_committed=None if spec.kind == "write" else False,
        )
    _apply_circuit(spec, result)
    return result


def execute_tool(
    name: str,
    raw_args: dict[str, Any] | None,
    *,
    confirmed: bool = False,
    idempotency_key: str | None = None,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    spec = TOOLS.get(name)
    if spec is None:
        result = _prepare_call(name, raw_args, confirmed=confirmed)[2]
        assert result is not None
    else:
        result = _run_sync_with_policy(
            spec,
            raw_args,
            confirmed=confirmed,
            idempotency_key=idempotency_key,
            context=context,
        )
    _record_tool_metrics(name, started, result)
    if spec is not None:
        record_tool_audit(
            tool=name,
            kind=spec.kind,
            args=raw_args or {},
            result=result,
            context=context,
            transport="local",
        )
    return result


async def _execute_remote(
    spec: ToolSpec,
    args: BaseModel,
    *,
    idempotency_key: str | None,
    context: ToolContext | None,
) -> dict[str, Any]:
    settings = get_settings()
    secret = getattr(settings, "tool_secret_value", "")
    if not secret:
        return _error_result(
            ToolErrorCode.TOOL_UNAVAILABLE,
            "MCP 工具签名密钥未配置",
            retryable=False,
            side_effect_committed=False,
        )

    payload = args.model_dump(exclude_none=True)
    buyer_id = context.buyer_id if context is not None else None
    session_id = context.session_id if context is not None else None

    if spec.uses_context:
        payload["context_token"] = create_context_token(
            secret,
            buyer_id=buyer_id,
            session_id=session_id,
            ttl_seconds=settings.tool_context_ttl_seconds,
        )
    if spec.kind == "write":
        if not idempotency_key:
            return _error_result(
                ToolErrorCode.IDEMPOTENCY_KEY_MISSING,
                "写操作缺少幂等键，已拒绝执行",
                retryable=False,
                side_effect_committed=False,
            )
        payload["approval_token"] = create_approval_token(
            secret,
            buyer_id=buyer_id,
            session_id=session_id,
            tool=spec.name,
            arguments=args.model_dump(exclude_none=True),
            idempotency_key=idempotency_key,
            ttl_seconds=settings.tool_approval_ttl_seconds,
        )

    assert spec.server is not None
    try:
        result = await call_mcp(
            spec.server,
            spec.name,
            payload,
            timeout=settings.mcp_timeout,
        )
    except MCPToolError as exc:
        log_exception("tool.mcp", exc)
        return _error_result(
            ToolErrorCode.TOOL_UNAVAILABLE,
            f"工具服务暂时不可用，请稍后重试（{spec.server}）",
            retryable=True,
            side_effect_committed=None if spec.kind == "write" else False,
        )
    final_result = _finalize_result(spec.name, result)
    final_result = _validate_tool_result(spec, final_result)
    return _limit_result_size(final_result)


async def _run_async_with_policy(
    spec: ToolSpec,
    raw_args: dict[str, Any] | None,
    *,
    confirmed: bool,
    idempotency_key: str | None,
    context: ToolContext | None,
    remote: bool,
) -> dict[str, Any]:
    _, args, error = _prepare_call(spec.name, raw_args, confirmed=confirmed)
    if error is not None:
        return error
    assert args is not None

    allowed, retry_after = _breaker.allow(spec.name)
    if not allowed:
        return _circuit_error(spec.name, retry_after)

    attempts = _tool_attempts(spec)
    timeout = _tool_timeout(spec)
    loop = asyncio.get_running_loop()
    result: dict[str, Any] | None = None

    for attempt in range(1, attempts + 1):
        if attempt > 1:
            METRICS.incr("tool_retry_total")
            await asyncio.sleep(_retry_backoff() * (2 ** (attempt - 2)))
        try:
            if remote:
                result = await asyncio.wait_for(
                    _execute_remote(
                        spec,
                        args,
                        idempotency_key=idempotency_key,
                        context=context,
                    ),
                    timeout=timeout,
                )
            else:
                call = functools.partial(
                    _execute_tool_impl,
                    spec.name,
                    raw_args,
                    confirmed=confirmed,
                    idempotency_key=idempotency_key,
                    context=context,
                )
                result = await asyncio.wait_for(
                    loop.run_in_executor(_get_tool_executor(), call),
                    timeout=timeout,
                )
        except asyncio.TimeoutError:
            result = _error_result(
                ToolErrorCode.TOOL_TIMEOUT,
                f"工具 {spec.name} 执行超时",
                retryable=True,
                side_effect_committed=None if spec.kind == "write" else False,
            )
            _store_uncertain_write_result(
                spec, raw_args, idempotency_key, context, result
            )
            break
        except Exception as exc:
            log_exception("tool.execute", exc)
            result = _error_result(
                ToolErrorCode.TOOL_EXECUTION_FAILED,
                "工具执行失败，请稍后重试",
                retryable=True,
                side_effect_committed=None if spec.kind == "write" else False,
            )
            _store_uncertain_write_result(
                spec, raw_args, idempotency_key, context, result
            )
        assert result is not None
        if result.get("ok") or not _should_retry(
            spec, result, attempt, attempts
        ):
            break

    if result is None:
        result = _error_result(
            ToolErrorCode.TOOL_EXECUTION_FAILED,
            "工具执行失败，请稍后重试",
            retryable=True,
            side_effect_committed=None if spec.kind == "write" else False,
        )
    _apply_circuit(spec, result)
    return result


async def execute_tool_async(
    name: str,
    raw_args: dict[str, Any] | None,
    *,
    confirmed: bool = False,
    idempotency_key: str | None = None,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    spec = TOOLS.get(name)
    if spec is None:
        result = _prepare_call(name, raw_args, confirmed=confirmed)[2]
        assert result is not None
        _record_tool_metrics(name, started, result)
        return result

    settings = get_settings()
    remote = bool(
        (getattr(settings, "tool_backend", "") or "").strip().lower() == "mcp"
        and spec.server
    )
    result = await _run_async_with_policy(
        spec,
        raw_args,
        confirmed=confirmed,
        idempotency_key=idempotency_key,
        context=context,
        remote=remote,
    )
    _record_tool_metrics(spec.name, started, result)
    record_tool_audit(
        tool=spec.name,
        kind=spec.kind,
        args=raw_args or {},
        result=result,
        context=context,
        transport="mcp" if remote else "local",
    )
    return result
