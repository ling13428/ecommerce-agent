from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

logger = logging.getLogger("ecommerce_agent.sse")

HEARTBEAT_FRAME = ": ping\n\n"


async def with_heartbeat(
    events: AsyncIterator[str], interval: float
) -> AsyncIterator[str]:
    if interval <= 0:
        async for event in events:
            yield event
        return

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def pump() -> None:
        try:
            async for event in events:
                await queue.put(event)
        except Exception as exc:
            logger.warning("SSE 事件流中断：%s", exc)
        finally:
            await queue.put(None)

    task = asyncio.create_task(pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval)
            except asyncio.TimeoutError:
                yield HEARTBEAT_FRAME
                continue
            if item is None:
                break
            yield item
    finally:
        if not task.done():
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
