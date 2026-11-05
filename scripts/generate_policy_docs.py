from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag.clean import DocumentError, parse_document  # noqa: E402

DOCS_DIR = ROOT / "data" / "policies" / "docs"
RAW_DIR = ROOT / "data" / "policies" / "raw"
REGISTRY = ROOT / "data" / "policies" / "registry.csv"
README = ROOT / "data" / "policies" / "README.md"

PLATFORM = "星潮商城"
STORE = "烬狐官方旗舰店"
STORE_SOURCE = "烬狐官方店铺政策（模拟）"
PLATFORM_SOURCE = "星潮商城平台规则（模拟）"
EFFECTIVE_DATE = "2026-01-01"
VALID_UNTIL = "2026-12-31"
REVIEW_DATE = "2026-12-01"

FRONT_KEYS = (
    "doc_id",
    "product_id",
    "title",
    "doc_type",
    "category",
    "source",
    "authority_level",
    "version",
    "effective_date",
    "valid_until",
    "review_date",
    "deprecated",
    "policy_domain",
    "region",
    "scope",
    "supersedes",
    "superseded_by",
)

RET_SHIPPING_ROWS = [
    ("键盘", "12–20 元", "0 元", "按实际重量和距离计算"),
    ("鼠标", "8–12 元", "0 元", "含普通快递"),
    ("耳机", "10–15 元", "0 元", "含普通快递"),
    ("配件", "6–10 元", "0 元", "键帽、脚贴等"),
]

LOG_SLA_ROWS = [
    ("珠三角", "1 天", "迅风快递", "深圳仓发货"),
    ("长三角", "2 天", "迅风快递", "武汉/天津仓发货"),
    ("京津冀", "2 天", "迅风快递", "天津仓发货"),
    ("华中/华南", "2–3 天", "迅风快递", "按就近仓分配"),
    ("西南/西北", "3–5 天", "迅风快递/云链物流", "部分区域转云链"),
    ("偏远地区", "5–7 天", "云链物流", "以物流揽收为准"),
    ("港澳台/海外", "暂不支持", "—", "不发货"),
]

PRI_WINDOW_ROWS = [
    ("普通用户", "7 天", "店铺在售商品", "签收次日起算"),
    ("星潮会员", "15 天", "店铺在售商品", "需在会员有效期内"),
    ("秒杀/清仓", "不适用", "—", "活动价不参与价保"),
    ("以旧换新订单", "不适用", "—", "按以旧换新规则处理"),
]

TRD_VALUATION_ROWS = [
    ("键盘", "A（95 新）", "200–500 元", "功能正常、外观轻微使用痕迹"),
    ("键盘", "B（85 新）", "100–300 元", "功能正常、明显使用痕迹"),
    ("键盘", "C（7 成新）", "50–150 元", "功能正常、外观磨损或缺少配件"),
    ("键盘", "D（故障机）", "0–50 元", "按键失灵、进水或主板故障"),
    ("鼠标", "A（95 新）", "100–300 元", "功能正常、脚贴轻微磨损"),
    ("鼠标", "B（85 新）", "50–150 元", "功能正常、外观明显使用"),
    ("鼠标", "C（7 成新）", "20–80 元", "双击、滚轮异常或缺少接收器"),
    ("鼠标", "D（故障机）", "0–30 元", "无法连接、进水或主板故障"),
    ("耳机", "A（95 新）", "80–250 元", "功能正常、耳罩轻微使用"),
    ("耳机", "B（85 新）", "40–120 元", "功能正常、耳罩明显使用"),
    ("耳机", "C（7 成新）", "15–60 元", "单边无声、麦克风异常"),
    ("耳机", "D（故障机）", "0–20 元", "进水、断梁或无法开机"),
]

INV_TYPE_ROWS = [
    ("电子普通发票", "个人/企业", "13%", "1–3 个工作日", "默认开具，可下载 PDF"),
    ("增值税专用发票", "企业一般纳税人", "13%", "3–7 个工作日", "需上传资质并邮寄"),
    ("电子发票（个人）", "个人", "13%", "1–3 个工作日", "抬头为个人姓名"),
    ("红字发票", "退货/换开", "13%", "3–7 个工作日", "需先完成退款或换开审核"),
]


def _md_table(headers: list[str], rows: list[tuple]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    lines.extend(
        "| " + " | ".join(str(cell) for cell in row) + " |" for row in rows
    )
    return "\n".join(lines)


def _front_matter(policy: dict[str, Any]) -> str:
    lines = ["---"]
    for key in FRONT_KEYS:
        value = policy.get(key, "")
        if value not in (None, ""):
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def _render(policy: dict[str, Any]) -> str:
    body = f"# {policy['title']}\n\n" + "\n\n".join(
        f"## {heading}\n\n{text}" for heading, text in policy["sections"]
    )
    return f"{_front_matter(policy)}\n\n{body}\n"


def _p(
    doc_id: str,
    title: str,
    doc_type: str,
    category: str,
    product_id: str,
    source: str,
    authority: str,
    version: str,
    effective_date: str,
    policy_domain: str,
    scope: str,
    sections: list[tuple[str, str]],
    *,
    deprecated: str = "false",
    valid_until: str = VALID_UNTIL,
    review_date: str = REVIEW_DATE,
    supersedes: str = "",
    superseded_by: str = "",
) -> dict[str, Any]:
    return {
        "doc_id": doc_id,
        "product_id": product_id,
        "title": title,
        "doc_type": doc_type,
        "category": category,
        "source": source,
        "authority_level": authority,
        "version": version,
        "effective_date": effective_date,
        "valid_until": valid_until,
        "review_date": review_date,
        "deprecated": deprecated,
        "policy_domain": policy_domain,
        "region": "全国",
        "scope": scope,
        "supersedes": supersedes,
        "superseded_by": superseded_by,
        "sections": sections,
    }


POLICIES: list[dict[str, Any]] = [
    _p(
        "POL-RET-001",
        "退换货政策总则（2026 版）",
        "store_policy",
        "售后",
        "STORE",
        STORE_SOURCE,
        "高",
        "v2",
        EFFECTIVE_DATE,
        "退换货",
        "店铺",
        [
            (
                "适用范围",
                f"本政策适用于在{PLATFORM}「{STORE}」购买的键盘、鼠标、耳机及相关配件。"
                "定制款、二手商品、赠品和积分兑换商品按单独说明处理。"
                "本政策自 2026-01-01 起生效，替代 2024 版退换货政策。",
            ),
            (
                "七天无理由退货",
                "买家自签收次日起 7 个自然日内，商品完好、配件齐全、不影响二次销售的，可申请无理由退货。"
                "定制款、已激活或明显使用过的商品、拆封的入耳式耳机耳塞和耳罩等个人卫生类商品，不支持无理由退货。"
                "无理由退货运费由买家承担；订单含运费险的，可按运费险规则申请赔付。",
            ),
            (
                "十五天质量问题退换",
                "自签收次日起 15 个自然日内，商品出现非人为损坏的性能故障，可申请免费换货或维修。"
                "需提供故障视频、照片和订单信息；必要时寄回检测，检测期间运费由店铺承担。"
                "人为损坏、进液、私自拆修或非正常使用造成的故障，不适用免费换货。",
            ),
            (
                "退款时效",
                "退货审核通过并完成质检后，退款按原支付路径退回。"
                "微信、支付宝一般 1–3 个工作日到账；银行卡一般 3–15 个工作日到账；"
                "星潮余额一般 1 个工作日内到账。具体到账时间以支付机构为准。",
            ),
            (
                "版本说明",
                "2024 版政策规定 15 天无理由退货，已于 2025-12-31 失效。"
                "2026-01-01 起下单的订单统一适用本政策。历史订单按当时生效的版本处理。",
            ),
        ],
        supersedes="POL-RET-002",
    ),
    _p(
        "POL-RET-002",
        "退换货政策总则（2024 版，已失效）",
        "store_policy",
        "售后",
        "STORE",
        STORE_SOURCE,
        "中",
        "v1",
        "2024-01-01",
        "退换货",
        "店铺",
        [
            (
                "历史版本说明",
                "本文档为 2024 版退换货政策，规定 15 天无理由退货。"
                "该版本已于 2025-12-31 失效，仅供查询 2025-12-31 及以前下单的历史订单，不得作为当前规则使用。",
            ),
            (
                "旧版规则",
                "签收次日起 15 个自然日内，商品完好、不影响二次销售的，可申请无理由退货。"
                "质量问题 30 个自然日内可申请免费换货或维修。"
                "无理由退货运费由买家承担；质量问题退货运费由店铺承担。",
            ),
            (
                "替代关系",
                "2026-01-01 起由 POL-RET-001《退换货政策总则（2026 版）》替代。"
                "新旧版本冲突时，以订单下单时生效的版本为准。",
            ),
        ],
        deprecated="true",
        valid_until="2025-12-31",
        review_date="",
        superseded_by="POL-RET-001",
    ),
    _p(
        "POL-RET-003",
        "七天无理由退货适用条件与例外",
        "store_policy",
        "售后",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "退换货",
        "店铺",
        [
            (
                "完好标准",
                "商品本体、配件、包装、说明书、赠品和发票需齐全；商品无划痕、无磕碰、无进液、无明显使用痕迹；"
                "键盘键帽无打油、鼠标脚贴无明显磨损、耳机耳罩无污渍。"
                "建议保留开箱视频和商品照片，便于发生争议时举证。",
            ),
            (
                "不支持无理由退货的情况",
                "定制刻字、定制配色或按买家要求改装的商品；已激活、已注册或已绑定账号的商品；"
                "拆封的入耳式耳机耳塞、耳罩等个人卫生类商品；人为损坏、进液、私自拆修的商品；"
                "缺件、包装严重破损或影响二次销售的商品；赠品、积分兑换商品和二手商品。",
            ),
            (
                "申请与审核",
                "买家在订单详情页提交换货或退货申请，选择原因并上传照片/视频。"
                "店铺在 24 小时内完成初审；需要补充材料的，审核时间自材料补齐之日起重新计算。"
                "审核通过后，买家按页面提示寄回商品。",
            ),
        ],
    ),
    _p(
        "POL-RET-004",
        "质量问题退换货与检测流程",
        "store_policy",
        "售后",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "退换货",
        "店铺",
        [
            (
                "受理范围",
                "签收次日起 15 个自然日内，商品出现非人为损坏的性能故障，可申请免费换货或维修。"
                "常见故障包括按键失灵、连击、无法连接、单边无声、麦克风异常、充电异常等。",
            ),
            (
                "检测流程",
                "买家提交故障视频和照片后，客服进行远程排查；无法远程确认的，寄回指定检测点。"
                "检测一般在 3–7 个工作日内完成。检测确认为质量问题的，店铺承担来回运费并安排换货或维修；"
                "检测确认为人为损坏的，店铺提供付费维修方案，买家可选择维修或退回。",
            ),
            (
                "换货与维修",
                "换货优先安排同型号同规格商品；无同款库存时，可协商更换同价位商品或退款。"
                "维修使用原厂或同等规格配件，维修后享受剩余保修期。"
                "换货商品自签收之日起重新计算 7 天无理由期限。",
            ),
        ],
    ),
    _p(
        "POL-RET-005",
        "退货运费、运费险与包装要求",
        "store_policy",
        "售后",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "退换货",
        "店铺",
        [
            (
                "运费承担",
                "质量问题退换货，来回运费由店铺承担；七天无理由退货，寄回运费由买家承担。"
                "偏远地区、港澳台及海外订单的运费按实际物流报价处理。"
                "运费参考标准如下，实际以物流揽收价格为准。",
            ),
            ("运费参考", _md_table(["商品类别", "无理由退货运费", "质量问题退货运费", "说明"], RET_SHIPPING_ROWS)),
            (
                "运费险",
                "订单含运费险的，买家寄回后可在线申请理赔。理赔金额以保险公司核定为准，"
                "一般覆盖首重运费，不覆盖保价费、包装费和偏远地区附加费。"
                "运费险理赔不影响商品退款进度。",
            ),
            (
                "包装要求",
                "请使用原包装或同等强度的包装，键盘和耳机建议加缓冲材料，避免运输磕碰。"
                "因包装不当导致商品损坏的，可能影响退款金额或换货判定。",
            ),
        ],
    ),
    _p(
        "POL-RET-006",
        "退款时效与退款路径",
        "store_policy",
        "售后",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "退换货",
        "店铺",
        [
            (
                "退款路径",
                "退款默认按原支付路径退回：微信/支付宝退回原账户，银行卡退回原卡，"
                "星潮余额退回余额账户。组合支付订单按各支付渠道实际支付金额分别退回。",
            ),
            (
                "退款时效",
                "退货商品签收并完成质检后，店铺在 24 小时内发起退款。"
                "微信、支付宝一般 1–3 个工作日到账；银行卡一般 3–15 个工作日到账；"
                "星潮余额一般 1 个工作日内到账。具体到账时间以支付机构为准。",
            ),
            (
                "部分退款与优惠",
                "部分退货按商品实付金额比例退款，运费和已使用的优惠按订单规则分摊。"
                "整单退货时，未使用的优惠券按平台规则退回；已过期的优惠券不补发。"
                "赠品需随主商品一并退回，赠品缺失可能从退款金额中扣除相应价值。",
            ),
        ],
    ),
    _p(
        "POL-RET-007",
        "换货、补发与维修规则",
        "store_policy",
        "售后",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "退换货",
        "店铺",
        [
            (
                "换货规则",
                "质量问题换货优先安排同型号同规格商品；颜色和版本以实际库存为准。"
                "无同款库存时，可协商更换同价位商品或全额退款。"
                "换货商品自签收之日起重新计算 7 天无理由期限。",
            ),
            (
                "补发规则",
                "签收后发现缺件、错发或运输破损的，请在 48 小时内联系客服，提供开箱视频和实物照片。"
                "核实后优先补发缺失配件或商品；无法补发的，按缺件价值退款。",
            ),
            (
                "维修规则",
                "超出 15 天换货期但仍在保修期内的质量问题，可申请维修。"
                "维修一般在 7–15 个工作日内完成，维修后享受剩余保修期。"
                "人为损坏、进液、私自拆修不在免费保修范围内。",
            ),
        ],
    ),
    _p(
        "POL-RET-008",
        "退换货常见问题",
        "policy_faq",
        "售后",
        "STORE",
        STORE_SOURCE,
        "中",
        "v1",
        EFFECTIVE_DATE,
        "退换货",
        "店铺",
        [
            (
                "常见问题",
                "**Q：拆封后还能七天无理由退货吗？**\n"
                "A：商品完好、配件齐全且不影响二次销售的，可以申请；拆封的入耳式耳机耳塞、耳罩等个人卫生类商品除外。\n\n"
                "**Q：退货运费谁出？**\n"
                "A：七天无理由退货由买家承担；质量问题退换货由店铺承担；含运费险的订单可按运费险规则理赔。\n\n"
                "**Q：退款多久到账？**\n"
                "A：质检完成后 24 小时内发起退款，微信/支付宝一般 1–3 个工作日，银行卡一般 3–15 个工作日。\n\n"
                "**Q：赠品需要退回吗？**\n"
                "A：需要。赠品缺失可能从退款金额中扣除相应价值；赠品已使用或损坏的，按实际情况协商。\n\n"
                "**Q：可以换颜色或换型号吗？**\n"
                "A：质量问题优先换同型号同规格；颜色和版本以库存为准。无理由换货需满足商品完好条件，差价按订单规则处理。\n\n"
                "**Q：超过 7 天还能退吗？**\n"
                "A：超过 7 天不再支持无理由退货；质量问题可在 15 天内申请换货或维修，保修期内可申请维修。\n\n"
                "**Q：定制款能退吗？**\n"
                "A：定制刻字、定制配色或按买家要求改装的商品不支持七天无理由退货；质量问题按检测结果处理。",
            )
        ],
    ),
    _p(
        "POL-INV-001",
        "发票类型与开票范围",
        "store_policy",
        "财务",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "发票",
        "店铺",
        [
            (
                "发票类型",
                "店铺支持电子普通发票和增值税专用发票。个人买家默认开具电子普通发票；"
                "企业买家可选择电子普通发票或增值税专用发票。电子发票与纸质发票具有同等法律效力。"
                "发票内容按实际商品明细开具，不支持变更品名或拆分无关项目。",
            ),
            ("类型对比", _md_table(["发票类型", "适用对象", "税率", "开具时限", "说明"], INV_TYPE_ROWS)),
            (
                "开票范围",
                "可开票金额为订单实付商品金额及可开票运费。优惠券、平台补贴、赠品和积分抵扣部分按平台规则处理，"
                "不重复开票。退货、退款或换货后，需按实际成交金额开具或红冲发票。",
            ),
            (
                "开票时限",
                "订单完成后 30 个自然日内可申请开票；超过 30 天的订单需转人工审核。"
                "电子普通发票一般在 1–3 个工作日内开具，增值税专用发票一般在 3–7 个工作日内开具。",
            ),
        ],
    ),
    _p(
        "POL-INV-002",
        "开票流程与所需信息",
        "store_policy",
        "财务",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "发票",
        "店铺",
        [
            (
                "个人发票",
                "在订单详情页选择“申请开票”，填写个人抬头和接收邮箱，提交后等待开具。"
                "个人抬头一般为买家姓名，也可按平台允许的规则填写。",
            ),
            (
                "企业发票",
                "企业电子普通发票需填写企业名称、纳税人识别号和接收邮箱；"
                "增值税专用发票还需提供地址、电话、开户行和银行账号，并上传一般纳税人资质证明。",
            ),
            (
                "开具与下载",
                "电子发票开具后会发送到预留邮箱，也可在订单详情页下载 PDF。"
                "增值税专用发票审核通过后按预留地址邮寄，邮寄时间不计入开具时限。",
            ),
            (
                "信息修改",
                "发票开具前可修改抬头和税号；已开具的发票需通过换开或红冲处理。"
                "因买家提供信息错误导致的发票问题，由买家承担相应责任。",
            ),
        ],
    ),
    _p(
        "POL-INV-003",
        "电子发票下载、换开与红冲",
        "store_policy",
        "财务",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "发票",
        "店铺",
        [
            (
                "下载方式",
                "电子发票可在订单详情页“发票信息”中下载，也可通过开票时预留的邮箱查收。"
                "下载链接长期有效；如链接失效，可联系客服重新发送。",
            ),
            (
                "换开规则",
                "发票开具后 60 个自然日内，因抬头、税号或金额错误可申请换开。"
                "换开需先红冲原发票，再重新开具；已用于报销或抵扣的发票，需买家先完成内部处理。",
            ),
            (
                "红冲规则",
                "发生退货、退款或换货导致金额变化时，需对原发票进行红冲。"
                "跨月红冲一般 3–7 个工作日完成；已认证的专用发票需买家配合提供红字信息表。"
                "红冲完成后原发票作废，买家需使用新发票报销。",
            ),
        ],
    ),
    _p(
        "POL-INV-004",
        "增值税专用发票（企业客户）",
        "store_policy",
        "财务",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "发票",
        "店铺",
        [
            (
                "适用对象",
                "增值税专用发票仅面向依法登记且为增值税一般纳税人的企业客户开具。"
                "个人、非一般纳税人企业和无法提供完整资质的主体，默认开具电子普通发票。",
            ),
            (
                "资质与信息",
                "申请专票需提供营业执照、一般纳税人资质证明、开票信息（名称、税号、地址、电话、开户行、账号）"
                "和收件信息。资质审核一般 1–3 个工作日。",
            ),
            (
                "开具与邮寄",
                "专票审核通过后 3–7 个工作日内开具并邮寄，邮寄费用由店铺承担。"
                "发生退货或换货时，企业需配合完成红冲；已抵扣的专票按税务规定处理。"
                "专票遗失不补开原件，请企业买家妥善保管。",
            ),
        ],
    ),
    _p(
        "POL-INV-005",
        "发票常见问题",
        "policy_faq",
        "财务",
        "STORE",
        STORE_SOURCE,
        "中",
        "v1",
        EFFECTIVE_DATE,
        "发票",
        "店铺",
        [
            (
                "常见问题",
                "**Q：什么时候可以开发票？**\n"
                "A：订单完成后 30 个自然日内可申请；电子普票一般 1–3 个工作日，专票一般 3–7 个工作日。\n\n"
                "**Q：个人可以开专票吗？**\n"
                "A：不可以。专票仅面向增值税一般纳税人企业，个人默认开具电子普通发票。\n\n"
                "**Q：发票金额包含运费吗？**\n"
                "A：可开票运费会计入发票金额；优惠券、平台补贴和赠品按平台规则处理，不重复开票。\n\n"
                "**Q：退货后发票怎么办？**\n"
                "A：需对原发票进行红冲；跨月红冲一般 3–7 个工作日，已认证专票需配合提供红字信息表。\n\n"
                "**Q：可以换抬头吗？**\n"
                "A：开具后 60 天内可申请换开，需先红冲原发票再重新开具。\n\n"
                "**Q：电子发票能报销吗？**\n"
                "A：可以。电子普通发票与纸质发票具有同等法律效力，按单位财务要求打印或存档即可。",
            )
        ],
    ),
    _p(
        "POL-LOG-001",
        "发货时效与仓库分配",
        "store_policy",
        "物流",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "物流",
        "店铺",
        [
            (
                "现货发货",
                "现货商品在付款后 24 小时内发出；17:00 前付款的订单尽量当日发出，17:00 后付款的订单顺延至次日。"
                "大促、预售和定制订单按商品页标注的时效执行。",
            ),
            (
                "预售与定制",
                "预售商品一般在付款后 7 个自然日内发出；定制商品一般在付款后 15 个自然日内发出。"
                "如遇生产延期，店铺会通过订单留言或短信通知买家。",
            ),
            (
                "仓库分配",
                "店铺在深圳、武汉、天津设有仓库，系统按收货地址就近分配。"
                "多件订单可能拆分为多个包裹发出，拆包不影响运费和售后权益。"
                "如需指定发货仓，可联系客服确认库存和可行性。",
            ),
        ],
    ),
    _p(
        "POL-LOG-002",
        "配送范围与时效标准",
        "store_policy",
        "物流",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "物流",
        "店铺",
        [
            (
                "配送范围",
                "店铺支持中国大陆大部分地区配送，港澳台及海外暂不支持。"
                "部分偏远地区、乡镇和山区可能需要转运，时效以物流实际揽收为准。"
                "下单前可在结算页输入收货地址，查看是否支持配送及预计时效。",
            ),
            ("时效参考", _md_table(["区域", "预计时效", "承运商", "说明"], LOG_SLA_ROWS)),
            (
                "时效说明",
                "上述时效为付款后至签收的预计自然日，不含大促、节假日和不可抗力导致的延误。"
                "物流信息以承运商系统为准；如超过预计时效 48 小时仍无更新，可联系客服催查。",
            ),
        ],
    ),
    _p(
        "POL-LOG-003",
        "节假日、偏远地区与不可抗力",
        "store_policy",
        "物流",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "物流",
        "店铺",
        [
            (
                "节假日安排",
                "春节、国庆等法定节假日期间，仓库和承运商可能调整作业时间，发货和配送顺延 1–3 天。"
                "具体安排以店铺公告和商品页提示为准。",
            ),
            (
                "偏远地区",
                "新疆、西藏、内蒙古部分区域、青海、宁夏等偏远地区可能使用云链物流转运，"
                "时效 5–7 天，部分区域不支持配送或需补运费。下单前以结算页提示为准。",
            ),
            (
                "不可抗力",
                "暴雨、暴雪、台风、地震、交通管制、疫情等不可抗力可能导致物流延误。"
                "店铺会协助催查和改派，但不对不可抗力造成的延误承担赔偿责任；"
                "包裹丢失或损毁的，按物流异常规则处理。",
            ),
        ],
    ),
    _p(
        "POL-LOG-004",
        "物流异常、丢件与破损处理",
        "store_policy",
        "物流",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "物流",
        "店铺",
        [
            (
                "签收验货",
                "建议买家当面验货，确认外包装无破损、商品无磕碰后再签收。"
                "发现外包装明显破损、变形或潮湿的，可拒收并联系客服。",
            ),
            (
                "异常报备",
                "签收后 48 小时内发现丢件、少件、错发或破损的，请提供开箱视频、实物照片和物流面单。"
                "客服核实后优先补发；无法补发的按商品实付金额退款。",
            ),
            (
                "丢件与理赔",
                "物流显示签收但买家未收到的，先联系承运商核实；确认丢件的，由店铺发起理赔或补发。"
                "高价值订单建议购买保价服务，保价理赔以承运商规则为准。理赔期间请保留物流面单和沟通记录。",
            ),
        ],
    ),
    _p(
        "POL-LOG-005",
        "自提、加急与指定快递",
        "store_policy",
        "物流",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "物流",
        "店铺",
        [
            (
                "门店自提",
                "深圳体验店支持自提，下单时选择“门店自提”，到货后凭订单号和手机号取货。"
                "自提订单不支持无理由退货的运费险理赔。",
            ),
            (
                "加急配送",
                "部分区域支持迅风加急，需在结算页选择并支付加急费用。"
                "加急服务不承诺具体送达时间，遇航班、天气或交通管制可能顺延。",
            ),
            (
                "指定快递",
                "默认由系统分配承运商，不支持无条件指定。"
                "确有特殊需求的，可联系客服协商，产生的差价由买家承担。"
                "未经协商自行指定快递导致的拒收或延误，由买家承担相应后果。",
            ),
        ],
    ),
    _p(
        "POL-LOG-006",
        "物流常见问题",
        "policy_faq",
        "物流",
        "STORE",
        STORE_SOURCE,
        "中",
        "v1",
        EFFECTIVE_DATE,
        "物流",
        "店铺",
        [
            (
                "常见问题",
                "**Q：多久发货？**\n"
                "A：现货一般 24 小时内发出，预售 7 天内，定制 15 天内；大促期间可能顺延 1–3 天。\n\n"
                "**Q：为什么物流一直不更新？**\n"
                "A：可能是承运商揽收延迟或中转滞留；超过预计时效 48 小时仍无更新，可联系客服催查。\n\n"
                "**Q：可以修改收货地址吗？**\n"
                "A：未发货前可联系客服尝试修改；已发货的订单需联系承运商改派，可能产生费用或无法改派。\n\n"
                "**Q：丢件或破损怎么办？**\n"
                "A：签收后 48 小时内提供开箱视频、照片和物流面单，客服核实后补发或退款。\n\n"
                "**Q：节假日发货吗？**\n"
                "A：法定节假日仓库和承运商可能调整作业时间，发货和配送顺延 1–3 天。\n\n"
                "**Q：支持指定快递吗？**\n"
                "A：默认系统分配，不支持无条件指定；特殊需求可联系客服协商，差价由买家承担。",
            )
        ],
    ),
    _p(
        "POL-PRI-001",
        "价格保护规则总则（2026 版）",
        "store_policy",
        "价格",
        "STORE",
        STORE_SOURCE,
        "高",
        "v2",
        EFFECTIVE_DATE,
        "价格保护",
        "店铺",
        [
            (
                "价保期限",
                "普通用户自签收次日起 7 个自然日内，星潮会员自签收次日起 15 个自然日内，"
                "同一商品同一规格在店铺页面出现直接降价的，可申请价格保护。"
                "本政策自 2026-01-01 起生效，替代 2024 版价保规则。",
            ),
            ("价保期限对照", _md_table(["用户类型", "价保天数", "适用商品", "说明"], PRI_WINDOW_ROWS)),
            (
                "补差规则",
                "补差金额按原订单实付金额与新订单实付金额的差额计算，不含运费、保价费和加急费。"
                "优惠券、平台补贴、赠品和以旧换新补贴按订单规则计入实付金额，不重复计算。",
            ),
            (
                "申请与到账",
                "买家在订单详情页提交价保申请，提供降价截图或商品链接。"
                "审核一般在 1–3 个工作日内完成，补差按原支付路径退回，或退回星潮余额。",
            ),
        ],
        supersedes="POL-PRI-002",
    ),
    _p(
        "POL-PRI-002",
        "价格保护规则（2024 版，已失效）",
        "store_policy",
        "价格",
        "STORE",
        STORE_SOURCE,
        "中",
        "v1",
        "2024-01-01",
        "价格保护",
        "店铺",
        [
            (
                "历史版本说明",
                "本文档为 2024 版价格保护规则，规定签收后 15 天内可申请价保。"
                "该版本已于 2025-12-31 失效，仅供查询历史订单，不得作为当前规则使用。",
            ),
            (
                "旧版规则",
                "签收次日起 15 个自然日内，同一商品同一规格出现降价的，可申请补差。"
                "秒杀、限时特价、优惠券和赠品不参与价保。补差按原支付路径退回。",
            ),
            (
                "替代关系",
                "2026-01-01 起由 POL-PRI-001《价格保护规则总则（2026 版）》替代。"
                "新旧版本冲突时，以订单下单时生效的版本为准。",
            ),
        ],
        deprecated="true",
        valid_until="2025-12-31",
        review_date="",
        superseded_by="POL-PRI-001",
    ),
    _p(
        "POL-PRI-003",
        "价保适用范围与例外",
        "store_policy",
        "价格",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "价格保护",
        "店铺",
        [
            (
                "适用情形",
                "同一商品、同一规格、同一店铺在价保期内出现商品页面直接降价的，可申请价保。"
                "商品页面标注的“到手价”下降，且下降原因属于店铺直降的，也在适用范围内。",
            ),
            (
                "不适用情形",
                "秒杀、限时特价、清仓、瑕疵品、会员专享价、平台券、店铺券、赠品、跨店满减、"
                "以旧换新补贴、银行立减和支付优惠导致的价格变化，不参与价保。"
                "商品下架、无货或更换链接的，不视为降价。",
            ),
            (
                "举证要求",
                "申请价保需提供订单号、商品链接和降价截图；截图需包含商品型号、规格、价格和页面时间。"
                "无法提供有效凭证的，店铺有权驳回申请。伪造截图或篡改页面时间的，平台有权驳回并限制账号。",
            ),
        ],
    ),
    _p(
        "POL-PRI-004",
        "价保申请流程与补差计算",
        "store_policy",
        "价格",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "价格保护",
        "店铺",
        [
            (
                "申请流程",
                "在订单详情页选择“价格保护”，填写降价金额和凭证，提交后等待审核。"
                "审核一般在 1–3 个工作日内完成；需要补充材料的，审核时间顺延。",
            ),
            (
                "补差计算",
                "补差金额 = 原订单实付金额 - 新订单实付金额。实付金额不含运费、保价费和加急费。"
                "使用优惠券、平台补贴或赠品的订单，按分摊后的实付金额计算，不重复补差。",
            ),
            (
                "到账方式",
                "补差优先按原支付路径退回；原路径不可用的，退回星潮余额。"
                "补差到账时间与退款一致：微信/支付宝 1–3 个工作日，银行卡 3–15 个工作日。"
                "补差金额以审核结果为准，同一订单不支持重复申请。",
            ),
        ],
    ),
    _p(
        "POL-PRI-005",
        "价保常见问题",
        "policy_faq",
        "价格",
        "STORE",
        STORE_SOURCE,
        "中",
        "v1",
        EFFECTIVE_DATE,
        "价格保护",
        "店铺",
        [
            (
                "常见问题",
                "**Q：价保几天？**\n"
                "A：普通用户签收后 7 天，星潮会员 15 天；以订单签收次日起算。\n\n"
                "**Q：用了优惠券还能价保吗？**\n"
                "A：按实付金额计算，优惠券金额会分摊到商品实付价中；平台券和店铺券导致的降价不单独补差。\n\n"
                "**Q：秒杀降价能价保吗？**\n"
                "A：不能。秒杀、限时特价、清仓和会员专享价不参与价保。\n\n"
                "**Q：补差退到哪里？**\n"
                "A：优先原支付路径，原路径不可用时退回星潮余额。\n\n"
                "**Q：价保有次数限制吗？**\n"
                "A：同一订单同一商品一般只支持一次价保；重复申请需提供新的降价凭证。\n\n"
                "**Q：商品下架后还能价保吗？**\n"
                "A：商品下架、无货或更换链接不视为降价，无法申请价保。",
            )
        ],
    ),
    _p(
        "POL-TRD-001",
        "以旧换新总则与回收范围",
        "store_policy",
        "服务",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "以旧换新",
        "店铺",
        [
            (
                "服务范围",
                "以旧换新支持键盘、鼠标和耳机回收，不限品牌。旧机需功能基本正常或可修复；"
                "新机需在烬狐官方旗舰店购买。旧机抵扣和补贴仅用于本次换新订单。",
            ),
            (
                "回收限制",
                "严重进液、电池鼓包、外壳破裂存在安全隐患、缺少核心配件且无法修复的旧机，"
                "可能被拒收或按 D 级估价。仿品、赃物和来源不明的商品不予回收。",
            ),
            (
                "新旧机关系",
                "旧机回收完成后，新机按正常订单享受 7 天无理由退货和保修服务。"
                "新机退货时，旧机抵扣和补贴按规则扣回；旧机已完成环保拆解的，不予退回。"
                "旧机抵扣金额以质检后的最终估价为准，页面预估不构成最终承诺。",
            ),
        ],
    ),
    _p(
        "POL-TRD-002",
        "回收估价与成色标准",
        "store_policy",
        "服务",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "以旧换新",
        "店铺",
        [
            (
                "成色分级",
                "旧机按外观、功能和配件完整度分为 A（95 新）、B（85 新）、C（7 成新）、D（故障机）四级。"
                "最终估价以质检结果为准，页面预估仅供参考。成色判定以质检工程师现场检测为准。",
            ),
            ("估价参考", _md_table(["品类", "成色", "估价区间", "说明"], TRD_VALUATION_ROWS)),
            (
                "估价差异",
                "质检结果与页面预估不一致的，店铺在 48 小时内联系买家确认。"
                "买家接受新估价的，按新估价抵扣；不接受的，旧机退回，退回运费由买家承担。"
                "退回旧机的物流时效不计入换新时效。",
            ),
        ],
    ),
    _p(
        "POL-TRD-003",
        "回收流程与数据清除",
        "store_policy",
        "服务",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "以旧换新",
        "店铺",
        [
            (
                "回收流程",
                "买家在活动页提交旧机信息并获得预估价格，选择寄送或上门回收；"
                "质检完成后确认最终价格，抵扣金额直接用于新机订单。"
                "寄送回收一般 3–7 个工作日完成质检，上门回收以预约时间为准。",
            ),
            (
                "数据与隐私",
                "键盘和鼠标不存储个人信息；耳机在回收前建议恢复出厂设置并解除账号绑定。"
                "店铺在质检和拆解过程中不读取、不保存任何个人数据。",
            ),
            (
                "旧机去向",
                "可修复旧机经检测后进入二手流通或官方翻新；不可修复旧机交由合规拆解机构处理。"
                "旧机一经确认回收，不支持退回。拆解过程符合环保要求，不向买家返还零部件。买家在确认回收前可随时取消。",
            ),
        ],
    ),
    _p(
        "POL-TRD-004",
        "换新补贴与优惠叠加",
        "store_policy",
        "服务",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "以旧换新",
        "店铺",
        [
            (
                "补贴标准",
                "旧机抵扣金额按质检估价计算；额外补贴按新机实付金额分档："
                "满 300 元补贴 50 元，满 800 元补贴 100 元，满 1500 元补贴 200 元。"
                "补贴金额不超过新机实付金额的 20%。",
            ),
            (
                "叠加规则",
                "旧机抵扣和换新补贴可与店铺优惠券叠加，不与平台券、秒杀价、限时特价和其他补贴叠加。"
                "具体以活动页规则为准。",
            ),
            (
                "退货扣回",
                "新机发生退货时，旧机抵扣和补贴从退款金额中扣回；"
                "旧机已拆解的，按旧机估价扣除；补贴已使用的，按活动规则追回。"
                "补贴追回顺序优先从退款金额中扣除，不足部分由买家补足。",
            ),
        ],
    ),
    _p(
        "POL-TRD-005",
        "以旧换新常见问题",
        "policy_faq",
        "服务",
        "STORE",
        STORE_SOURCE,
        "中",
        "v1",
        EFFECTIVE_DATE,
        "以旧换新",
        "店铺",
        [
            (
                "常见问题",
                "**Q：旧机不是烬狐的能换吗？**\n"
                "A：可以。键盘、鼠标和耳机不限品牌，但需功能基本正常或可修复。\n\n"
                "**Q：旧机坏了还能换吗？**\n"
                "A：可以申请，按 D 级或故障机估价；严重进液、电池鼓包等安全隐患机型可能拒收。\n\n"
                "**Q：估价和实际不一致怎么办？**\n"
                "A：质检后 48 小时内联系买家确认；接受新估价按新价格抵扣，不接受可退回旧机。\n\n"
                "**Q：旧机寄回运费谁出？**\n"
                "A：活动页标注包邮的由店铺承担；未标注的由买家承担，退回旧机的运费一般由买家承担。\n\n"
                "**Q：新机退货旧机能退吗？**\n"
                "A：旧机一经确认回收并拆解，不支持退回；抵扣和补贴会从新机退款中扣回。\n\n"
                "**Q：补贴能和优惠券叠加吗？**\n"
                "A：可与店铺优惠券叠加，不与平台券、秒杀价和其他补贴叠加。\n\n"
                "**Q：多久完成换新？**\n"
                "A：寄送回收一般 3–7 个工作日完成质检，确认后新机按正常发货时效发出。",
            )
        ],
    ),
    _p(
        "POL-BND-001",
        "不能查询他人订单与隐私边界",
        "refusal_boundary",
        "安全",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "安全边界",
        "店铺",
        [
            (
                "查询边界",
                "客服只能查询当前登录账号名下的订单，不得查询、透露或修改他人订单、收货地址、手机号、"
                "支付信息和物流信息。即使对方提供订单号，也不能绕过身份验证。",
            ),
            (
                "身份验证",
                "涉及订单修改、退款、发票和售后时，需验证订单号、收货人手机号后四位或平台要求的其他信息。"
                "验证不通过的，转人工处理，不得凭猜测继续操作。",
            ),
            (
                "禁止索要的信息",
                "客服不会索要身份证号、银行卡号、支付密码、短信验证码或账号密码。"
                "遇到此类要求，应提醒用户警惕诈骗并转人工。如用户主动提供，应提醒其撤回，且不得记录在会话或工单中。",
            ),
        ],
    ),
    _p(
        "POL-BND-002",
        "不能承诺赔付金额与超政策补偿",
        "refusal_boundary",
        "安全",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "安全边界",
        "店铺",
        [
            (
                "赔付边界",
                "客服只能按店铺政策和平台规则说明赔付范围、时限和流程，不得承诺具体赔付金额、"
                "到账时间或平台判责结果。超出政策的补偿需转人工审批。",
            ),
            (
                "超政策场景",
                "涉及精神损失、误工费、间接损失、惩罚性赔偿、媒体曝光补偿等超政策诉求，"
                "不得自行承诺，应记录诉求并转人工处理。",
            ),
            (
                "表述要求",
                "可以使用“按政策可申请”“以审核结果为准”“预计 1–3 个工作日”等表述，"
                "不得使用“肯定赔”“马上到账”“一定满足”等承诺性表述。所有赔付和补偿以平台及店铺审核结果为准。",
            ),
        ],
    ),
    _p(
        "POL-BND-003",
        "敏感信息索要与禁售品边界",
        "refusal_boundary",
        "安全",
        "STORE",
        STORE_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "安全边界",
        "店铺",
        [
            (
                "敏感信息",
                "不得索要或记录身份证号、银行卡号、支付密码、短信验证码、账号密码、"
                "人脸照片等敏感信息；如业务确需核验，应引导用户通过平台官方页面操作。",
            ),
            (
                "禁售与敏感商品",
                "店铺不销售或咨询禁售品、管制器具、侵权仿品和规避平台规则的商品。"
                "遇到相关咨询，应说明无法提供并转人工或合规处理。",
            ),
            (
                "越权请求",
                "不得应要求提供绕过平台风控、刷单、虚假评价、恶意退款、批量注册等违规操作建议。"
                "此类请求应拒绝并转人工。发现批量或组织化违规请求时，记录特征并同步合规处理。",
            ),
        ],
    ),
    _p(
        "POL-PLT-001",
        "星潮商城售后争议处理规则",
        "platform_rule",
        "平台",
        "PLATFORM",
        PLATFORM_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "平台规则",
        "平台",
        [
            (
                "适用范围",
                f"本规则适用于{PLATFORM}平台内所有店铺的售后争议处理。"
                "店铺政策不得低于平台规则底线；店铺政策与平台规则冲突时，"
                "以更有利于消费者且不违反法律法规的规定为准。",
            ),
            (
                "处理流程",
                "买家与店铺协商不成时，可申请平台介入。平台按“协商优先、举证判责、限时处理”的原则处理，"
                "一般 3–5 个工作日内给出处理意见。复杂争议可延长 3 个工作日。",
            ),
            (
                "判责依据",
                "平台根据订单信息、聊天记录、物流记录、开箱视频、检测报告和双方举证综合判责。"
                "恶意索赔、虚假举证或伪造凭证的，平台有权驳回申请并限制相关账号。",
            ),
        ],
    ),
    _p(
        "POL-PLT-002",
        "平台介入与举证期限",
        "platform_rule",
        "平台",
        "PLATFORM",
        PLATFORM_SOURCE,
        "高",
        "v1",
        EFFECTIVE_DATE,
        "平台规则",
        "平台",
        [
            (
                "申请条件",
                "买家已与店铺协商且未达成一致，或店铺超时未处理的，可申请平台介入。"
                "申请时需选择争议类型并提交订单号、诉求和初步证据。",
            ),
            (
                "举证期限",
                "平台受理后，买卖双方需在 48 小时内提交证据。证据包括聊天记录、商品照片/视频、"
                "物流面单、检测报告、发票和支付凭证。逾期未举证的，平台可依据现有材料判责。",
            ),
            (
                "处理时限",
                "平台一般在 3–5 个工作日内给出处理意见；需要第三方检测或物流核实的，可延长 3 个工作日。"
                "处理结果通过站内信和短信通知双方。双方可在结果出来后 48 小时内申请复核。",
            ),
        ],
    ),
    _p(
        "POL-PLT-003",
        "平台规则变更公告（2026 年 6 月）",
        "policy_notice",
        "平台",
        "PLATFORM",
        PLATFORM_SOURCE,
        "高",
        "v3",
        "2026-06-01",
        "平台规则",
        "平台",
        [
            (
                "公告内容",
                f"{PLATFORM}将于 2026-06-01 起调整售后争议、价保凭证和以旧换新补贴规则。"
                "本次变更适用于 2026-06-01 及以后下单的订单，历史订单按原规则处理。",
            ),
            (
                "主要变化",
                "价保申请需提供带页面时间的降价截图；发票申请时限由 30 天调整为 45 天；"
                "以旧换新补贴上限调整为新品实付金额的 20%；平台介入举证期限统一为 48 小时。",
            ),
            (
                "生效与解释",
                "本公告自 2026-06-01 起生效，有效期至 2026-12-31。"
                "如与店铺政策冲突，以本公告和平台规则为准；未尽事宜按平台现行规则处理。",
            ),
        ],
        valid_until="2026-12-31",
        review_date="2026-11-01",
    ),
]


def _clear_generated_raw() -> None:
    for subdir in ("images", "tables", "pdf", "scans", "docx", "html"):
        directory = RAW_DIR / subdir
        if directory.exists():
            for path in directory.iterdir():
                if path.is_file():
                    path.unlink()


def _write_csv(path: Path, headers: list[str], rows: list[tuple]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def _write_xlsx(path: Path, title: str, headers: list[str], rows: list[tuple]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title[:31]
    sheet.append(headers)
    for row in rows:
        sheet.append(list(row))
    header_fill = PatternFill("solid", fgColor="1F4E78")
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for column in sheet.columns:
        max_length = max(len(str(cell.value or "")) for cell in column)
        sheet.column_dimensions[column[0].column_letter].width = min(
            max(max_length + 4, 12), 40
        )
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="center", wrap_text=True)
    workbook.save(path)


def _write_html_table(
    path: Path, title: str, headers: list[str], rows: list[tuple]
) -> None:
    head = "".join(f"<th>{value}</th>" for value in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{value}</td>" for value in row) + "</tr>"
        for row in rows
    )
    path.write_text(
        f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font-family: "Microsoft YaHei", sans-serif; margin: 40px; color: #1f2937; }}
h1 {{ font-size: 24px; }}
table {{ border-collapse: collapse; width: 100%; max-width: 900px; }}
th, td {{ border: 1px solid #d1d5db; padding: 10px 12px; text-align: left; }}
th {{ background: #1f4e78; color: #fff; }}
tr:nth-child(even) {{ background: #f3f4f6; }}
</style>
</head>
<body>
<h1>{title}</h1>
<table>
<thead><tr>{head}</tr></thead>
<tbody>{body}</tbody>
</table>
</body>
</html>
""",
        encoding="utf-8",
    )


def _font(size: int):
    from PIL import ImageFont

    candidates = [
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\simsun.ttc"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def _wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        current += char
        if len(current) >= width:
            lines.append(current)
            current = ""
    if current:
        lines.append(current)
    return lines


def _write_infographic(
    path: Path, title: str, subtitle: str, bullets: list[str]
) -> None:
    from PIL import Image, ImageDraw

    width, height = 1200, 800
    image = Image.new("RGB", (width, height), "#f8fafc")
    draw = ImageDraw.Draw(image)
    title_font = _font(44)
    subtitle_font = _font(24)
    body_font = _font(26)
    draw.rectangle([0, 0, width, 150], fill="#1f4e78")
    draw.text((60, 40), title, font=title_font, fill="#ffffff")
    draw.text((60, 100), subtitle, font=subtitle_font, fill="#cbd5e1")
    y = 200
    for index, bullet in enumerate(bullets, 1):
        draw.rounded_rectangle(
            [60, y, width - 60, y + 90],
            radius=14,
            fill="#ffffff",
            outline="#cbd5e1",
            width=2,
        )
        draw.ellipse([85, y + 25, 125, y + 65], fill="#1f4e78")
        draw.text((100, y + 31), str(index), font=subtitle_font, fill="#ffffff")
        draw.text((150, y + 28), bullet, font=body_font, fill="#1f2937")
        y += 110
    draw.text(
        (60, height - 50),
        "烬狐 EMBERFOX · 星潮商城 · 模拟政策图示",
        font=subtitle_font,
        fill="#64748b",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _write_pdf(
    path: Path, title: str, meta_lines: list[str], paragraphs: list[str]
) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    width, height = A4
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setTitle(title)
    y = height - 70
    pdf.setFont("STSong-Light", 20)
    pdf.drawString(60, y, title)
    y -= 30
    pdf.setFont("STSong-Light", 11)
    for line in meta_lines:
        pdf.drawString(60, y, line)
        y -= 18
    y -= 10
    pdf.setFont("STSong-Light", 12)
    for paragraph in paragraphs:
        for line in _wrap(paragraph, 42):
            if y < 70:
                pdf.showPage()
                pdf.setFont("STSong-Light", 12)
                y = height - 70
            pdf.drawString(60, y, line)
            y -= 20
        y -= 10
    pdf.save()


def _write_scan(
    jpg_path: Path, pdf_path: Path, title: str, lines: list[str]
) -> None:
    from PIL import Image, ImageDraw

    width, height = 1240, 1754
    image = Image.new("RGB", (width, height), "#fbfaf5")
    draw = ImageDraw.Draw(image)
    title_font = _font(40)
    body_font = _font(24)
    small_font = _font(20)
    draw.rectangle([60, 60, width - 60, height - 60], outline="#9ca3af", width=3)
    draw.text((110, 120), title, font=title_font, fill="#111827")
    draw.line([110, 190, width - 110, 190], fill="#9ca3af", width=2)
    y = 250
    for line in lines:
        draw.text((110, y), line, font=body_font, fill="#1f2937")
        y += 60
    draw.text((110, height - 220), "经办人：__________", font=body_font, fill="#1f2937")
    draw.text((110, height - 160), "日期：2026-06-01", font=body_font, fill="#1f2937")
    draw.ellipse(
        [width - 360, height - 360, width - 120, height - 120],
        outline="#b91c1c",
        width=5,
    )
    draw.text(
        (width - 335, height - 260),
        "烬狐售后",
        font=small_font,
        fill="#b91c1c",
    )
    draw.text(
        (width - 335, height - 230),
        "专用章（模拟）",
        font=small_font,
        fill="#b91c1c",
    )
    image = image.rotate(1.2, expand=True, fillcolor="#fbfaf5")
    jpg_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(jpg_path, quality=86)
    image.save(pdf_path, "PDF", resolution=150)


def _write_docx(
    path: Path, title: str, paragraphs: list[str], table: tuple[list[str], list[tuple]] | None = None
) -> None:
    from docx import Document

    document = Document()
    document.add_heading(title, level=1)
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    if table is not None:
        headers, rows = table
        doc_table = document.add_table(rows=1, cols=len(headers))
        doc_table.style = "Table Grid"
        for index, header in enumerate(headers):
            doc_table.rows[0].cells[index].text = header
        for row in rows:
            cells = doc_table.add_row().cells
            for index, value in enumerate(row):
                cells[index].text = str(value)
    document.save(path)


def _generate_markdown() -> list[Path]:
    if DOCS_DIR.exists():
        for path in DOCS_DIR.glob("*.md"):
            path.unlink()
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for policy in POLICIES:
        path = DOCS_DIR / f"{policy['doc_id']}.md"
        path.write_text(_render(policy), encoding="utf-8")
        paths.append(path)
    return paths


def _generate_raw() -> list[dict[str, Any]]:
    _clear_generated_raw()
    records: list[dict[str, Any]] = []

    images_dir = RAW_DIR / "images"
    tables_dir = RAW_DIR / "tables"
    pdf_dir = RAW_DIR / "pdf"
    scans_dir = RAW_DIR / "scans"
    docx_dir = RAW_DIR / "docx"
    html_dir = RAW_DIR / "html"
    for directory in (
        images_dir,
        tables_dir,
        pdf_dir,
        scans_dir,
        docx_dir,
        html_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    images = [
        (
            "RET-return-flow.png",
            "退换货流程",
            "七天无理由 / 十五天质量问题",
            [
                "提交申请：订单详情页选择退货或换货",
                "店铺初审：24 小时内完成审核",
                "寄回商品：按页面地址寄回并填写单号",
                "质检确认：3–7 个工作日完成检测",
                "退款/换货：原路退款或安排换新",
            ],
            "退换货",
        ),
        (
            "INV-invoice-types.png",
            "发票类型对比",
            "电子普票 / 增值税专票",
            [
                "电子普通发票：个人和企业均可申请",
                "增值税专用发票：仅限一般纳税人企业",
                "电子普票：1–3 个工作日开具",
                "专票：3–7 个工作日开具并邮寄",
                "退货换开：先红冲再重新开具",
            ],
            "发票",
        ),
        (
            "LOG-delivery-map.png",
            "配送时效参考",
            "中国大陆区域时效",
            [
                "珠三角：1 天，深圳仓发货",
                "长三角/京津冀：2 天",
                "华中/华南：2–3 天",
                "西南/西北：3–5 天",
                "偏远地区：5–7 天，港澳台/海外暂不支持",
            ],
            "物流",
        ),
        (
            "PRI-price-protection.png",
            "价格保护规则",
            "7 天 / 会员 15 天",
            [
                "普通用户：签收后 7 天内可申请",
                "星潮会员：签收后 15 天内可申请",
                "补差 = 原实付 - 新实付，不含运费",
                "秒杀、优惠券、赠品不参与价保",
                "审核 1–3 个工作日，原路退回",
            ],
            "价格保护",
        ),
        (
            "TRD-trade-in-flow.png",
            "以旧换新流程",
            "估价 / 质检 / 抵扣",
            [
                "提交旧机信息，获取预估价格",
                "选择寄送或上门回收",
                "质检确认成色和最终价格",
                "确认抵扣，旧机进入拆解或翻新",
                "新机按正常时效发货",
            ],
            "以旧换新",
        ),
    ]
    for filename, title, subtitle, bullets, domain in images:
        path = images_dir / filename
        _write_infographic(path, title, subtitle, bullets)
        records.append(
            {
                "file_id": f"RAW-IMG-{filename.split('-')[0]}",
                "file_name": str(path.relative_to(RAW_DIR.parent)),
                "domain": domain,
                "format": "PNG",
                "kind": "流程图/信息图",
                "ingest_mode": "待解析",
                "status": "未入库",
                "tool": "图片 OCR / 多模态模型",
                "note": "含中文图示，需 OCR 或多模态解析后入库",
            }
        )

    tables = [
        (
            "RET-return-shipping",
            "退货运费标准",
            ["商品类别", "无理由退货运费", "质量问题退货运费", "说明"],
            RET_SHIPPING_ROWS,
            "退换货",
        ),
        (
            "LOG-delivery-sla",
            "配送时效标准",
            ["区域", "预计时效", "承运商", "说明"],
            LOG_SLA_ROWS,
            "物流",
        ),
        (
            "PRI-price-protection-window",
            "价保期限表",
            ["用户类型", "价保天数", "适用商品", "说明"],
            PRI_WINDOW_ROWS,
            "价格保护",
        ),
        (
            "TRD-trade-in-valuation",
            "以旧换新估价表",
            ["品类", "成色", "估价区间", "说明"],
            TRD_VALUATION_ROWS,
            "以旧换新",
        ),
        (
            "INV-invoice-types",
            "发票类型对比表",
            ["发票类型", "适用对象", "税率", "开具时限", "说明"],
            INV_TYPE_ROWS,
            "发票",
        ),
    ]
    for stem, title, headers, rows, domain in tables:
        csv_path = tables_dir / f"{stem}.csv"
        xlsx_path = tables_dir / f"{stem}.xlsx"
        _write_csv(csv_path, headers, rows)
        _write_xlsx(xlsx_path, title, headers, rows)
        for path, fmt in ((csv_path, "CSV"), (xlsx_path, "XLSX")):
            records.append(
                {
                    "file_id": f"RAW-TBL-{stem}-{fmt}",
                    "file_name": str(path.relative_to(RAW_DIR.parent)),
                    "domain": domain,
                    "format": fmt,
                    "kind": "数据表",
                    "ingest_mode": "待解析",
                    "status": "未入库",
                    "tool": "pandas / openpyxl",
                    "note": "表格解析后按行切片，或转 Markdown 表格入库",
                }
            )

    pdfs = [
        (
            "RET-policy-v2.pdf",
            "退换货政策（2026 版）",
            [
                "适用店铺：烬狐官方旗舰店（星潮商城）",
                "生效日期：2026-01-01；失效日期：2026-12-31",
                "版本：v2；替代：POL-RET-002",
            ],
            [
                "本政策适用于在星潮商城烬狐官方旗舰店购买的键盘、鼠标、耳机及相关配件。定制款、二手商品、赠品和积分兑换商品按单独说明处理。",
                "七天无理由：签收次日起 7 个自然日内，商品完好、配件齐全、不影响二次销售的可申请退货。定制款、已激活商品、拆封的入耳式耳机耳塞和耳罩不支持无理由退货。",
                "十五天质量问题：签收次日起 15 个自然日内，非人为损坏的性能故障可申请免费换货或维修，需提供故障视频、照片和订单信息。",
                "退款时效：质检完成后 24 小时内发起退款；微信/支付宝 1–3 个工作日，银行卡 3–15 个工作日，星潮余额 1 个工作日。",
                "版本说明：2024 版 15 天无理由政策已于 2025-12-31 失效，2026-01-01 起下单的订单适用本政策。",
            ],
            "退换货",
        ),
        (
            "INV-invoice-guide.pdf",
            "发票开具指南",
            [
                "适用店铺：烬狐官方旗舰店（星潮商城）",
                "生效日期：2026-01-01；失效日期：2026-12-31",
                "版本：v1",
            ],
            [
                "店铺支持电子普通发票和增值税专用发票。个人买家默认电子普通发票，企业买家可选择电子普通发票或专票。",
                "订单完成后 30 个自然日内可申请开票；电子普票一般 1–3 个工作日，专票一般 3–7 个工作日。",
                "可开票金额为实付商品金额及可开票运费；优惠券、平台补贴、赠品和积分抵扣按平台规则处理。",
                "发票开具后 60 天内可申请换开；退货或换货需红冲原发票，跨月红冲一般 3–7 个工作日。",
            ],
            "发票",
        ),
        (
            "LOG-service-agreement.pdf",
            "物流服务协议",
            [
                "适用店铺：烬狐官方旗舰店（星潮商城）",
                "生效日期：2026-01-01；失效日期：2026-12-31",
                "版本：v1",
            ],
            [
                "现货商品付款后 24 小时内发出，17:00 前付款尽量当日发出；预售 7 天内，定制 15 天内。",
                "店铺在深圳、武汉、天津设仓，按收货地址就近分配；多件订单可能拆包发出。",
                "中国大陆大部分地区支持配送，港澳台及海外暂不支持；偏远地区可能使用云链物流转运。",
                "签收后 48 小时内发现丢件、少件、错发或破损，提供开箱视频、照片和物流面单，核实后补发或退款。",
                "暴雨、暴雪、台风、交通管制等不可抗力可能造成延误，店铺协助催查但不承担延误赔偿责任。",
            ],
            "物流",
        ),
        (
            "PRI-price-protection.pdf",
            "价格保护规则",
            [
                "适用店铺：烬狐官方旗舰店（星潮商城）",
                "生效日期：2026-01-01；失效日期：2026-12-31",
                "版本：v2；替代：POL-PRI-002",
            ],
            [
                "普通用户签收后 7 天、星潮会员签收后 15 天内，同一商品同一规格出现店铺页面直接降价的，可申请价保。",
                "补差金额按原订单实付金额与新订单实付金额的差额计算，不含运费、保价费和加急费。",
                "秒杀、限时特价、清仓、会员专享价、平台券、店铺券、赠品、跨店满减和以旧换新补贴不参与价保。",
                "申请需提供订单号、商品链接和带页面时间的降价截图；审核 1–3 个工作日，补差原路退回或退回星潮余额。",
            ],
            "价格保护",
        ),
        (
            "TRD-trade-in-agreement.pdf",
            "以旧换新服务协议",
            [
                "适用店铺：烬狐官方旗舰店（星潮商城）",
                "生效日期：2026-01-01；失效日期：2026-12-31",
                "版本：v1",
            ],
            [
                "以旧换新支持键盘、鼠标和耳机回收，不限品牌；旧机需功能基本正常或可修复，新机需在店铺购买。",
                "旧机按 A/B/C/D 四级成色估价，最终价格以质检结果为准；质检差异需在 48 小时内确认。",
                "旧机抵扣和补贴可与店铺优惠券叠加，不与平台券、秒杀价和其他补贴叠加；补贴上限为新机实付金额的 20%。",
                "新机退货时，旧机抵扣和补贴从退款中扣回；旧机一经确认回收并拆解，不支持退回。",
                "耳机回收前建议恢复出厂设置并解除账号绑定；店铺不读取、不保存任何个人数据。",
            ],
            "以旧换新",
        ),
    ]
    for filename, title, meta_lines, paragraphs, domain in pdfs:
        path = pdf_dir / filename
        _write_pdf(path, title, meta_lines, paragraphs)
        records.append(
            {
                "file_id": f"RAW-PDF-{filename.split('-')[0]}",
                "file_name": str(path.relative_to(RAW_DIR.parent)),
                "domain": domain,
                "format": "PDF",
                "kind": "政策全文",
                "ingest_mode": "待解析",
                "status": "未入库",
                "tool": "pypdf / pdfplumber",
                "note": "文本型 PDF，提取文本后按标题切片",
            }
        )

    scans = [
        (
            "TRD-recycle-receipt-scan",
            "以旧换新回收单（扫描件）",
            [
                "回收单号：TRD-20260601-0018",
                "旧机品类：机械键盘",
                "旧机型号：MK75 Pro",
                "成色等级：B（85 新）",
                "预估抵扣：180 元",
                "换新机型：VK75 Pro",
                "备注：功能正常，键帽有轻微使用痕迹",
            ],
            "以旧换新",
        ),
        (
            "PLT-platform-notice-scan",
            "星潮商城规则变更公告（扫描件）",
            [
                "公告编号：PLT-2026-06",
                "生效日期：2026-06-01",
                "一、价保申请需提供带页面时间的降价截图。",
                "二、发票申请时限由 30 天调整为 45 天。",
                "三、以旧换新补贴上限调整为新品实付金额的 20%。",
                "四、平台介入举证期限统一为 48 小时。",
            ],
            "平台规则",
        ),
    ]
    for stem, title, lines, domain in scans:
        jpg_path = scans_dir / f"{stem}.jpg"
        pdf_path = scans_dir / f"{stem}.pdf"
        _write_scan(jpg_path, pdf_path, title, lines)
        for path, fmt in ((jpg_path, "JPG"), (pdf_path, "PDF")):
            records.append(
                {
                    "file_id": f"RAW-SCAN-{stem}-{fmt}",
                    "file_name": str(path.relative_to(RAW_DIR.parent)),
                    "domain": domain,
                    "format": fmt,
                    "kind": "扫描件",
                    "ingest_mode": "待解析",
                    "status": "未入库",
                    "tool": "OCR（PaddleOCR / Tesseract）",
                    "note": "图片型扫描件，无文本层，需 OCR 后入库",
                }
            )

    docx_paths = [
        (
            "RET-policy-v2.docx",
            "退换货政策（2026 版）",
            [
                "本政策适用于在星潮商城烬狐官方旗舰店购买的键盘、鼠标、耳机及相关配件。",
                "七天无理由：签收次日起 7 个自然日内，商品完好、配件齐全、不影响二次销售的可申请退货。",
                "十五天质量问题：签收次日起 15 个自然日内，非人为损坏的性能故障可申请免费换货或维修。",
                "退款时效：质检完成后 24 小时内发起退款，微信/支付宝 1–3 个工作日，银行卡 3–15 个工作日。",
            ],
            (
                ["场景", "时限", "运费", "处理"],
                [
                    ("七天无理由", "签收后 7 天", "买家承担", "退货退款"),
                    ("质量问题", "签收后 15 天", "店铺承担", "换货/维修"),
                    ("保修期内", "按保修条款", "按责任判定", "维修"),
                ],
            ),
            "退换货",
        ),
        (
            "INV-invoice-guide.docx",
            "发票开具指南",
            [
                "店铺支持电子普通发票和增值税专用发票。",
                "订单完成后 30 个自然日内可申请开票；电子普票 1–3 个工作日，专票 3–7 个工作日。",
                "发票开具后 60 天内可申请换开；退货或换货需红冲原发票。",
            ],
            (
                ["发票类型", "适用对象", "税率", "开具时限"],
                [
                    ("电子普通发票", "个人/企业", "13%", "1–3 个工作日"),
                    ("增值税专用发票", "企业一般纳税人", "13%", "3–7 个工作日"),
                ],
            ),
            "发票",
        ),
    ]
    for filename, title, paragraphs, table, domain in docx_paths:
        path = docx_dir / filename
        _write_docx(path, title, paragraphs, table)
        records.append(
            {
                "file_id": f"RAW-DOCX-{filename.split('-')[0]}",
                "file_name": str(path.relative_to(RAW_DIR.parent)),
                "domain": domain,
                "format": "DOCX",
                "kind": "政策文档",
                "ingest_mode": "待解析",
                "status": "未入库",
                "tool": "python-docx",
                "note": "可提取段落和表格后入库",
            }
        )

    html_path = html_dir / "LOG-delivery-sla.html"
    _write_html_table(
        html_path, "星潮商城配送时效标准", ["区域", "预计时效", "承运商", "说明"], LOG_SLA_ROWS
    )
    records.append(
        {
            "file_id": "RAW-HTML-LOG-delivery-sla",
            "file_name": str(html_path.relative_to(RAW_DIR.parent)),
            "domain": "物流",
            "format": "HTML",
            "kind": "网页表格",
            "ingest_mode": "待解析",
            "status": "未入库",
            "tool": "BeautifulSoup / trafilatura",
            "note": "网页型表格，解析正文后入库",
        }
    )

    return records


def _write_registry(raw_records: list[dict[str, Any]]) -> None:
    rows: list[dict[str, Any]] = []
    for policy in POLICIES:
        rows.append(
            {
                "file_id": policy["doc_id"],
                "file_name": f"docs/{policy['doc_id']}.md",
                "domain": policy["policy_domain"],
                "format": "MD",
                "kind": policy["doc_type"],
                "source": policy["source"],
                "authority_level": policy["authority_level"],
                "version": policy["version"],
                "effective_date": policy["effective_date"],
                "valid_until": policy.get("valid_until", ""),
                "deprecated": policy["deprecated"],
                "ingest_mode": "RAG 直接入库",
                "status": "已纳入 RAG",
                "tool": "内置 Markdown 切片",
                "parsed_file": "",
                "parser": "内置 Markdown 切片",
                "duplicate_of": "",
                "note": policy["title"],
            }
        )
    for record in raw_records:
        effective_date = (
            "2026-06-01"
            if "PLT-platform-notice-scan" in record["file_name"]
            else EFFECTIVE_DATE
        )
        rows.append(
            {
                "file_id": record["file_id"],
                "file_name": record["file_name"],
                "domain": record["domain"],
                "format": record["format"],
                "kind": record["kind"],
                "source": STORE_SOURCE if record["domain"] != "平台规则" else PLATFORM_SOURCE,
                "authority_level": "高",
                "version": "v1",
                "effective_date": effective_date,
                "valid_until": VALID_UNTIL,
                "deprecated": "false",
                "ingest_mode": record["ingest_mode"],
                "status": record["status"],
                "tool": record["tool"],
                "parsed_file": "",
                "parser": "",
                "duplicate_of": "",
                "note": record["note"],
            }
        )

    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "file_id",
                "file_name",
                "domain",
                "format",
                "kind",
                "source",
                "authority_level",
                "version",
                "effective_date",
                "valid_until",
                "deprecated",
                "ingest_mode",
                "status",
                "tool",
                "parsed_file",
                "parser",
                "duplicate_of",
                "note",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_readme(raw_records: list[dict[str, Any]]) -> None:
    formats: dict[str, int] = {}
    for record in raw_records:
        formats[record["format"]] = formats.get(record["format"], 0) + 1
    format_lines = "\n".join(
        f"- {fmt}：{count} 个" for fmt, count in sorted(formats.items())
    )
    parse_report_path = (
        ROOT / "data" / "policies" / "parsed" / "parse_report.json"
    )
    parse_totals: dict[str, Any] = {}
    if parse_report_path.exists():
        parse_totals = json.loads(
            parse_report_path.read_text(encoding="utf-8")
        ).get("totals", {})
    selected_manifest = (
        ROOT / "data" / "policies" / "selected" / "manifest.json"
    )
    selected_count = 0
    if selected_manifest.exists():
        selected_count = len(
            json.loads(
                selected_manifest.read_text(encoding="utf-8")
            ).get("documents", [])
        )
    if parse_totals:
        parse_status = (
            f"两批解析：{parse_totals.get('parsed', 0)}/{parse_totals.get('files', 0)} "
            f"个文件已解析，重复 {parse_totals.get('duplicates', 0)} 个，"
            f"待 OCR {parse_totals.get('skipped', 0)} 个，"
            f"失败 {parse_totals.get('errors', 0)} 个；"
            f"其中 {selected_count} 篇已选入库。"
        )
    else:
        parse_status = "尚未运行 `scripts/parse_policy_raw.py`。"
    README.write_text(
        f"""# 店铺政策与平台规则知识库

> 品牌：烬狐 EMBERFOX　平台：{PLATFORM}　版本：v1
> 生成日期：{EFFECTIVE_DATE}

## 目录结构

```
data/policies/
├─ docs/                  # 可直接进入 RAG 的 Markdown 政策文档
├─ raw/
│  ├─ images/             # 流程图、信息图（PNG）
│  ├─ tables/             # 运费、时效、价保、估价、发票表（CSV/XLSX）
│  ├─ pdf/                # 文本型 PDF 政策全文
│  ├─ scans/              # 扫描件（JPG + 图片型 PDF，无文本层）
│  ├─ docx/               # Word 政策文档
│  └─ html/               # 网页表格
├─ parsed/                # 原始文件解析结果（Markdown，待确认）
├─ selected/              # 已确认入库的解析文档（默认参与切片）
├─ registry.csv           # 全部文件清单、有效期、入库状态、所需工具
└─ README.md              # 本文件
```

## 当前状态

- Markdown 政策文档：{len(POLICIES)} 篇，已纳入 RAG 切片。
- 非 Markdown 原始文件：{len(raw_records)} 个，已在 `registry.csv` 标注所需工具。
- {parse_status}
{format_lines}

## 覆盖领域

- 退换货：总则、无理由条件、质量问题、运费、退款、换货、FAQ、旧版政策
- 发票：类型、流程、电子发票、专票、FAQ
- 物流：发货、时效、节假日、异常、自提/加急、FAQ
- 价格保护：总则、例外、补差、FAQ、旧版规则
- 以旧换新：总则、估价、回收流程、补贴、FAQ
- 安全边界：他人订单、赔付承诺、敏感信息
- 平台规则：争议处理、平台介入、规则变更公告

## 待解析文件与建议工具

| 格式 | 建议工具 | 处理方式 |
|---|---|---|
| PDF（文本型） | pdfplumber / pypdf | 提取文本后按标题切片 |
| PDF（扫描件） | qwen-vl-ocr / RapidOCR | OCR 后转 Markdown |
| JPG/PNG | qwen-vl-ocr / RapidOCR / 多模态模型 | OCR 或图片理解后转 Markdown |
| CSV/XLSX | csv / openpyxl / pandas | 按行转 Markdown 表格或结构化入库 |
| DOCX | python-docx | 提取段落和表格 |
| HTML | BeautifulSoup / trafilatura | 提取正文和表格 |

当前实际使用：`qwen-vl-ocr`（DashScope OpenAI 兼容接口），配置项为 `OCR_MODEL`、`OCR_API_KEY`、`OCR_BASE_URL`、`OCR_TIMEOUT`。

## 入库约定

- `docs/` 下的 Markdown 由 `scripts/build_chunks.py` 直接切片。
- `selected/` 下的解析文档由 `scripts/select_policy_parsed.py` 选择，默认参与切片。
- `parsed/` 下的解析结果由 `scripts/parse_policy_raw.py` 生成，确认无重复后再决定是否加入 `selected/`。
- `raw/` 下的文件不自动入库，避免把无文本层扫描件或图片当成空文档。
- 引入解析工具后，把解析结果写入 `parsed/` 或 `docs/`，保留 `doc_id`、`effective_date`、`valid_until`、`deprecated`、`source_file`、`parser` 等元数据，再重新切片。
- 新旧版本冲突时，保留旧版文档并标记 `deprecated: true`，回答时优先使用 `effective_date` 最新且未废弃的版本。
""",
        encoding="utf-8",
    )


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    paths = _generate_markdown()
    raw_records = _generate_raw()
    _write_registry(raw_records)
    _write_readme(raw_records)

    errors: list[str] = []
    warnings: list[str] = []
    for path in paths:
        try:
            document = parse_document(path)
        except DocumentError as exc:
            errors.append(str(exc))
            continue
        warnings.extend(document.warnings)

    print(f"已生成 {len(paths)} 篇政策文档 -> {DOCS_DIR}")
    print(f"已生成 {len(raw_records)} 个原始文件 -> {RAW_DIR}")
    print(f"源清单 -> {REGISTRY}")
    print(f"说明 -> {README}")
    if errors:
        print(f"校验失败 {len(errors)} 篇：")
        for error in errors[:10]:
            print(f"  - {error}")
        return 1
    print(f"校验通过；警告 {len(warnings)} 条")
    for warning in warnings[:10]:
        print(f"  - {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
