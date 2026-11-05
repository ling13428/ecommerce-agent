from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from core.audit import record_tool_audit
from core.cache import get_redis
from core.config import get_settings
from core.logging import log_exception
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


_IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60
_IDEMPOTENCY_LOCK_SECONDS = 60
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


def _redis_release(client: Any, key: str) -> None:
    try:
        client.delete(key)
    except Exception as exc:
        logger.warning("释放写操作锁失败：%s", exc)


def _prepare_call(
    name: str,
    raw_args: dict[str, Any] | None,
    *,
    confirmed: bool,
) -> tuple[ToolSpec | None, BaseModel | None, dict[str, Any] | None]:
    spec = TOOLS.get(name)
    if spec is None:
        return None, None, {"ok": False, "error": f"不允许调用未注册的工具：{name}"}

    try:
        args = spec.args_model.model_validate(raw_args or {})
    except ValidationError as exc:
        return spec, None, {
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
        return spec, args, {
            "ok": False,
            "status": "confirm_required",
            "message": summary,
            "args": args.model_dump(exclude_none=True),
        }
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

    cache_key = ""
    redis_client: Any = None
    redis_lock_key = ""
    redis_result_key = ""
    if spec.kind == "write":
        if not idempotency_key:
            return {"ok": False, "error": "写操作缺少幂等键，已拒绝执行"}
        digest_payload = args.model_dump(exclude_none=True)
        if context is not None and context.buyer_id:
            digest_payload["_buyer_id"] = context.buyer_id
        args_digest = hashlib.sha256(
            json.dumps(
                digest_payload, sort_keys=True, ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
        cache_key = f"{name}:{idempotency_key}:{args_digest}"

        redis_client = get_redis()
        if redis_client is not None:
            redis_lock_key = f"idempotency:lock:{cache_key}"
            redis_result_key = f"idempotency:result:{cache_key}"
            try:
                cached = _redis_cached_result(redis_client, redis_result_key)
                if cached is not None:
                    return cached
                acquired = redis_client.set(
                    redis_lock_key,
                    "1",
                    nx=True,
                    ex=_IDEMPOTENCY_LOCK_SECONDS,
                )
            except Exception as exc:
                logger.warning("Redis 幂等不可用，回退到进程内存：%s", exc)
                redis_client = None
            else:
                if not acquired:
                    cached = _redis_cached_result(
                        redis_client, redis_result_key
                    )
                    if cached is not None:
                        return cached
                    return {
                        "ok": False,
                        "error": "该写操作正在处理中，请稍后重试",
                    }
        if redis_client is None:
            cached = _get_cached_result(cache_key)
            if cached is not None:
                return cached

    try:
        kwargs = args.model_dump()
        if spec.uses_context:
            kwargs["context"] = context or ToolContext()
        result = spec.func(**kwargs)
    except Exception as exc:
        log_exception("tool.execute", exc)
        if redis_client is not None:
            _redis_release(redis_client, redis_lock_key)
        return {"ok": False, "error": "工具执行失败，请稍后重试"}

    final_result = _finalize_result(name, result)

    if spec.kind == "write":
        if redis_client is not None:
            if final_result.get("ok"):
                try:
                    redis_client.set(
                        redis_result_key,
                        json.dumps(
                            {"result": final_result}, ensure_ascii=False
                        ),
                        ex=_IDEMPOTENCY_TTL_SECONDS,
                    )
                except Exception as exc:
                    logger.warning("写入幂等结果失败：%s", exc)
            _redis_release(redis_client, redis_lock_key)
        elif final_result.get("ok"):
            _cache_result(cache_key, final_result)
    return final_result


def execute_tool(
    name: str,
    raw_args: dict[str, Any] | None,
    *,
    confirmed: bool = False,
    idempotency_key: str | None = None,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    result = _execute_tool_impl(
        name,
        raw_args,
        confirmed=confirmed,
        idempotency_key=idempotency_key,
        context=context,
    )
    spec = TOOLS.get(name)
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
    secret = settings.tool_secret_value
    if not secret:
        return {"ok": False, "error": "MCP 工具签名密钥未配置"}

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
            return {"ok": False, "error": "写操作缺少幂等键，已拒绝执行"}
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
        return {
            "ok": False,
            "error": f"工具服务暂时不可用，请稍后重试（{spec.server}）",
        }
    return _finalize_result(spec.name, result)


async def execute_tool_async(
    name: str,
    raw_args: dict[str, Any] | None,
    *,
    confirmed: bool = False,
    idempotency_key: str | None = None,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    spec, _, error = _prepare_call(name, raw_args, confirmed=confirmed)
    if error is not None:
        return error
    assert spec is not None

    settings = get_settings()
    if (settings.tool_backend or "").strip().lower() == "mcp" and spec.server:
        args = spec.args_model.model_validate(raw_args or {})
        result = await _execute_remote(
            spec,
            args,
            idempotency_key=idempotency_key,
            context=context,
        )
        record_tool_audit(
            tool=spec.name,
            kind=spec.kind,
            args=args.model_dump(exclude_none=True),
            result=result,
            context=context,
            transport="mcp",
        )
        return result
    return await asyncio.to_thread(
        execute_tool,
        name,
        raw_args,
        confirmed=confirmed,
        idempotency_key=idempotency_key,
        context=context,
    )
