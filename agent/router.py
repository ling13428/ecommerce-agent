from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field, replace
from typing import Any

from agent.agent_utils import get_llm_client
from agent.session import SessionState
from core.config import get_settings
from tools.products import detect_product_id
from tools.registry import TOOLS

logger = logging.getLogger("ecommerce_agent.router")

KNOWLEDGE = "knowledge"
PRODUCT = "product"
TRANSACTION = "transaction"
HANDOFF = "handoff"
CHAT = "chat"

ROUTE_TOOL_NAMES = {
    KNOWLEDGE: ("search_knowledge",),
    PRODUCT: ("get_product",),
    TRANSACTION: (),
    HANDOFF: (),
    CHAT: (),
}

SUB_INTENT_TOOLS = {
    "order_query": ("get_order",),
    "logistics": ("get_logistics",),
    "aftersale": ("get_aftersale",),
    "cancel_order": ("get_order", "cancel_order"),
    "update_address": ("get_order", "update_address"),
    "intercept": ("get_logistics", "intercept_parcel"),
    "create_aftersale": ("get_order", "get_aftersale", "create_aftersale"),
    "payment": ("get_payment_methods",),
    "coupon": ("get_coupons",),
    "recommend": ("recommend_products",),
    "invoice": ("create_invoice",),
}

WRITE_SUB_INTENT_TOOLS = {
    "cancel_order": "cancel_order",
    "update_address": "update_address",
    "intercept": "intercept_parcel",
    "create_aftersale": "create_aftersale",
}

ORDER_ID_PATTERN = re.compile(
    r"(?:订单号?|订单编号|单号)\s*[:：]?\s*([A-Za-z0-9-]{4,})",
    re.IGNORECASE,
)
TRACKING_PATTERN = re.compile(r"\b[A-Za-z]{2}\d{9,}\b")
BARE_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{4,32}$")

INJECTION_PATTERNS = (
    re.compile(
        r"(忽略|无视|忘记).{0,8}(之前|以上|前面|系统|所有).{0,6}"
        r"(指令|提示|规则|设定|要求)"
    ),
    re.compile(
        r"(系统提示词|system\s*prompt|developer\s*mode|开发者模式|越狱|jailbreak)",
        re.IGNORECASE,
    ),
    re.compile(r"(输出|打印|重复|泄露).{0,8}(提示词|prompt|系统消息|api\s*key)"),
    re.compile(
        r"(api\s*key|access\s*token|secret\s*key|密钥|token)",
        re.IGNORECASE,
    ),
)

HUMAN_WORDS = (
    "转人工",
    "人工客服",
    "人工坐席",
    "真人客服",
    "找人工",
    "叫人工",
    "人工服务",
    "客服呢",
)
COMPLAINT_WORDS = (
    "投诉",
    "差评",
    "曝光",
    "12315",
    "消协",
    "生气",
    "气死",
    "愤怒",
    "太差",
    "垃圾",
    "骗子",
    "恶心",
    "离谱",
)

PAYMENT_WORDS = (
    "花呗",
    "分期",
    "白条",
    "货到付款",
    "货到付",
    "支付方式",
    "付款方式",
    "怎么支付",
    "能用微信",
    "能支付宝",
    "信用卡",
    "对公转账",
    "先用后付",
    "免密支付",
)
COUPON_WORDS = (
    "优惠券",
    "优惠卷",
    "满减",
    "折扣",
    "打折",
    "代金券",
    "便宜点",
    "便宜些",
    "砍价",
    "议价",
    "能少点",
    "抹零",
)
RECOMMEND_WORDS = (
    "推荐",
    "求推荐",
    "买什么",
    "预算",
    "以内",
    "新手",
    "入门",
)
RECOMMEND_WEAK_WORDS = ("选哪款", "哪款好", "选哪个", "适合")

ORDER_WORDS = (
    "订单",
    "下单",
    "购买记录",
    "订单号",
    "查单",
    "我的单",
    "买了",
)
LOGISTICS_WORDS = (
    "物流",
    "快递",
    "包裹",
    "运单",
    "派送",
    "签收",
    "到哪",
    "催发货",
    "催一下发货",
    "催单",
    "物流异常",
    "拦截",
)
AFTERSALE_WORDS = (
    "退货进度",
    "退款进度",
    "换货进度",
    "售后进度",
    "我的退款",
    "我的退货",
    "申请退货",
    "申请退款",
    "申请换货",
    "补发",
    "换货",
    "维修",
    "退款到账",
    "退款到哪",
    "取消订单",
    "改地址",
    "修改地址",
    "退货申请",
    "退款申请",
)
INVOICE_ACTION_WORDS = (
    "帮我开票",
    "帮我开发票",
    "我要开票",
    "我要开发票",
    "给我开票",
    "申请开票",
    "开一张发票",
)

PERSONAL_MARKERS = (
    "我的",
    "我买",
    "我这单",
    "订单号",
    "单号",
    "进度",
    "到哪",
    "查询",
    "帮我查",
    "查一下",
    "查订单",
    "查物流",
    "催",
    "什么时候到",
    "到账",
    "买了",
)
POLICY_MARKERS = (
    "政策",
    "规则",
    "规定",
    "制度",
    "流程",
    "条件",
    "标准",
    "要求",
    "时效",
    "说明",
    "怎么退",
    "如何退",
    "能不能退",
    "可以退吗",
    "能退吗",
    "怎么申请",
    "如何申请",
    "多久到账",
    "运费谁出",
    "谁承担",
    "几天无理由",
    "保修",
    "价保",
    "以旧换新",
    "发票",
    "开票",
    "平台介入",
    "隐私",
    "别人",
    "安全",
    "几天到",
)

BOUNDARY_WORDS = (
    "别人的订单",
    "查别人",
    "他人订单",
    "隐私",
    "个人信息",
    "身份证",
    "手机号",
    "验证码",
    "账号密码",
    "泄露",
)
BOUNDARY_PATTERNS = (
    re.compile(r"(别人|他人).{0,8}(订单|信息|隐私|查)"),
    re.compile(r"(查|看).{0,4}(别人|他人)"),
)

FACT_WORDS = (
    "多少钱",
    "价格",
    "售价",
    "几块",
    "有货",
    "库存",
    "现货",
    "缺货",
    "补货",
    "活动",
    "活动价",
    "优惠",
)
SHIPPING_WORDS = ("发货", "什么时候发货", "多久发货", "几天到", "配送")
PRICE_STOCK_WORDS = (
    "多少钱",
    "价格",
    "售价",
    "几块",
    "有货",
    "库存",
    "现货",
    "缺货",
    "补货",
    "活动",
    "优惠",
)
WRITE_INTENT_WORDS = ("我要", "帮我", "申请", "取消", "修改", "改一下", "拦截", "催")
WRITE_ACTION_WORDS = ("退货", "退款", "换货", "补发", "改地址", "取消订单")
CANCEL_INTENT_WORDS = ("取消订单", "订单取消", "不要了", "取消掉")
ADDRESS_INTENT_WORDS = (
    "改地址",
    "修改地址",
    "改一下地址",
    "修改订单",
    "地址填错",
    "地址写错",
    "换地址",
)
INTERCEPT_INTENT_WORDS = (
    "拦截快递",
    "拦截包裹",
    "快递拦截",
    "拦截一下",
    "退回快递",
    "拦截",
)
AFTERSALE_CREATE_WORDS = (
    "申请退货",
    "申请退款",
    "申请换货",
    "申请售后",
    "申请维修",
    "我要退货",
    "我要退款",
    "我要换货",
    "退货退款",
    "仅退款",
    "换货申请",
    "维修申请",
)

KNOWLEDGE_WORDS = (
    "参数",
    "规格",
    "配置",
    "续航",
    "触发",
    "键程",
    "重量",
    "尺寸",
    "材质",
    "轴体",
    "回报率",
    "dpi",
    "连接",
    "配对",
    "怎么用",
    "怎么调",
    "怎么设置",
    "如何",
    "支持",
    "兼容",
    "区别",
    "对比",
    "比较",
    "保养",
    "清洁",
    "保修",
    "退换货",
    "退货",
    "退款",
    "换货",
    "运费",
    "包邮",
    "发货",
    "发票",
    "开票",
    "价保",
    "价格保护",
    "以旧换新",
    "平台规则",
    "规则",
    "政策",
    "流程",
    "条件",
    "标准",
    "时效",
    "隐私",
    "安全",
    "别人",
    "账号",
    "验证码",
)

GREETING_PATTERN = re.compile(
    r"^(你好|您好|嗨|hi|hello|在吗|在么|有人吗)[!！。.~\s]*$",
    re.IGNORECASE,
)
THANKS_PATTERN = re.compile(r"^(谢谢|多谢|感谢|辛苦了|thanks|thank you)[!！。.~\s]*$", re.IGNORECASE)
BYE_PATTERN = re.compile(r"^(再见|拜拜|bye)[!！。.~\s]*$", re.IGNORECASE)
ACK_PATTERN = re.compile(r"^(好的|好|嗯|哦|收到|明白了|行|可以)[!！。.~\s]*$")


@dataclass(frozen=True)
class RouteResult:
    route: str
    sub_intent: str
    action: str
    confidence: float = 0.9
    source: str = "rule"
    slots: dict[str, str] = field(default_factory=dict)
    secondary_routes: tuple[str, ...] = ()
    reason: str | None = None
    message: str | None = None

    @property
    def routes(self) -> tuple[str, ...]:
        return (self.route, *self.secondary_routes)

    @property
    def allowed_tools(self) -> set[str]:
        allowed: set[str] = {"transfer_to_human"}
        for route in self.routes:
            allowed.update(ROUTE_TOOL_NAMES.get(route, ()))
        allowed.update(SUB_INTENT_TOOLS.get(self.sub_intent, ()))
        return {name for name in allowed if name in TOOLS}

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "sub_intent": self.sub_intent,
            "action": self.action,
            "confidence": self.confidence,
            "source": self.source,
            "routes": list(self.routes),
            "slots": dict(self.slots),
            "reason": self.reason,
            "allowed_tools": sorted(self.allowed_tools),
        }


ROUTE_INSTRUCTIONS = {
    KNOWLEDGE: (
        "本轮意图是商品知识/政策问答。只能使用 search_knowledge 检索，"
        "回答必须带 doc_id/section/source；检索低分或空结果时转人工，不要编造。"
    ),
    PRODUCT: (
        "本轮意图是商品实时数据。只能使用 get_product 查询价格、库存、活动、"
        "发货时效；不要用 search_knowledge 回答实时数据。缺少商品型号时先追问。"
    ),
    TRANSACTION: (
        "本轮意图是订单、物流、售后、支付、优惠或推荐等业务问题。"
        "只能使用对应业务工具；没有可用工具时调用 transfer_to_human，"
        "禁止用 search_knowledge 猜测业务事实。"
    ),
}


def prompt_for_route(route: RouteResult) -> str:
    parts = [ROUTE_INSTRUCTIONS.get(route.route, "")]
    if route.secondary_routes:
        for item in route.secondary_routes:
            text = ROUTE_INSTRUCTIONS.get(item)
            if text:
                parts.append(text)
    if route.sub_intent:
        parts.append(f"子意图：{route.sub_intent}。")
    write_tool = WRITE_SUB_INTENT_TOOLS.get(route.sub_intent)
    if write_tool:
        parts.append(
            f"用户已明确要求执行写操作：直接调用 {write_tool}，"
            "由服务端生成确认提示；不要先用查询工具确认，"
            "也不要用自然语言代替工具调用。"
        )
    if route.slots:
        slots = "，".join(f"{key}={value}" for key, value in route.slots.items())
        parts.append(f"已提取槽位：{slots}。")
    parts.append("本轮只能调用允许的工具；不要调用未提供的工具。")
    return "\n".join(part for part in parts if part)


def _contains(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def _is_policy_question(text: str) -> bool:
    has_policy = _contains(text, POLICY_MARKERS)
    return has_policy and not _contains(text, PERSONAL_MARKERS)


def _extract_slots(text: str) -> dict[str, str]:
    slots: dict[str, str] = {}
    order_match = ORDER_ID_PATTERN.search(text)
    if order_match:
        slots["order_id"] = order_match.group(1)
    tracking_match = TRACKING_PATTERN.search(text)
    if tracking_match:
        slots["tracking_no"] = tracking_match.group(0)
    product_id = detect_product_id(text)
    if product_id:
        slots["product_id"] = product_id
    return slots


def _last_assistant_message(session: SessionState) -> str:
    for message in reversed(session.messages):
        if message.get("role") == "assistant":
            return str(message.get("content", ""))
    return ""


def _is_short_reply(value: str) -> bool:
    return bool(BARE_ID_PATTERN.fullmatch(value.strip()))


def _knowledge(
    text: str,
    sub_intent: str,
    slots: dict[str, str],
    confidence: float = 0.9,
    secondary: tuple[str, ...] = (),
) -> RouteResult:
    return RouteResult(
        route=KNOWLEDGE,
        sub_intent=sub_intent,
        action="rag",
        confidence=confidence,
        slots=slots,
        secondary_routes=secondary,
    )


def _product(
    slots: dict[str, str], secondary: tuple[str, ...] = ()
) -> RouteResult:
    return RouteResult(
        route=PRODUCT,
        sub_intent="product_realtime",
        action="tool",
        confidence=0.95,
        slots=slots,
        secondary_routes=secondary,
    )


def _transaction(
    text: str, sub_intent: str, slots: dict[str, str]
) -> RouteResult:
    available = [
        name for name in SUB_INTENT_TOOLS.get(sub_intent, ()) if name in TOOLS
    ]
    if available:
        return RouteResult(
            route=TRANSACTION,
            sub_intent=sub_intent,
            action="tool",
            confidence=0.95,
            slots=slots,
        )

    messages = {
        "order_query": "订单查询需要人工客服帮你核实，正在为你转接，请稍候。",
        "logistics": "物流进度需要人工客服帮你查询，正在为你转接，请稍候。",
        "aftersale": "售后进度需要人工客服帮你核实，正在为你转接，请稍候。",
        "payment": "支付方式需要人工客服帮你确认，正在为你转接，请稍候。",
        "coupon": "优惠券和活动规则需要人工客服帮你确认，正在为你转接，请稍候。",
        "recommend": "选款建议我先帮你转给人工客服，请稍候。",
        "invoice": "开票事项需要人工客服协助，正在为你转接，请稍候。",
        "cancel_order": "取消订单需要人工客服协助，正在为你转接，请稍候。",
        "update_address": "修改地址需要人工客服协助，正在为你转接，请稍候。",
        "intercept": "拦截快递需要人工客服协助，正在为你转接，请稍候。",
        "create_aftersale": "售后申请需要人工客服协助，正在为你转接，请稍候。",
    }
    return RouteResult(
        route=TRANSACTION,
        sub_intent=sub_intent,
        action="handoff",
        confidence=0.9,
        slots=slots,
        reason=f"{sub_intent}_tool_unavailable",
        message=messages.get(sub_intent, "这个问题需要人工客服协助，正在为你转接。"),
    )


def _handoff(
    sub_intent: str, reason: str, message: str, slots: dict[str, str]
) -> RouteResult:
    return RouteResult(
        route=HANDOFF,
        sub_intent=sub_intent,
        action="handoff",
        confidence=0.98,
        slots=slots,
        reason=reason,
        message=message,
    )


def _clarify(
    message: str, sub_intent: str, slots: dict[str, str]
) -> RouteResult:
    return RouteResult(
        route=CHAT,
        sub_intent=sub_intent,
        action="clarify",
        confidence=0.75,
        slots=slots,
        message=message,
    )


def _reply(sub_intent: str, message: str) -> RouteResult:
    return RouteResult(
        route=CHAT,
        sub_intent=sub_intent,
        action="reply",
        confidence=0.95,
        message=message,
    )


def route_message(message: str, session: SessionState) -> RouteResult:
    text = message.strip()
    lowered = text.lower()
    slots = _extract_slots(text)

    if not text:
        return _clarify("请告诉我你想咨询的问题。", "clarify", slots)

    if any(pattern.search(lowered) for pattern in INJECTION_PATTERNS):
        return _handoff(
            "injection",
            "prompt_injection",
            "这个请求我不能处理，已为你转接人工客服。",
            slots,
        )

    if _contains(lowered, HUMAN_WORDS):
        return _handoff(
            "human",
            "user_requested_human",
            "好的，正在为你转接人工客服，请稍候。",
            slots,
        )

    if _contains(lowered, COMPLAINT_WORDS):
        return _handoff(
            "complaint",
            "negative_emotion",
            "很抱歉给你带来不好的体验，正在为你转接人工客服，请稍候。",
            slots,
        )

    if _contains(lowered, BOUNDARY_WORDS) or any(
        pattern.search(lowered) for pattern in BOUNDARY_PATTERNS
    ):
        return _knowledge(text, "safety_boundary", slots)

    last_assistant = _last_assistant_message(session)
    if (
        ("订单号" in last_assistant or "物流单号" in last_assistant)
        and _is_short_reply(text)
    ):
        slots.setdefault("order_id", text)
        return _transaction(text, "order_query", slots)

    policy_question = _is_policy_question(lowered)

    if _contains(lowered, INVOICE_ACTION_WORDS):
        return _transaction(text, "invoice", slots)

    if not policy_question:
        if _contains(lowered, CANCEL_INTENT_WORDS):
            return _transaction(text, "cancel_order", slots)
        if _contains(lowered, ADDRESS_INTENT_WORDS):
            return _transaction(text, "update_address", slots)
        if _contains(lowered, INTERCEPT_INTENT_WORDS):
            return _transaction(text, "intercept", slots)
        if _contains(lowered, AFTERSALE_CREATE_WORDS):
            return _transaction(text, "create_aftersale", slots)
        if _contains(lowered, WRITE_INTENT_WORDS) and _contains(
            lowered, WRITE_ACTION_WORDS
        ):
            return _transaction(text, "create_aftersale", slots)
        if _contains(lowered, PAYMENT_WORDS):
            return _transaction(text, "payment", slots)
        if _contains(lowered, COUPON_WORDS):
            return _transaction(text, "coupon", slots)
        if _contains(lowered, RECOMMEND_WORDS):
            return _transaction(text, "recommend", slots)
        if (
            _contains(lowered, RECOMMEND_WEAK_WORDS)
            and "product_id" not in slots
            and not _contains(lowered, ("对比", "区别", "比较"))
        ):
            return _transaction(text, "recommend", slots)

        has_personal = _contains(lowered, PERSONAL_MARKERS)
        has_order_context = (
            "order_id" in slots
            or "tracking_no" in slots
            or _contains(lowered, ORDER_WORDS)
            or _contains(lowered, LOGISTICS_WORDS)
            or _contains(lowered, AFTERSALE_WORDS)
        )
        if has_order_context and (
            has_personal
            or _contains(lowered, ORDER_WORDS)
            or (
                _contains(lowered, LOGISTICS_WORDS)
                and "product_id" not in slots
            )
        ):
            if _contains(lowered, LOGISTICS_WORDS) or "tracking_no" in slots:
                sub_intent = "logistics"
            elif _contains(lowered, AFTERSALE_WORDS):
                sub_intent = "aftersale"
            else:
                sub_intent = "order_query"
            return _transaction(text, sub_intent, slots)

    if "product_id" in slots:
        if _contains(lowered, FACT_WORDS) or _contains(lowered, SHIPPING_WORDS):
            secondary = (
                (KNOWLEDGE,)
                if _contains(lowered, KNOWLEDGE_WORDS)
                else ()
            )
            return _product(slots, secondary)

    if _contains(lowered, FACT_WORDS) or _contains(lowered, SHIPPING_WORDS):
        if _contains(lowered, PRICE_STOCK_WORDS):
            return _clarify(
                "请问是哪款商品？可以告诉我型号或编号，例如 VK75 Pro、P2001。",
                "product_clarify",
                slots,
            )

    if (
        policy_question
        or "product_id" in slots
        or _contains(lowered, KNOWLEDGE_WORDS)
    ):
        return _knowledge(text, "knowledge", slots)

    if GREETING_PATTERN.fullmatch(lowered):
        return _reply("greeting", "你好，我是烬狐客服，可以帮你查商品、订单和售后问题。")
    if THANKS_PATTERN.fullmatch(lowered):
        return _reply("thanks", "不客气，还有其他问题随时问我。")
    if BYE_PATTERN.fullmatch(lowered):
        return _reply("bye", "好的，再见，祝你购物愉快。")
    if ACK_PATTERN.fullmatch(lowered):
        return _reply("ack", "好的，有需要随时告诉我。")

    if len(text) <= 3:
        return _clarify(
            "可以再具体一点吗？比如商品型号、订单号，或者想咨询的问题。",
            "clarify",
            slots,
        )

    return _clarify(
        "我主要帮你处理商品咨询、订单物流和售后问题，可以再具体说一下吗？",
        "out_of_scope",
        slots,
    )


ALLOWED_ROUTES = {KNOWLEDGE, PRODUCT, TRANSACTION, HANDOFF, CHAT}

ALLOWED_SUB_INTENTS = set(SUB_INTENT_TOOLS) | {
    "product_realtime",
    "knowledge",
    "safety_boundary",
    "smalltalk",
    "llm_handoff",
}

ROUTE_LLM_SYSTEM_PROMPT = """你是电商客服的意图分类器，只输出一个 JSON 对象，不要输出 Markdown 或解释。
路由定义：
- product：询问具体商品的实时价格、库存、活动、发货时效
- transaction：订单查询、物流进度、售后进度、取消/改地址/拦截快递、支付方式、优惠券、选款推荐、发票
- knowledge：商品参数/卖点/用法/保养/FAQ，店铺与平台政策（退货、发票、价保、以旧换新、隐私边界等）
- handoff：用户要求人工、投诉或情绪负面、要求越权/敏感操作
- chat：寒暄、感谢、告别、与业务无关的闲聊

输出字段：
{"route": "product|transaction|knowledge|handoff|chat",
 "sub_intent": "order_query|logistics|aftersale|payment|coupon|recommend|invoice|cancel_order|update_address|intercept|create_aftersale|product_realtime|knowledge|safety_boundary|smalltalk|llm_handoff",
 "confidence": 0.0,
 "reason": "一句话说明"}

判断规则：
1. 用户说“我的/我买的/这个订单/包裹”等个人业务信息时，优先 transaction。
2. 只问规则、参数、用法等描述性内容时选 knowledge。
3. 无法判断时选 chat，并把 confidence 设为 0.4 以下。
4. 不要编造订单号、物流单号或商品编号。"""


@dataclass(frozen=True)
class RouteDecision:
    route: str
    sub_intent: str
    confidence: float
    reason: str = ""


def needs_llm_route(
    l1: RouteResult, text: str, settings: Any
) -> bool:
    if not getattr(settings, "router_llm_enabled", False):
        return False
    if l1.action == "handoff":
        return False
    if l1.route == KNOWLEDGE and l1.sub_intent == "knowledge":
        if "product_id" in l1.slots:
            return False
        return not _is_policy_question(text.lower())
    if l1.action == "clarify":
        return True
    return l1.confidence < float(
        getattr(settings, "router_llm_min_confidence", 0.7)
    )


def _strip_code_fence(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    return content.strip()


async def _request_route_decision(
    message: str,
    session: SessionState,
    l1: RouteResult,
    client: Any,
    settings: Any,
) -> RouteDecision:
    payload = {
        "message": message,
        "recent_messages": session.snapshot()[-6:],
        "rule_hint": {
            "route": l1.route,
            "sub_intent": l1.sub_intent,
            "confidence": l1.confidence,
        },
    }
    async with asyncio.timeout(float(settings.router_llm_timeout)):
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": ROUTE_LLM_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
            temperature=0,
            max_tokens=int(settings.router_llm_max_tokens),
            response_format={"type": "json_object"},
        )

    content = response.choices[0].message.content or ""
    data = json.loads(_strip_code_fence(content))
    if not isinstance(data, dict):
        raise ValueError("分类结果不是 JSON 对象")

    route = str(data.get("route") or "").strip().lower()
    if route not in ALLOWED_ROUTES:
        raise ValueError(f"未知路由：{route}")

    sub_intent = str(data.get("sub_intent") or "").strip()
    if sub_intent not in ALLOWED_SUB_INTENTS:
        sub_intent = ""

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return RouteDecision(
        route=route,
        sub_intent=sub_intent,
        confidence=confidence,
        reason=str(data.get("reason") or "").strip(),
    )


def _apply_decision(
    decision: RouteDecision, l1: RouteResult, text: str
) -> RouteResult:
    slots = dict(l1.slots)
    route = decision.route
    sub_intent = decision.sub_intent

    if route == KNOWLEDGE:
        base = _knowledge(
            text, sub_intent or "knowledge", slots
        )
    elif route == PRODUCT:
        base = _product(slots)
    elif route == TRANSACTION:
        if sub_intent not in SUB_INTENT_TOOLS:
            sub_intent = "order_query"
        base = _transaction(text, sub_intent, slots)
    elif route == HANDOFF:
        base = _handoff(
            sub_intent or "llm_handoff",
            "llm_classified_handoff",
            "好的，正在为你转接人工客服，请稍候。",
            slots,
        )
    else:
        base = RouteResult(
            route=CHAT,
            sub_intent=sub_intent or "smalltalk",
            action="agent",
            confidence=decision.confidence,
            slots=slots,
            reason=decision.reason or None,
        )

    return replace(
        base,
        confidence=decision.confidence,
        source="llm",
        reason=decision.reason or base.reason,
    )


async def route_message_l2(
    message: str,
    session: SessionState,
    client: Any = None,
    settings: Any = None,
) -> RouteResult:
    l1 = route_message(message, session)
    settings = settings or get_settings()
    text = (message or "").strip()

    if not text or not needs_llm_route(l1, text, settings):
        return l1

    try:
        client = client or get_llm_client()
        decision = await _request_route_decision(
            text, session, l1, client, settings
        )
    except Exception as exc:
        logger.warning("路由 L2 分类失败，保留规则结果：%s", exc)
        return l1

    if decision.confidence < float(settings.router_llm_min_confidence):
        logger.info(
            "路由 L2 置信度不足（%.2f），保留规则结果 %s/%s",
            decision.confidence,
            l1.route,
            l1.sub_intent,
        )
        return l1

    return _apply_decision(decision, l1, text)
