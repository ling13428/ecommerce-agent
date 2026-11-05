from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "data" / "products" / "catalog.json"

BRAND = "烬狐 EMBERFOX"
EFFECTIVE_DATE = "2026-10-24"

KB_WEIGHT = {
    "60%": "约 620g",
    "65%": "约 690g",
    "68%": "约 730g",
    "75%": "约 820g",
    "87键": "约 980g",
    "98键": "约 1120g",
    "104键": "约 1180g",
}

KB_COLORS = {
    "VK": ["银翼", "暗夜", "赤霞"],
    "MK": ["曜石黑", "冰川白", "雾灰"],
    "SL": ["月岩灰", "霜白"],
    "AL": ["阳极银", "深空灰", "赤铜"],
}

MOUSE_COLORS = {
    "VM": ["曜石黑", "冰川白", "赤霞"],
    "GM": ["曜石黑", "冰川白"],
    "TM": ["钛灰", "曜石黑"],
    "EM": ["曜石黑", "冰川白", "雾蓝"],
}

HEADSET_COLORS = {
    "AH": ["曜石黑", "冰川白", "赤霞"],
    "EH": ["曜石黑", "银白"],
    "BH": ["曜石黑", "云雾白", "雾蓝"],
}

KB_SUB = {
    "VK": "磁轴键盘",
    "MK": "机械键盘",
    "SL": "矮轴键盘",
    "AL": "铝坨坨键盘",
}

MOUSE_SUB = {
    "VM": "无线游戏鼠标",
    "GM": "有线游戏鼠标",
    "TM": "镁合金无线鼠标",
    "EM": "入门游戏鼠标",
}

HEADSET_SUB = {
    "AH": "头戴式游戏耳机",
    "EH": "入耳式游戏耳机",
    "BH": "头戴式蓝牙耳机",
}

ACTIVITIES = [
    "满 800 减 80",
    "满 500 减 50",
    "赠品牌鼠标垫",
    "晒单返 20 元券",
    "会员专享 95 折",
    "限时 9 折",
]


def _split_model(model: str) -> tuple[str, str, str]:
    match = re.match(
        r"^([A-Z]{2})(\d{1,3})(?:\s+(Pro|Ultra|SE|Plus|Mini|Wireless))?$", model
    )
    if match is None:
        raise ValueError(f"型号格式不合法：{model}")
    return match.group(1), match.group(2), match.group(3) or ""


def _activity(index: int) -> str:
    return ACTIVITIES[index % len(ACTIVITIES)]


def _shipping(stock: int, price: int) -> str:
    if stock == 0:
        return "补货后 7 天内发货"
    if price >= 1000:
        return "48 小时内发货"
    return "24 小时内发货"


def _keyboard(
    model: str,
    layout: str,
    price: int,
    stock: int,
    connection: str,
    index: int,
) -> dict[str, Any]:
    series, _number, variant = _split_model(model)

    if series == "VK":
        if variant == "Ultra":
            switch = "烬狐磁轴 Ultra"
            polling = "8000Hz"
            trigger = "0.005–3.4mm"
            case = "全铝 CNC 机身"
            hotswap = "支持（磁轴轴座）"
        elif variant == "Pro":
            switch = "烬狐磁轴 Pro"
            polling = "8000Hz"
            trigger = "0.01–3.4mm"
            case = "铝合金上盖 + ABS 底壳"
            hotswap = "支持（磁轴轴座）"
        elif variant == "SE":
            switch = "烬狐磁轴"
            polling = "1000Hz"
            trigger = "0.1–3.4mm"
            case = "ABS 注塑 + 硅胶填充"
            hotswap = "不支持"
        else:
            switch = "烬狐磁轴"
            polling = "1000Hz"
            trigger = "0.01–3.4mm"
            case = "铝合金上盖 + ABS 底壳"
            hotswap = "不支持"
        keycap = "PBT 双色注塑"
        battery = "4000mAh" if connection == "三模" else "无电池（有线供电）"
    elif series == "MK":
        if variant in {"Pro", "Plus"}:
            switch = "烬狐机械轴 Pro（预润）"
            case = "Gasket 结构 + 硅胶填充"
        else:
            switch = "烬狐机械轴（红/茶/青可选）"
            case = "ABS 注塑 + 硅胶填充"
        polling = "1000Hz"
        trigger = "固定触发"
        keycap = "PBT 双色注塑"
        battery = "4000mAh" if connection == "三模" else "无电池（有线供电）"
        hotswap = "支持"
    elif series == "SL":
        switch = "矮轴（红/茶可选）"
        polling = "1000Hz"
        trigger = "固定触发"
        case = "铝合金上盖 + ABS 底壳"
        keycap = "矮球帽 PBT"
        battery = "3000mAh" if connection == "三模" else "无电池（有线供电）"
        hotswap = "不支持"
    elif series == "AL":
        switch = "客制化轴座（兼容三脚/五脚）"
        polling = "1000Hz"
        trigger = "固定触发"
        case = "全铝 CNC 机身"
        keycap = "PBT 双色注塑"
        battery = "5000mAh" if connection == "三模" else "无电池（有线供电）"
        hotswap = "支持"
    else:
        raise ValueError(f"未知键盘系列：{series}")

    weight = KB_WEIGHT[layout]
    if series == "AL":
        weight = "约 1.6kg" if model == "AL65" else "约 2.1kg"

    colors = KB_COLORS[series]
    package = (
        "键盘、USB-C 数据线、2.4G 接收器、拔键器、说明书"
        if connection == "三模"
        else "键盘、USB-C 数据线、拔键器、说明书"
    )
    subcategory = KB_SUB[series]
    name = f"烬狐 {model} {subcategory}"

    return {
        "id": "",
        "brand": BRAND,
        "model": model,
        "name": name,
        "category": "键盘",
        "subcategory": subcategory,
        "price": price,
        "stock": stock,
        "specs": f"{layout} 配列，{switch}，{connection}，{polling} 回报率",
        "activity": _activity(index),
        "shipping": _shipping(stock, price),
        "colors": colors,
        "params": {
            "layout": layout,
            "connection": connection,
            "switch": switch,
            "polling": polling,
            "trigger": trigger,
            "keycap": keycap,
            "case": case,
            "battery": battery,
            "weight": weight,
            "colors": colors,
            "compatibility": "Windows 10/11、macOS 12+、Linux",
            "software": "烬狐 Hub",
            "package": package,
            "hotswap": hotswap,
        },
    }


def _mouse(
    model: str,
    shape: str,
    price: int,
    stock: int,
    connection: str,
    sensor: str,
    dpi: int,
    polling: str,
    weight: str,
    buttons: int,
    battery: str,
    switch: str,
    index: int,
) -> dict[str, Any]:
    series, _number, _variant = _split_model(model)
    subcategory = MOUSE_SUB[series]
    colors = MOUSE_COLORS[series]
    package = (
        "鼠标、USB-C 数据线、2.4G 接收器、说明书"
        if connection == "三模" or "2.4G" in connection
        else "鼠标、USB 数据线、说明书"
    )
    name = f"烬狐 {model} {subcategory}"

    return {
        "id": "",
        "brand": BRAND,
        "model": model,
        "name": name,
        "category": "鼠标",
        "subcategory": subcategory,
        "price": price,
        "stock": stock,
        "specs": f"{shape}，{sensor} {dpi} DPI，{weight}，{connection}",
        "activity": _activity(index),
        "shipping": _shipping(stock, price),
        "colors": colors,
        "params": {
            "shape": shape,
            "connection": connection,
            "sensor": sensor,
            "dpi": dpi,
            "polling": polling,
            "weight": weight,
            "buttons": buttons,
            "battery": battery,
            "switch": switch,
            "colors": colors,
            "compatibility": "Windows 10/11、macOS 12+",
            "software": "烬狐 Hub",
            "package": package,
        },
    }


def _headset(
    model: str,
    form: str,
    price: int,
    stock: int,
    connection: str,
    driver: str,
    mic: str,
    battery: str,
    weight: str,
    surround: str,
    impedance: str,
    index: int,
) -> dict[str, Any]:
    series, _number, _variant = _split_model(model)
    subcategory = HEADSET_SUB[series]
    colors = HEADSET_COLORS[series]
    if connection == "三模" or "2.4G" in connection:
        package = "耳机、USB-C 数据线、2.4G 接收器、可拆卸麦克风、说明书"
    elif connection == "蓝牙 5.3":
        package = "耳机、USB-C 充电线、说明书"
    else:
        package = "耳机、USB-C 数据线、可拆卸麦克风、说明书"
    name = f"烬狐 {model} {subcategory}"

    return {
        "id": "",
        "brand": BRAND,
        "model": model,
        "name": name,
        "category": "耳机",
        "subcategory": subcategory,
        "price": price,
        "stock": stock,
        "specs": f"{form}，{driver} 动圈单元，{connection}，{mic}",
        "activity": _activity(index),
        "shipping": _shipping(stock, price),
        "colors": colors,
        "params": {
            "form": form,
            "connection": connection,
            "driver": driver,
            "mic": mic,
            "battery": battery,
            "weight": weight,
            "surround": surround,
            "impedance": impedance,
            "colors": colors,
            "compatibility": "PC、PS5、Switch、手机（视接口而定）",
            "package": package,
            "software": "烬狐 Hub",
        },
    }


KEYBOARDS = [
    ("VK75 Pro", "75%", 969, 56, "三模"),
    ("VK75", "75%", 699, 71, "有线"),
    ("VK75 Ultra", "75%", 1299, 18, "三模"),
    ("VK75 SE", "75%", 499, 120, "有线"),
    ("VK65", "65%", 649, 52, "有线"),
    ("VK65 Pro", "65%", 899, 38, "三模"),
    ("VK65 Ultra", "65%", 1099, 21, "三模"),
    ("VK68", "68%", 669, 47, "有线"),
    ("VK68 Pro", "68%", 929, 33, "三模"),
    ("VK68 Ultra", "68%", 1199, 0, "三模"),
    ("VK60", "60%", 599, 64, "有线"),
    ("VK87", "87键", 799, 44, "有线"),
    ("VK87 Pro", "87键", 1099, 27, "三模"),
    ("VK87 Ultra", "87键", 1399, 12, "三模"),
    ("VK98", "98键", 999, 36, "三模"),
    ("VK98 Pro", "98键", 1199, 24, "三模"),
    ("VK98 Ultra", "98键", 1499, 0, "三模"),
    ("VK104", "104键", 1099, 19, "三模"),
    ("VK104 Pro", "104键", 1299, 14, "三模"),
    ("MK75 Pro", "75%", 629, 54, "三模"),
    ("MK75", "75%", 469, 88, "三模"),
    ("MK75 Plus", "75%", 699, 30, "三模"),
    ("MK65", "65%", 399, 98, "三模"),
    ("MK65 Pro", "65%", 559, 62, "三模"),
    ("MK68", "68%", 429, 77, "三模"),
    ("MK68 Pro", "68%", 589, 41, "三模"),
    ("MK60", "60%", 299, 150, "有线"),
    ("MK87", "87键", 499, 66, "三模"),
    ("MK87 Pro", "87键", 659, 39, "三模"),
    ("MK98", "98键", 549, 58, "三模"),
    ("MK98 Pro", "98键", 719, 35, "三模"),
    ("MK104", "104键", 599, 43, "三模"),
    ("MK104 Pro", "104键", 769, 26, "三模"),
    ("SL75", "75%", 459, 57, "三模"),
    ("SL75 Pro", "75%", 599, 32, "三模"),
    ("SL87", "87键", 499, 45, "三模"),
    ("SL87 Pro", "87键", 639, 23, "三模"),
    ("SL98", "98键", 549, 0, "三模"),
    ("AL65", "65%", 1299, 9, "有线"),
    ("AL75", "75%", 1599, 7, "三模"),
]

MICE = [
    ("VM9 Pro", "对称", 749, 22, "2.4G/有线", "PAW3950", 32000, "4000Hz", "约 50g", 6, "700mAh", "烬狐光微动"),
    ("VM9", "对称", 549, 38, "三模", "PAW3395", 32000, "1000Hz", "约 55g", 6, "600mAh", "欧姆龙微动"),
    ("VM9 Ultra", "对称", 999, 11, "2.4G/有线", "PAW3950 HS", 36000, "8000Hz", "约 47g", 6, "650mAh", "烬狐光微动"),
    ("VM9 Mini", "小号对称", 599, 29, "三模", "PAW3395", 30000, "1000Hz", "约 44g", 6, "500mAh", "欧姆龙微动"),
    ("VM6", "对称", 329, 95, "三模", "PAW3395", 30000, "1000Hz", "约 63g", 6, "600mAh", "欧姆龙微动"),
    ("VM6 Pro", "对称", 499, 42, "三模", "PAW3950", 32000, "4000Hz", "约 58g", 6, "650mAh", "烬狐光微动"),
    ("VM6 Ultra", "对称", 699, 17, "2.4G/有线", "PAW3950 HS", 32000, "8000Hz", "约 52g", 6, "600mAh", "烬狐光微动"),
    ("VM3", "对称", 199, 210, "三模", "PAW3395", 26000, "1000Hz", "约 58g", 5, "500mAh", "欧姆龙微动"),
    ("VM3 Pro", "对称", 349, 87, "三模", "PAW3395", 30000, "4000Hz", "约 54g", 5, "550mAh", "欧姆龙微动"),
    ("VM3 Mini", "小号对称", 299, 64, "三模", "PAW3395", 26000, "1000Hz", "约 49g", 5, "450mAh", "欧姆龙微动"),
    ("VM5", "右手人体工学", 249, 133, "三模", "PAW3395", 26000, "1000Hz", "约 72g", 6, "600mAh", "欧姆龙微动"),
    ("VM5 Pro", "右手人体工学", 399, 51, "三模", "PAW3395", 30000, "4000Hz", "约 65g", 6, "650mAh", "烬狐光微动"),
    ("VM8", "右手人体工学", 279, 108, "三模", "PAW3395", 26000, "1000Hz", "约 88g", 7, "700mAh", "欧姆龙微动"),
    ("VM8 Pro", "右手人体工学", 429, 46, "三模", "PAW3395", 30000, "4000Hz", "约 78g", 7, "700mAh", "烬狐光微动"),
    ("VM8 Ultra", "右手人体工学", 629, 0, "2.4G/有线", "PAW3950 HS", 32000, "8000Hz", "约 69g", 7, "650mAh", "烬狐光微动"),
    ("VM10", "右手人体工学", 459, 0, "三模", "PAW3395", 30000, "4000Hz", "约 74g", 7, "700mAh", "烬狐光微动"),
    ("GM3", "对称", 99, 260, "有线", "PAW3311", 16000, "1000Hz", "约 68g", 5, "无电池（有线供电）", "欧姆龙微动"),
    ("GM3 Pro", "对称", 159, 140, "有线", "PAW3395", 26000, "1000Hz", "约 61g", 5, "无电池（有线供电）", "欧姆龙微动"),
    ("GM5", "右手人体工学", 119, 175, "有线", "PAW3311", 16000, "1000Hz", "约 82g", 6, "无电池（有线供电）", "欧姆龙微动"),
    ("GM5 Pro", "右手人体工学", 189, 96, "有线", "PAW3395", 26000, "1000Hz", "约 74g", 6, "无电池（有线供电）", "欧姆龙微动"),
    ("GM6", "对称", 149, 120, "有线", "PAW3395", 26000, "1000Hz", "约 66g", 6, "无电池（有线供电）", "欧姆龙微动"),
    ("GM6 Pro", "对称", 229, 74, "有线", "PAW3395", 30000, "1000Hz", "约 59g", 6, "无电池（有线供电）", "烬狐光微动"),
    ("GM8", "右手人体工学", 169, 88, "有线", "PAW3395", 26000, "1000Hz", "约 91g", 7, "无电池（有线供电）", "欧姆龙微动"),
    ("TM6", "对称", 799, 26, "2.4G/有线", "PAW3395", 32000, "4000Hz", "约 49g", 6, "600mAh", "烬狐光微动"),
    ("TM6 Pro", "对称", 1099, 15, "2.4G/有线", "PAW3950 HS", 36000, "8000Hz", "约 45g", 6, "600mAh", "烬狐光微动"),
    ("TM8", "右手人体工学", 899, 20, "2.4G/有线", "PAW3395", 32000, "4000Hz", "约 56g", 7, "650mAh", "烬狐光微动"),
    ("TM8 Pro", "右手人体工学", 1199, 9, "2.4G/有线", "PAW3950 HS", 36000, "8000Hz", "约 51g", 7, "650mAh", "烬狐光微动"),
    ("TM9", "对称", 1299, 0, "2.4G/有线", "PAW3950 HS", 36000, "8000Hz", "约 48g", 6, "600mAh", "烬狐光微动"),
    ("TM9 Pro", "对称", 1599, 6, "2.4G/有线", "PAW3950 HS", 42000, "8000Hz", "约 43g", 6, "600mAh", "烬狐光微动"),
    ("EM2", "对称", 69, 320, "有线", "PAW3104", 12000, "1000Hz", "约 76g", 5, "无电池（有线供电）", "欧姆龙微动"),
    ("EM3", "对称", 89, 210, "有线", "PAW3311", 16000, "1000Hz", "约 72g", 6, "无电池（有线供电）", "欧姆龙微动"),
    ("EM4", "右手人体工学", 79, 180, "有线", "PAW3311", 16000, "1000Hz", "约 85g", 6, "无电池（有线供电）", "欧姆龙微动"),
    ("EM5", "对称", 129, 150, "2.4G/蓝牙", "PAW3311", 16000, "1000Hz", "约 84g", 6, "600mAh", "欧姆龙微动"),
    ("EM6", "右手人体工学", 149, 130, "2.4G/蓝牙", "PAW3311", 16000, "1000Hz", "约 92g", 7, "700mAh", "欧姆龙微动"),
    ("EM7", "对称", 179, 0, "2.4G/蓝牙", "PAW3311", 20000, "1000Hz", "约 78g", 6, "600mAh", "欧姆龙微动"),
]

HEADSETS = [
    ("AH9 Pro", "头戴式", 1599, 4, "三模", "53mm", "可拆卸降噪麦克风", "1500mAh", "约 320g", "虚拟 7.1", "32Ω"),
    ("AH9", "头戴式", 1299, 9, "三模", "53mm", "可拆卸降噪麦克风", "1500mAh", "约 330g", "虚拟 7.1", "32Ω"),
    ("AH9 Wireless", "头戴式", 1399, 7, "2.4G", "53mm", "可拆卸降噪麦克风", "1500mAh", "约 325g", "虚拟 7.1", "32Ω"),
    ("AH7", "头戴式", 899, 24, "三模", "53mm", "可拆卸麦克风", "1200mAh", "约 300g", "虚拟 7.1", "32Ω"),
    ("AH7 Pro", "头戴式", 1099, 16, "三模", "53mm", "可拆卸降噪麦克风", "1200mAh", "约 305g", "虚拟 7.1", "32Ω"),
    ("AH7 Wireless", "头戴式", 999, 12, "2.4G", "53mm", "可拆卸麦克风", "1200mAh", "约 298g", "虚拟 7.1", "32Ω"),
    ("AH5", "头戴式", 599, 42, "三模", "50mm", "可拆卸麦克风", "1000mAh", "约 280g", "虚拟 7.1", "32Ω"),
    ("AH5 Pro", "头戴式", 799, 28, "三模", "50mm", "可拆卸降噪麦克风", "1000mAh", "约 285g", "虚拟 7.1", "32Ω"),
    ("AH5 Wireless", "头戴式", 699, 0, "2.4G", "50mm", "可拆卸麦克风", "1000mAh", "约 278g", "虚拟 7.1", "32Ω"),
    ("AH3", "头戴式", 349, 48, "有线", "53mm", "可拆卸麦克风", "无电池（有线供电）", "约 290g", "虚拟 7.1", "32Ω"),
    ("AH3 Pro", "头戴式", 499, 35, "有线", "53mm", "可拆卸降噪麦克风", "无电池（有线供电）", "约 295g", "虚拟 7.1", "32Ω"),
    ("AH1", "头戴式", 199, 90, "有线", "50mm", "可拆卸麦克风", "无电池（有线供电）", "约 260g", "虚拟 7.1", "32Ω"),
    ("AH1 Pro", "头戴式", 299, 62, "有线", "50mm", "可拆卸降噪麦克风", "无电池（有线供电）", "约 265g", "虚拟 7.1", "32Ω"),
    ("EH9", "入耳式", 699, 21, "三模", "10mm", "可拆卸双麦", "500mAh", "约 28g", "虚拟 7.1", "16Ω"),
    ("EH7", "入耳式", 399, 0, "三模", "10mm", "可拆卸麦克风", "400mAh", "约 25g", "虚拟 7.1", "16Ω"),
    ("EH7 Pro", "入耳式", 549, 33, "三模", "10mm", "可拆卸双麦", "450mAh", "约 26g", "虚拟 7.1", "16Ω"),
    ("EH5", "入耳式", 299, 76, "三模", "10mm", "可拆卸麦克风", "400mAh", "约 24g", "虚拟 7.1", "16Ω"),
    ("EH5 Pro", "入耳式", 429, 54, "三模", "10mm", "可拆卸双麦", "450mAh", "约 25g", "虚拟 7.1", "16Ω"),
    ("EH3", "入耳式", 149, 140, "有线", "10mm", "可拆卸麦克风", "无电池（有线供电）", "约 22g", "虚拟 7.1", "16Ω"),
    ("EH3 Pro", "入耳式", 229, 88, "有线", "10mm", "可拆卸双麦", "无电池（有线供电）", "约 23g", "虚拟 7.1", "16Ω"),
    ("EH1", "入耳式", 99, 180, "有线", "10mm", "可拆卸麦克风", "无电池（有线供电）", "约 20g", "无", "16Ω"),
    ("BH5 Pro", "头戴式蓝牙", 899, 6, "蓝牙 5.3", "40mm", "内置双麦", "1200mAh", "约 280g", "无", "32Ω"),
    ("BH5", "头戴式蓝牙", 699, 39, "蓝牙 5.3", "40mm", "内置双麦", "1000mAh", "约 270g", "无", "32Ω"),
    ("BH3", "头戴式蓝牙", 499, 57, "蓝牙 5.3", "40mm", "内置双麦", "900mAh", "约 260g", "无", "32Ω"),
    ("BH1", "头戴式蓝牙", 299, 85, "蓝牙 5.3", "40mm", "内置麦克风", "800mAh", "约 250g", "无", "32Ω"),
]


def build_catalog() -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    index = 0

    for model, layout, price, stock, connection in KEYBOARDS:
        products.append(_keyboard(model, layout, price, stock, connection, index))
        index += 1

    for (
        model,
        shape,
        price,
        stock,
        connection,
        sensor,
        dpi,
        polling,
        weight,
        buttons,
        battery,
        switch,
    ) in MICE:
        products.append(
            _mouse(
                model,
                shape,
                price,
                stock,
                connection,
                sensor,
                dpi,
                polling,
                weight,
                buttons,
                battery,
                switch,
                index,
            )
        )
        index += 1

    for (
        model,
        form,
        price,
        stock,
        connection,
        driver,
        mic,
        battery,
        weight,
        surround,
        impedance,
    ) in HEADSETS:
        products.append(
            _headset(
                model,
                form,
                price,
                stock,
                connection,
                driver,
                mic,
                battery,
                weight,
                surround,
                impedance,
                index,
            )
        )
        index += 1

    for offset, product in enumerate(products, 2001):
        product["id"] = f"P{offset}"

    _validate(products)
    return products


def _validate(products: list[dict[str, Any]]) -> None:
    if len(products) != 100:
        raise ValueError(f"商品数量应为 100，实际 {len(products)}")

    ids = [product["id"] for product in products]
    if len(set(ids)) != len(ids):
        raise ValueError("商品编号存在重复")

    models = [product["model"] for product in products]
    if len(set(models)) != len(models):
        raise ValueError("商品型号存在重复")

    expected_categories = {"键盘": 40, "鼠标": 35, "耳机": 25}
    actual: dict[str, int] = {}
    for product in products:
        actual[product["category"]] = actual.get(product["category"], 0) + 1
    if actual != expected_categories:
        raise ValueError(f"分类数量不符合预期：{actual}")

    out_of_stock = [product for product in products if product["stock"] == 0]
    if len(out_of_stock) >= 10:
        raise ValueError(f"缺货商品应少于 10 个，实际 {len(out_of_stock)}")

    for product in products:
        if not product["name"] or not product["specs"]:
            raise ValueError(f"{product['id']} 缺少名称或规格")
        if product["price"] <= 0:
            raise ValueError(f"{product['id']} 价格必须大于 0")
        if product["stock"] < 0:
            raise ValueError(f"{product['id']} 库存不能为负数")


def main() -> int:
    products = build_catalog()
    payload = {
        "brand": BRAND,
        "effective_date": EFFECTIVE_DATE,
        "description": "虚构电竞外设品牌商品库，用于电商客服 RAG 与工具调用演示。",
        "products": products,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    out_of_stock = [product for product in products if product["stock"] == 0]
    print(f"已生成 {len(products)} 个商品 -> {OUTPUT}")
    print(
        "分类："
        + "，".join(
            f"{category} {sum(1 for p in products if p['category'] == category)}"
            for category in ("键盘", "鼠标", "耳机")
        )
    )
    print(f"缺货商品 {len(out_of_stock)} 个：" + "、".join(p["name"] for p in out_of_stock))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
