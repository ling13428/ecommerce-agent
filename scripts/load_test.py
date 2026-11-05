from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from uuid import uuid4

import httpx


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(ratio * (len(ordered) - 1))))
    return ordered[index]


async def run(args: argparse.Namespace) -> dict:
    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    latencies: list[float] = []
    statuses: dict[int, int] = {}
    errors: list[str] = []
    started = time.perf_counter()

    async with httpx.AsyncClient(timeout=args.timeout) as client:

        async def one(index: int) -> None:
            async with semaphore:
                begin = time.perf_counter()
                try:
                    if args.mode == "health":
                        response = await client.get(args.url + "/health")
                        await response.aread()
                    else:
                        session_id = f"loadtest-{uuid4().hex[:12]}"
                        async with client.stream(
                            "POST",
                            args.url + "/api/chat/stream",
                            json={
                                "message": "你好",
                                "session_id": session_id,
                            },
                        ) as response:
                            async for _ in response.aiter_lines():
                                pass
                    elapsed = (time.perf_counter() - begin) * 1000
                    latencies.append(elapsed)
                    statuses[response.status_code] = (
                        statuses.get(response.status_code, 0) + 1
                    )
                except Exception as exc:
                    errors.append(f"{index}: {type(exc).__name__}: {exc}")

        await asyncio.gather(*(one(index) for index in range(args.requests)))

    total_seconds = time.perf_counter() - started
    return {
        "mode": args.mode,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "total_seconds": round(total_seconds, 3),
        "rps": round(args.requests / total_seconds, 2)
        if total_seconds
        else 0,
        "statuses": statuses,
        "errors": errors[:10],
        "latency_ms": {
            "mean": round(statistics.mean(latencies), 2) if latencies else 0,
            "p50": round(percentile(latencies, 0.50), 2),
            "p95": round(percentile(latencies, 0.95), 2),
            "p99": round(percentile(latencies, 0.99), 2),
            "max": round(max(latencies), 2) if latencies else 0,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SSE/健康检查压测")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--mode", choices=["chat", "health"], default="chat")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--output", default="reports/load_test.json")
    args = parser.parse_args(argv)

    report = asyncio.run(run(args))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    try:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
    except OSError as exc:
        print(f"报告写入失败：{exc}", file=sys.stderr)
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
