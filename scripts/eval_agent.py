from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SESSION_PERSISTENCE", "false")
os.environ.setdefault("CACHE_BACKEND", "memory")
os.environ.setdefault("AGENT_CHECKPOINT_BACKEND", "memory")
os.environ.setdefault("PRODUCT_PROVIDER", "mock")
os.environ.setdefault("ORDER_PROVIDER", "mock")

from agent.router import route_message, route_message_l2  # noqa: E402
from agent.session import SessionState  # noqa: E402
from tools.context import ToolContext  # noqa: E402
from tools.registry import execute_tool  # noqa: E402

GOLD = ROOT / "data" / "eval" / "agent_gold.jsonl"
REPORT = ROOT / "reports" / "agent_eval.json"


def load_items() -> list[dict]:
    items = []
    for line in GOLD.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            items.append(json.loads(line))
    return items


def check_route(item: dict, route) -> tuple[bool, str]:
    if route.route != item["route"]:
        return False, f"route={route.route} (期望 {item['route']})"
    if item["sub_intent"] and route.sub_intent != item["sub_intent"]:
        return False, f"sub_intent={route.sub_intent} (期望 {item['sub_intent']})"
    if item["tool"] and item["tool"] not in route.allowed_tools:
        return False, f"tool={item['tool']} 不在白名单 {sorted(route.allowed_tools)}"
    if item.get("expect_handoff") and route.action != "handoff":
        return False, f"action={route.action} (期望 handoff)"
    return True, ""


async def eval_router(items: list[dict], use_l2: bool) -> dict:
    results = []
    for item in items:
        session = SessionState(session_id=f"eval-{item['id']}")
        session.add_user(item["message"])
        start = time.perf_counter()
        if use_l2:
            route = await route_message_l2(item["message"], session)
        else:
            route = route_message(item["message"], session)
        elapsed = (time.perf_counter() - start) * 1000
        ok, reason = check_route(item, route)
        results.append(
            {
                "id": item["id"],
                "category": item["category"],
                "message": item["message"],
                "ok": ok,
                "reason": reason,
                "actual": {
                    "route": route.route,
                    "sub_intent": route.sub_intent,
                    "action": route.action,
                    "source": route.source,
                },
                "expected": {
                    "route": item["route"],
                    "sub_intent": item["sub_intent"],
                    "tool": item["tool"],
                },
                "elapsed_ms": round(elapsed, 2),
            }
        )
    return summarize(results)


def eval_tools(items: list[dict], skip_knowledge: bool) -> dict:
    results = []
    for item in items:
        tool = item.get("tool")
        if not tool or item.get("expect_handoff"):
            continue
        if skip_knowledge and tool == "search_knowledge":
            continue
        context = ToolContext(
            buyer_id=item.get("buyer_id"),
            session_id=f"eval-{item['id']}",
        )
        start = time.perf_counter()
        result = execute_tool(
            tool,
            item.get("tool_args") or {},
            confirmed=False,
            context=context,
        )
        elapsed = (time.perf_counter() - start) * 1000
        ok = bool(result.get("ok"))
        reason = ""
        if item.get("expect_confirm"):
            if result.get("status") == "confirm_required":
                ok = True
            else:
                ok = False
                reason = f"期望 confirm_required，实际 {result.get('status')}"
        payload = json.dumps(result, ensure_ascii=False, default=str)
        for keyword in item.get("keywords") or []:
            if keyword not in payload:
                ok = False
                reason = f"缺少关键词 {keyword}"
        results.append(
            {
                "id": item["id"],
                "category": item["category"],
                "tool": tool,
                "ok": ok,
                "reason": reason,
                "status": result.get("status"),
                "elapsed_ms": round(elapsed, 2),
            }
        )
    return summarize(results)


def summarize(results: list[dict]) -> dict:
    by_category: dict[str, list[bool]] = defaultdict(list)
    for item in results:
        by_category[item["category"]].append(item["ok"])
    total = len(results)
    passed = sum(1 for item in results if item["ok"])
    categories = {
        category: {
            "total": len(values),
            "passed": sum(1 for value in values if value),
            "accuracy": round(sum(1 for value in values if value) / len(values), 3),
        }
        for category, values in sorted(by_category.items())
    }
    return {
        "total": total,
        "passed": passed,
        "accuracy": round(passed / total, 3) if total else 0.0,
        "by_category": categories,
        "failures": [item for item in results if not item["ok"]],
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent 路由/工具有效性评测")
    parser.add_argument(
        "--mode", choices=["router", "tools"], default="router"
    )
    parser.add_argument("--l2", action="store_true", help="路由评测启用 L2 LLM")
    parser.add_argument("--skip-knowledge", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--threshold", type=float, default=0.0)
    args = parser.parse_args(argv)

    items = load_items()
    if args.limit:
        items = items[: args.limit]

    if args.mode == "router":
        report = asyncio.run(eval_router(items, args.l2))
    else:
        report = eval_tools(items, args.skip_knowledge)

    report["mode"] = args.mode
    report["l2"] = bool(args.l2)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"模式：{args.mode}  L2：{args.l2}")
    print(
        f"总计 {report['total']}，通过 {report['passed']}，"
        f"准确率 {report['accuracy']:.1%}"
    )
    for category, stats in report["by_category"].items():
        print(
            f"  {category:10s} {stats['passed']:3d}/{stats['total']:<3d} "
            f"{stats['accuracy']:.1%}"
        )
    for failure in report["failures"][:10]:
        print(
            f"  FAIL {failure['id']} {failure.get('message') or failure.get('tool')}"
            f"：{failure.get('reason') or failure.get('status')}"
        )
    print(f"报告：{REPORT}")

    if args.threshold and report["accuracy"] < args.threshold:
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
