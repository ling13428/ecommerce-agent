from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag.clean import DocumentError, parse_document  # noqa: E402

CATALOG_PATH = ROOT / "data" / "products" / "catalog.json"
DOCS_DIR = ROOT / "data" / "products" / "docs"
CATALOG_DIR = ROOT / "data" / "catalog"
REPORT_DIR = ROOT / "reports"

SOURCE = "烬狐官方商品资料（模拟）"
EFFECTIVE_DATE = "2026-10-24"
DOC_TYPES = {
    "overview": "product_overview",
    "specs": "product_spec",
    "faq": "product_faq",
}
DOC_SUFFIX = {
    "overview": "01-overview.md",
    "specs": "02-specs.md",
    "faq": "03-usage-faq.md",
}
DOC_ID_SUFFIX = {"overview": "01", "specs": "02", "faq": "03"}

POSITIONING = {
    "磁轴键盘": "面向 FPS、MOBA 和日常办公的磁轴键盘，核心是可调触发键程、快速重置和低延迟输入。",
    "机械键盘": "面向游戏与办公的机械键盘，强调稳定的按键手感、热插拔可玩性和多设备连接。",
    "矮轴键盘": "主打轻薄便携的矮轴键盘，适合桌面空间有限、经常携带键盘外出的用户。",
    "铝坨坨键盘": "面向客制化玩家的全铝机身键盘，强调质感、结构稳定和可更换轴体的可玩性。",
    "无线游戏鼠标": "面向竞技游戏的无线鼠标，强调低延迟、轻量化和稳定的无线连接。",
    "有线游戏鼠标": "面向预算有限或追求稳定有线连接的游戏鼠标，强调传感器性能和耐用性。",
    "镁合金无线鼠标": "采用镁合金外壳的轻量化无线鼠标，面向追求极致重量和强度的竞技玩家。",
    "入门游戏鼠标": "面向入门玩家的游戏鼠标，强调基础性能、舒适握持和易用性。",
    "头戴式游戏耳机": "面向游戏语音和影音娱乐的头戴式耳机，强调声场、麦克风清晰度和长时间佩戴舒适度。",
    "入耳式游戏耳机": "面向移动和桌面场景的入耳式游戏耳机，强调轻便、隔音和清晰的语音沟通。",
    "头戴式蓝牙耳机": "兼顾通勤、办公和娱乐的蓝牙头戴耳机，强调无线自由、续航和通话降噪。",
}

LAYOUT_DESC = {
    "60%": "去掉独立方向键和数字区，体积极小，适合桌面空间紧张或喜欢极简布局的用户。",
    "65%": "保留方向键和少量编辑键，在体积和实用性之间取得平衡。",
    "68%": "在 65% 基础上增加独立编辑键，适合需要频繁使用 Delete、PageUp 等按键的用户。",
    "75%": "保留方向键、功能键和常用编辑键，比 87 键更省桌面空间。",
    "87键": "保留完整功能区和方向键，没有独立数字区，适合大多数游戏和办公场景。",
    "98键": "保留数字小键盘并压缩编辑区，兼顾输入效率和桌面空间。",
    "104键": "保留完整数字小键盘和功能区，适合财务、表格和需要大量数字输入的场景。",
}

SCENARIOS = {
    "键盘": [
        "FPS 游戏中的急停、连点和快速转向。",
        "MOBA/RTS 游戏的多键位操作。",
        "桌面空间有限的办公或宿舍环境。",
        "需要有线低延迟和无线便携两种模式的用户。",
    ],
    "鼠标": [
        "FPS 游戏中的快速甩枪和精准定位。",
        "长时间办公、学习或游戏使用。",
        "需要多设备切换的笔记本和平板用户。",
        "喜欢轻量化鼠标或特定握姿的玩家。",
    ],
    "耳机": [
        "游戏开黑、语音沟通和听声辨位。",
        "居家看剧、听歌和上网课。",
        "需要长时间佩戴的办公或游戏场景。",
        "在 PC、主机和移动设备之间切换使用。",
    ],
}

CHECKLIST = {
    "键盘": [
        "确认是否需要独立数字小键盘；60%–75% 配列没有数字区。",
        "确认轴体手感偏好，磁轴、机械轴和矮轴的手感差异较大。",
        "确认主要使用有线、2.4G 还是蓝牙连接。",
        "如果主要在 Mac 上使用，建议先确认键位布局和系统兼容性。",
    ],
    "鼠标": [
        "确认手长和握姿，选择对称或右手人体工学外形。",
        "确认重量偏好：轻量化适合快速甩枪，偏重鼠标握持更稳。",
        "确认是否需要无线、蓝牙或只使用有线。",
        "确认是否需要高 DPI、高回报率或可编程按键。",
    ],
    "耳机": [
        "确认佩戴方式：头戴式隔音和声场更好，入耳式更轻便。",
        "确认连接方式：有线、2.4G 或蓝牙。",
        "确认是否需要可拆卸麦克风和虚拟 7.1 环绕声。",
        "确认主要平台是 PC、PS5、Switch 还是手机。",
    ],
}


def _load_products() -> list[dict[str, Any]]:
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    products = payload.get("products")
    if not isinstance(products, list) or len(products) != 100:
        raise ValueError("catalog.json 中应包含 100 个商品")
    return products


def _front_matter(product: dict[str, Any], doc_id: str, title: str, doc_type: str) -> str:
    return (
        "---\n"
        f"doc_id: {doc_id}\n"
        f"product_id: {product['id']}\n"
        f"title: {title}\n"
        f"doc_type: {doc_type}\n"
        f"category: {product['category']}\n"
        f"source: {SOURCE}\n"
        "authority_level: 中\n"
        "version: v1\n"
        f"effective_date: {EFFECTIVE_DATE}\n"
        "deprecated: false\n"
        "---\n"
    )


def _intro(product: dict[str, Any]) -> str:
    p = product["params"]
    if product["category"] == "键盘":
        return (
            f"{product['model']} 采用 {p['layout']} 配列，支持{p['connection']}连接，"
            f"使用{p['switch']}，外壳为{p['case']}。"
        )
    if product["category"] == "鼠标":
        return (
            f"{product['model']} 采用 {p['shape']} 外形，搭载 {p['sensor']} 传感器，"
            f"最高 {p['dpi']} DPI，整机重量 {p['weight']}。"
        )
    return (
        f"{product['model']} 采用 {p['form']} 结构，内置 {p['driver']} 动圈单元，"
        f"支持{p['connection']}连接，整机重量 {p['weight']}。"
    )


def _connection_steps(connection: str) -> str:
    if connection == "三模":
        return "有线模式使用 USB-C 数据线；2.4G 模式插入接收器；蓝牙模式通过配对键进入配对。"
    if connection == "2.4G/有线":
        return "2.4G 模式插入接收器并打开电源；有线模式直接连接 USB-C 数据线。"
    if connection == "2.4G/蓝牙":
        return "2.4G 模式插入接收器；蓝牙模式长按配对键，在系统蓝牙列表中连接。"
    if connection == "2.4G":
        return "将接收器插入 USB 接口，打开设备电源后即可使用。"
    if connection.startswith("蓝牙"):
        return "长按电源或配对键进入配对状态，在系统蓝牙列表中选择设备连接。"
    if connection == "有线":
        return "直接使用 USB 数据线连接设备，无需配对。"
    return f"支持{connection}连接。"


def _weight_desc(weight: str) -> str:
    match = re.search(r"\d+", weight)
    grams = int(match.group()) if match else 0
    if grams and grams <= 55:
        return "属于轻量化鼠标，适合快速甩枪和长时间游戏。"
    if grams and grams <= 75:
        return "重量适中，兼顾稳定性和灵活性。"
    return "偏重设计，握持更稳，适合喜欢扎实手感的用户。"


def _selling_points(product: dict[str, Any]) -> list[tuple[str, str]]:
    p = product["params"]

    if product["category"] == "键盘":
        points: list[tuple[str, str]] = []
        if "磁轴" in p["switch"]:
            points.append(
                (
                    "可调触发",
                    f"触发键程可在 {p['trigger']} 之间调节，按游戏类型设置更短的触发点。",
                )
            )
        else:
            points.append(
                (
                    "轴体手感",
                    f"{p['switch']}，按键反馈清晰，适合长时间游戏和打字。",
                )
            )
        points.append(
            (
                "回报率",
                f"{p['polling']} 回报率，降低输入延迟，适合高刷新率显示器。",
            )
        )
        points.append(
            (
                "连接方式",
                f"支持{p['connection']}，可在台式机、笔记本和平板之间切换。",
            )
        )
        points.append((f"{p['layout']} 配列", LAYOUT_DESC[p["layout"]]))
        points.append(
            (
                "键帽与结构",
                f"{p['keycap']}，{p['case']}，兼顾耐用性和敲击质感。",
            )
        )
        if p["hotswap"] != "不支持":
            points.append(
                ("热插拔", f"{p['hotswap']}，方便更换轴体或做个性化调校。")
            )
        return points[:5]

    if product["category"] == "鼠标":
        return [
            (
                "传感器",
                f"{p['sensor']} 传感器，最高 {p['dpi']} DPI，适合 FPS、MOBA 和日常使用。",
            ),
            ("重量", f"{p['weight']}，{_weight_desc(p['weight'])}"),
            ("回报率", f"{p['polling']} 回报率，降低输入延迟。"),
            ("连接方式", f"支持{p['connection']}，可按场景切换。"),
            (
                "微动与按键",
                f"{p['switch']}，{p['buttons']} 个可编程按键，支持驱动自定义。",
            ),
        ]

    points = [
        (
            "发声单元",
            f"{p['driver']} 动圈单元，声场开阔，适合游戏定位和影音娱乐。",
        ),
        ("连接方式", f"支持{p['connection']}，可按设备和使用场景切换。"),
        ("麦克风", f"{p['mic']}，语音沟通更清晰。"),
    ]
    if "无电池" in p["battery"]:
        points.append(("佩戴与供电", f"{p['weight']}，有线供电，不需要充电。"))
    else:
        points.append(
            (
                "续航",
                f"内置{p['battery']}电池，具体续航受音量、灯效和连接方式影响。",
            )
        )
    if p["surround"] != "无":
        points.append(("环绕声", f"支持{p['surround']}，可通过驱动开启。"))
    else:
        points.append(("佩戴", f"{p['weight']}，耳罩柔软，适合长时间佩戴。"))
    return points[:5]


def _bullets(items: list[tuple[str, str]]) -> str:
    return "\n".join(f"- **{title}**：{desc}" for title, desc in items)


def _numbered(items: list[str]) -> str:
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, 1))


def _overview_body(product: dict[str, Any]) -> str:
    category = product["category"]
    positioning = POSITIONING[product["subcategory"]]
    return f"""
# {product['name']}

## 产品定位

{positioning}{_intro(product)}

## 核心卖点

{_bullets(_selling_points(product))}

## 适合的场景

{_numbered(SCENARIOS[category])}

## 购买前建议确认

{chr(10).join(f"- {item}" for item in CHECKLIST[category])}

## 关于价格与库存

价格、库存、活动和发货时效会实时变化，请以商品页展示或客服工具查询结果为准。本文档只描述产品特性，不记录具体价格和库存。
""".strip()


def _spec_rows(product: dict[str, Any]) -> list[tuple[str, str]]:
    p = product["params"]
    base = [
        ("商品编号", product["id"]),
        ("型号", product["model"]),
        ("类别", product["subcategory"]),
    ]
    if product["category"] == "键盘":
        return base + [
            ("配列", p["layout"]),
            ("连接方式", p["connection"]),
            ("轴体", p["switch"]),
            ("回报率", p["polling"]),
            ("触发调节", p["trigger"]),
            ("键帽", p["keycap"]),
            ("外壳", p["case"]),
            ("电池", p["battery"]),
            ("重量", p["weight"]),
            ("配色", "、".join(p["colors"])),
            ("兼容系统", p["compatibility"]),
            ("包装清单", p["package"]),
        ]
    if product["category"] == "鼠标":
        return base + [
            ("外形", p["shape"]),
            ("连接方式", p["connection"]),
            ("传感器", p["sensor"]),
            ("最高 DPI", f"{p['dpi']} DPI"),
            ("回报率", p["polling"]),
            ("微动", p["switch"]),
            ("按键数", f"{p['buttons']} 个"),
            ("电池", p["battery"]),
            ("重量", p["weight"]),
            ("配色", "、".join(p["colors"])),
            ("兼容系统", p["compatibility"]),
            ("包装清单", p["package"]),
        ]
    return base + [
        ("佩戴方式", p["form"]),
        ("连接方式", p["connection"]),
        ("发声单元", p["driver"]),
        ("麦克风", p["mic"]),
        ("环绕声", p["surround"]),
        ("阻抗", p["impedance"]),
        ("电池", p["battery"]),
        ("重量", p["weight"]),
        ("配色", "、".join(p["colors"])),
        ("兼容系统", p["compatibility"]),
        ("包装清单", p["package"]),
    ]


def _connection_bullets(product: dict[str, Any]) -> str:
    p = product["params"]
    connection = p["connection"]
    tri_mode = connection == "三模"
    lines: list[str] = []
    if tri_mode or "有线" in connection:
        lines.append("- 有线模式使用 USB-C 数据线连接，首次使用建议优先选择有线模式。")
    if tri_mode or "2.4G" in connection:
        lines.append("- 2.4G 模式将接收器插入 USB-A 接口，打开设备电源后即可使用。")
    if tri_mode or "蓝牙" in connection:
        lines.append("- 蓝牙模式通过组合键或配对键进入配对状态，再在系统蓝牙列表中连接。")
        lines.append("- 蓝牙模式下最多记忆三台设备，切换时请先断开当前设备的音频占用。")
    if product["category"] == "键盘":
        lines.append(
            f"- 改键、灯效和触发设置需要安装 {p['software']}，部分功能仅在有线模式下可用。"
        )
    elif product["category"] == "鼠标":
        lines.append(
            f"- DPI、回报率和按键功能需要安装 {p['software']} 调整，配置文件可保存到板载内存。"
        )
    else:
        lines.append(
            f"- 虚拟 7.1、麦克风增益和均衡器需要安装 {p['software']} 调整。"
        )
    lines.append(f"- 兼容系统：{p['compatibility']}。")
    return "\n".join(lines)


def _environment_bullets(product: dict[str, Any]) -> str:
    if product["category"] == "键盘":
        return "\n".join(
            [
                "- 工作温度建议 0℃–40℃，避免长期暴晒、潮湿或液体泼溅。",
                "- 清洁时先断开连接，使用干燥软布擦拭键帽和外壳。",
                "- 避免在键盘上方饮食，碎屑进入轴体可能影响手感。",
            ]
        )
    if product["category"] == "鼠标":
        return "\n".join(
            [
                "- 工作温度建议 0℃–40℃，避免潮湿、灰尘和强烈撞击。",
                "- 建议搭配鼠标垫使用，定期清洁脚贴和传感器开孔。",
                "- 无线鼠标长期不用时，建议每隔三个月补电一次。",
            ]
        )
    return "\n".join(
        [
            "- 工作温度建议 0℃–40℃，避免高温、潮湿和液体泼溅。",
            "- 耳罩和头梁可用干燥软布擦拭，不要使用酒精直接喷洒。",
            "- 长时间高音量使用可能损伤听力，建议控制音量和使用时长。",
        ]
    )


def _caveat(product: dict[str, Any]) -> str:
    if product["category"] == "键盘":
        return "回报率、触发键程和续航为实验室条件下的参考值，实际表现受使用模式、灯效、连接距离和系统环境影响。价格与库存不在本文档维护，需通过商品工具实时查询。"
    if product["category"] == "鼠标":
        return "DPI、回报率和续航为实验室条件下的参考值，实际表现受鼠标垫、连接距离、灯效和使用环境影响。价格与库存不在本文档维护，需通过商品工具实时查询。"
    return "续航、环绕声和麦克风效果受设备接口、驱动版本、音量和环境噪声影响，不同平台和游戏内的音效设置也会影响实际听感。建议购买前确认接口和系统兼容性。价格与库存不在本文档维护，需通过商品工具实时查询。"


def _specs_body(product: dict[str, Any]) -> str:
    rows = _spec_rows(product)
    table = "| 项目 | 说明 |\n|---|---|\n" + "\n".join(
        f"| {key} | {value} |" for key, value in rows
    )
    return f"""
# {product['name']} 规格参数

## 基础参数

{table}

## 连接与兼容

{_connection_bullets(product)}

## 使用环境

{_environment_bullets(product)}

## 参数口径说明

{_caveat(product)}
""".strip()


def _first_use_steps(product: dict[str, Any]) -> list[str]:
    p = product["params"]
    connection = p["connection"]
    if product["category"] == "键盘":
        if "蓝牙" in connection:
            connect_step = "长按组合键进入蓝牙配对，再在系统蓝牙列表中搜索并连接。"
        elif connection == "三模":
            connect_step = "将模式开关拨到有线或 2.4G 档位，连接电脑后等待系统自动识别。"
        else:
            connect_step = "使用 USB-C 数据线连接电脑，等待系统自动识别。"
        return [
            connect_step,
            f"如需改键、调节触发键程或灯效，前往官网下载并安装{p['software']}。",
            "首次使用建议先充满电，并确认键位布局与系统语言一致。",
            "在文本编辑器或游戏里逐个测试按键，确认没有连击或失灵。",
        ]
    if product["category"] == "鼠标":
        if connection == "有线":
            connect_step = "使用 USB 数据线连接电脑，等待系统自动识别。"
        elif "蓝牙" in connection:
            connect_step = "2.4G 模式插入接收器，或长按配对键进入蓝牙配对。"
        else:
            connect_step = "为鼠标充满电，插入 2.4G 接收器并打开电源开关。"
        return [
            connect_step,
            f"安装{p['software']}后调整 DPI、回报率和按键功能。",
            "在鼠标垫上移动几次，确认传感器定位正常。",
            "根据桌面空间和握姿调整 DPI 档位，再进入游戏。",
        ]
    if connection == "蓝牙 5.3":
        connect_step = "长按电源或配对键进入蓝牙配对，在系统蓝牙列表中选择耳机。"
    elif "2.4G" in connection and "蓝牙" in connection:
        connect_step = "插入 2.4G 接收器，或长按配对键进入蓝牙配对。"
    elif "2.4G" in connection:
        connect_step = "将 2.4G 接收器插入 USB 接口，打开耳机电源。"
    else:
        connect_step = "使用 USB-C 数据线连接耳机，等待系统识别。"
    driver_step = f"安装{p['software']}后可调整麦克风增益和均衡器。"
    if p["surround"] != "无":
        driver_step = f"安装{p['software']}后可调整环绕声、麦克风增益和均衡器。"
    return [
        connect_step,
        "在系统声音设置中将耳机设为默认播放和录音设备。",
        driver_step,
        "首次使用建议先以中等音量试听，确认左右声道和麦克风正常。",
    ]


def _maintenance_bullets(product: dict[str, Any]) -> list[str]:
    if product["category"] == "键盘":
        return [
            "定期用干燥软布擦拭键帽和外壳，避免液体从轴体缝隙进入。",
            "可拆卸键帽可用清水冲洗，晾干后再装回，不要使用酒精直接喷洒。",
            "长期不用时建议保持约一半电量，每隔三个月补电一次。",
            "避免在键盘上方饮食，碎屑进入轴体可能影响手感。",
        ]
    if product["category"] == "鼠标":
        return [
            "定期用干燥软布擦拭外壳和按键，避免汗渍长时间附着。",
            "脚贴磨损后及时更换，保持鼠标移动顺滑。",
            "无线鼠标长期不用时建议保持约一半电量，每隔三个月补电一次。",
            "不要自行拆解鼠标，以免影响保修和内部排线。",
        ]
    return [
        "耳罩和头梁可用干燥软布擦拭，避免液体进入发声单元。",
        "不要拉扯耳机线材和麦克风杆，收纳时避免过度弯折。",
        "长期不用时建议保持约一半电量，每隔三个月补电一次。",
        "耳罩老化或破损时联系售后更换同型号配件。",
    ]


def _faq_pairs(product: dict[str, Any]) -> list[tuple[str, str]]:
    p = product["params"]
    if product["category"] == "键盘":
        pairs: list[tuple[str, str]] = [
            (
                f"{product['model']} 支持哪些连接方式？",
                f"支持{p['connection']}。{_connection_steps(p['connection'])}",
            )
        ]
        if "磁轴" in p["switch"]:
            pairs.append(
                (
                    "磁轴和机械轴有什么区别？",
                    "磁轴通过磁场变化触发，支持可调触发键程和快速重置；机械轴手感更直接，结构成熟，按游戏类型和个人习惯选择。",
                )
            )
        else:
            pairs.append(
                (
                    "轴体手感怎么选？",
                    f"{p['switch']}，红轴偏线性、茶轴有轻微段落、青轴段落感更强，建议按游戏和打字习惯选择。",
                )
            )
        if p["hotswap"] == "不支持":
            hotswap_answer = (
                "不支持热插拔，轴体为固定结构；如轴体损坏或手感异常，请联系售后检测。"
            )
        else:
            hotswap_answer = (
                f"{p['hotswap']}，更换轴体前请断开电源，并确认轴体引脚规格。"
            )
        pairs.append(("支持热插拔吗？", hotswap_answer))
        if p["connection"] == "有线":
            pairs.append(
                (
                    "回报率是多少？",
                    f"标称 {p['polling']} 回报率，具体以驱动显示为准。",
                )
            )
        else:
            pairs.append(
                (
                    "回报率是多少？无线模式也能达到吗？",
                    f"标称 {p['polling']} 回报率；无线模式会根据续航和稳定性自动调整，具体以驱动显示为准。",
                )
            )
        pairs.append(
            (
                "支持 Mac 吗？",
                f"兼容 {p['compatibility']}；部分功能键和驱动功能可能因系统版本不同而有差异。",
            )
        )
        pairs.append(
            (
                "键帽打油或磨损怎么办？",
                f"本款使用 {p['keycap']}，日常用干燥软布擦拭；磨损明显时可联系售后购买替换键帽。",
            )
        )
        if "无电池" not in p["battery"]:
            pairs.append(
                (
                    "电池续航多久？",
                    f"内置{p['battery']}电池，续航受灯效、回报率和连接方式影响；建议开启省电模式延长使用时间。",
                )
            )
        if p["connection"] == "有线":
            fault_answer = (
                "先更换数据线或 USB 接口排查连接问题，再在驱动中恢复默认设置；"
                "仍无法解决时联系售后检测。"
            )
        else:
            fault_answer = (
                "先更换数据线或接收器排查连接问题，再在驱动中恢复默认设置；"
                "仍无法解决时联系售后检测。"
            )
        pairs.append(("出现连击或按键失灵怎么办？", fault_answer))
        return pairs[:8]

    if product["category"] == "鼠标":
        if "无电池" in p["battery"]:
            battery_answer = "本款为有线供电，不需要充电；使用时直接连接 USB 接口即可。"
        else:
            battery_answer = (
                f"内置{p['battery']}电池，续航受回报率、灯效和使用频率影响；"
                "建议开启省电模式并关闭不用的灯效。"
            )
        return [
            (
                "怎么连接或配对？",
                f"支持{p['connection']}。{_connection_steps(p['connection'])}",
            ),
            (
                "DPI 怎么调？",
                f"最高{p['dpi']} DPI，可通过驱动或机身按键切换档位；建议根据游戏和桌面空间选择。",
            ),
            (
                "回报率是多少？",
                f"{p['polling']} 回报率，高回报率会增加耗电，长时间办公可适当降低。",
            ),
            ("续航和充电怎么样？", battery_answer),
            (
                "出现双击怎么办？",
                f"本款使用{p['switch']}，出现双击可先在驱动中调整去抖时间；仍无法解决时联系售后检测。",
            ),
            (
                "脚贴可以更换吗？",
                "可以，使用与原厂尺寸匹配的脚贴；更换前清洁底面，避免灰尘影响顺滑度。",
            ),
            (
                "适合什么握姿？",
                f"{p['shape']}，适合抓握、趴握等常见握姿；建议根据手长和握姿选择。",
            ),
            (
                "驱动支持哪些系统？",
                f"支持 {p['compatibility']}，部分高级功能需要安装{p['software']}。",
            ),
        ]

    if p["surround"] == "无":
        surround_answer = "本款不支持虚拟 7.1 环绕声，可通过设备或播放软件自带的音效增强。"
    else:
        surround_answer = (
            f"本款支持{p['surround']}，需要安装{p['software']}并在驱动中开启；"
            "部分主机平台不支持虚拟环绕声。"
        )
    if "无电池" in p["battery"]:
        battery_answer = "本款为有线供电，不需要充电；直接连接 USB 接口即可使用。"
    else:
        battery_answer = (
            f"内置{p['battery']}电池，续航受音量、灯效和连接方式影响；"
            "建议关闭不用的灯效并控制音量。"
        )
    if "内置" in p["mic"]:
        mic_answer = (
            f"本款为{p['mic']}，先在系统输入设备中选中耳机麦克风并确认未静音；"
            "再检查驱动或系统增益。"
        )
    else:
        mic_answer = (
            f"本款为{p['mic']}，先确认麦克风已插紧并在系统输入设备中选中；"
            "再检查驱动中的麦克风增益。"
        )
    if p["connection"] == "蓝牙 5.3":
        noise_answer = (
            "先远离路由器、手机等无线干扰源，重新配对并调整音量；"
            "仍存在时联系售后检测。"
        )
    else:
        noise_answer = "先更换 USB 接口或缩短线材距离，排除供电干扰；仍存在时联系售后检测。"
    return [
        (
            "怎么连接？",
            f"支持{p['connection']}。{_connection_steps(p['connection'])}",
        ),
        ("麦克风没声音怎么办？", mic_answer),
        ("7.1 环绕声怎么开？", surround_answer),
        ("续航多久？", battery_answer),
        (
            "耳罩可以更换吗？",
            "可以，联系售后购买同型号耳罩；拆卸时不要拉扯线材。",
        ),
        (
            "支持 PS5 或 Switch 吗？",
            f"兼容 {p['compatibility']}；部分平台的语音和环绕声功能需要额外设置。",
        ),
        ("有底噪或电流声怎么办？", noise_answer),
        (
            "戴久了夹头怎么办？",
            f"整机重量{p['weight']}，可适当调整头梁长度和耳罩角度；不要强行掰扯头梁。",
        ),
    ]


def _faq_body(product: dict[str, Any]) -> str:
    pairs = _faq_pairs(product)
    qa = "\n\n".join(f"**Q：{question}**\nA：{answer}" for question, answer in pairs)
    return f"""
# {product['name']} 使用、保养与常见问题

## 首次使用

{_numbered(_first_use_steps(product))}

## 日常保养

{chr(10).join(f"- {item}" for item in _maintenance_bullets(product))}

## 常见问题

{qa}
""".strip()


def _write_doc(path: Path, front_matter: str, body: str) -> None:
    path.write_text(f"{front_matter}\n{body}\n", encoding="utf-8")


def _generate_docs(products: list[dict[str, Any]]) -> list[Path]:
    if DOCS_DIR.exists():
        for path in DOCS_DIR.glob("*.md"):
            path.unlink()
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for product in products:
        sections = {
            "overview": (
                f"{product['name']} 产品定位与选购指南",
                _overview_body(product),
            ),
            "specs": (
                f"{product['name']} 规格参数与包装清单",
                _specs_body(product),
            ),
            "faq": (
                f"{product['name']} 使用、保养与常见问题",
                _faq_body(product),
            ),
        }
        for key, (title, body) in sections.items():
            doc_id = f"{product['id']}-{DOC_ID_SUFFIX[key]}"
            filename = f"{product['id']}-{DOC_SUFFIX[key]}"
            path = DOCS_DIR / filename
            front_matter = _front_matter(
                product, doc_id, title, DOC_TYPES[key]
            )
            _write_doc(path, front_matter, body)
            written.append(path)
    return written


def _write_source_registry(products: list[dict[str, Any]]) -> Path:
    path = CATALOG_DIR / "source_registry.csv"
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "doc_id",
                "文件名",
                "领域",
                "格式",
                "来源说明",
                "权威等级",
                "版本",
                "生效日期",
                "是否入库",
                "备注",
            ]
        )
        for product in products:
            for key, suffix in DOC_SUFFIX.items():
                doc_id = f"{product['id']}-{DOC_ID_SUFFIX[key]}"
                writer.writerow(
                    [
                        doc_id,
                        f"{product['id']}-{suffix}",
                        product["category"],
                        "MD",
                        SOURCE,
                        "中",
                        "v1",
                        EFFECTIVE_DATE,
                        "是",
                        DOC_TYPES[key],
                    ]
                )
    return path


def _write_products_csv(products: list[dict[str, Any]]) -> Path:
    path = CATALOG_DIR / "products.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "商品编号",
                "型号",
                "商品名称",
                "分类",
                "子类",
                "价格",
                "库存",
                "状态",
                "活动",
                "发货时效",
                "配色",
                "规格摘要",
            ]
        )
        for product in products:
            writer.writerow(
                [
                    product["id"],
                    product["model"],
                    product["name"],
                    product["category"],
                    product["subcategory"],
                    product["price"],
                    product["stock"],
                    "缺货" if product["stock"] == 0 else "在售",
                    product["activity"],
                    product["shipping"],
                    "、".join(product["colors"]),
                    product["specs"],
                ]
            )
    return path


def _first_doc(product: dict[str, Any]) -> str:
    return f"{product['id']}-01"


def _write_intent_matrix(products: list[dict[str, Any]]) -> Path:
    example = {
        category: _first_doc(next(p for p in products if p["category"] == category))
        for category in ("键盘", "鼠标", "耳机")
    }
    rows = [
        ("键盘", "配列怎么选", "是", example["键盘"], 0),
        ("键盘", "磁轴和机械轴区别", "是", example["键盘"], 0),
        ("键盘", "触发键程怎么调", "是", example["键盘"], 0),
        ("键盘", "支持热插拔吗", "是", example["键盘"], 0),
        ("键盘", "三模怎么切换", "是", example["键盘"], 0),
        ("键盘", "驱动支持哪些系统", "是", example["键盘"], 0),
        ("键盘", "无线回报率", "是", example["键盘"], 0),
        ("键盘", "键帽打油怎么办", "是", example["键盘"], 0),
        ("键盘", "键盘怎么清洁", "是", example["键盘"], 0),
        ("键盘", "是否支持 Mac", "是", example["键盘"], 0),
        ("鼠标", "手型和握姿怎么选", "是", example["鼠标"], 0),
        ("鼠标", "DPI 怎么调", "是", example["鼠标"], 0),
        ("鼠标", "回报率多少", "是", example["鼠标"], 0),
        ("鼠标", "重量多少", "是", example["鼠标"], 0),
        ("鼠标", "怎么配对", "是", example["鼠标"], 0),
        ("鼠标", "续航和充电", "是", example["鼠标"], 0),
        ("鼠标", "双击怎么办", "是", example["鼠标"], 0),
        ("鼠标", "脚贴能换吗", "是", example["鼠标"], 0),
        ("鼠标", "驱动支持哪些系统", "是", example["鼠标"], 0),
        ("耳机", "7.1 环绕声怎么开", "是", example["耳机"], 0),
        ("耳机", "麦克风没声音", "是", example["耳机"], 0),
        ("耳机", "怎么连接", "是", example["耳机"], 0),
        ("耳机", "续航多久", "是", example["耳机"], 0),
        ("耳机", "耳罩能换吗", "是", example["耳机"], 0),
        ("耳机", "支持 PS5 吗", "是", example["耳机"], 0),
        ("耳机", "有底噪怎么办", "是", example["耳机"], 0),
        ("耳机", "戴久了夹头", "是", example["耳机"], 0),
        ("通用", "退换货政策", "是", "POL-RET-001", 0),
        ("通用", "开发票", "是", "POL-INV-001", 0),
        ("通用", "物流时效", "是", "POL-LOG-001", 0),
        ("通用", "价格保护", "是", "POL-PRI-001", 0),
        ("通用", "以旧换新", "是", "POL-TRD-001", 0),
    ]
    path = CATALOG_DIR / "intent_matrix.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["领域", "子意图", "是否有文档", "示例文档", "评测题数量"])
        writer.writerows(rows)
    return path


def _write_datasheet(products: list[dict[str, Any]]) -> Path:
    counts = {
        category: sum(1 for p in products if p["category"] == category)
        for category in ("键盘", "鼠标", "耳机")
    }
    out_of_stock = [p for p in products if p["stock"] == 0]
    path = ROOT / "docs" / "datasheet.md"
    path.write_text(
        f"""# 数据集数据卡：烬狐 EMBERFOX 商品 + 店铺政策知识库 v1

## 基本信息

- 数据集名称：烬狐 EMBERFOX 商品 + 店铺政策知识库
- 版本：v1
- 生成日期：{EFFECTIVE_DATE}
- 商品数量：{len(products)} 个（键盘 {counts['键盘']}、鼠标 {counts['鼠标']}、耳机 {counts['耳机']}）
- 商品文档：{len(products) * 3} 篇（每个商品 3 篇：定位与选购、规格参数、使用与 FAQ）
- 政策文档：35 篇（退换货、发票、物流、价格保护、以旧换新、安全边界、平台规则）
- 原始文件：27 个（PNG/CSV/XLSX/PDF/JPG/DOCX/HTML，已完成两批解析，其中 7 篇已选入库，其余待确认）
- 评测 gold：80 条（70 可回答 / 10 拒答），见 `data/eval/retrieval_gold.jsonl`
- 缺货商品：{len(out_of_stock)} 个
- 数据性质：**全部为模拟构造数据，不代表任何真实品牌、平台或商品**

## 覆盖范围

- 商品：键盘、鼠标、耳机；磁轴、机械轴、矮轴、全铝客制化、无线/有线/镁合金鼠标、头戴/入耳/蓝牙耳机
- 商品文档字段：商品编号、型号、类别、配列/外形/佩戴方式、连接方式、轴体/传感器/发声单元、回报率、续航、重量、配色、包装清单、使用与保养、FAQ
- 政策领域：退换货、发票、物流、价格保护、以旧换新、安全边界、平台规则
- 政策元数据：版本、生效日期、失效日期、复核日期、是否废弃、替代关系、适用区域、作用域
- 原始格式：流程图 PNG、运费/时效/价保/估价/发票表 CSV+XLSX、文本 PDF、扫描件 JPG+图片型 PDF、DOCX、HTML

## 生成方法

- 商品目录由脚本 `scripts/generate_catalog.py` 确定性生成，价格、库存、型号和参数均为手工设定的模拟值。
- 商品文档由脚本 `scripts/generate_product_docs.py` 按商品分类模板生成。
- 政策文档由脚本 `scripts/generate_policy_docs.py` 生成，包含 Markdown 正文、图片、表格、PDF、扫描件、DOCX 和 HTML。
- 价格、库存、活动和发货时效不写入 RAG 文档，由商品工具 `get_product` 实时返回。
- 图片、表格、PDF、扫描件、DOCX、HTML 已用 pdfplumber/openpyxl/python-docx/BeautifulSoup/qwen-vl-ocr 解析；5 个 CSV 表格和 2 个扫描件已选入库，其余待确认。

## 已知局限

- 数据为虚构，不能用于真实商品咨询、法律依据或商业决策。
- 商品参数和政策条款为示例值，未经过真实业务验证。
- 政策 Markdown 为摘要版，PDF/扫描件中的细则可能更完整，尚未解析对齐。
- 缺少真实用户对话和订单数据，评测集需另行构造。

## 合规声明

- 不含个人信息、真实客户数据或未脱敏日志。
- 品牌名、平台名、型号、价格、库存和政策条款均为虚构，如有雷同纯属巧合。
- 仅用于本地技术验证和 RAG 演示。
""",
        encoding="utf-8",
    )
    return path


def _validate_docs(paths: list[Path]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for path in paths:
        try:
            document = parse_document(path)
        except DocumentError as exc:
            errors.append(str(exc))
            continue
        warnings.extend(document.warnings)
    return errors, warnings


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    products = _load_products()
    written = _generate_docs(products)
    registry = _write_source_registry(products)
    products_csv = _write_products_csv(products)
    intent = _write_intent_matrix(products)
    datasheet = _write_datasheet(products)

    errors, warnings = _validate_docs(written)

    print(f"已生成 {len(written)} 篇商品文档 -> {DOCS_DIR}")
    print(f"源清单 -> {registry}")
    print(f"商品表 -> {products_csv}")
    print(f"意图矩阵 -> {intent}")
    print(f"数据卡 -> {datasheet}")
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
