import asyncio

import pytest

from core.session_lock import SessionBusy, session_lock


@pytest.mark.asyncio
async def test_session_lock_serializes_same_session():
    active = 0
    peak = 0

    async def worker():
        nonlocal active, peak
        async with session_lock("same-session"):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1

    await asyncio.gather(*(worker() for _ in range(5)))
    assert peak == 1


@pytest.mark.asyncio
async def test_session_lock_allows_different_sessions():
    order = []

    async def worker(name, delay):
        async with session_lock(name):
            order.append(name)
            await asyncio.sleep(delay)

    await asyncio.gather(worker("a", 0.05), worker("b", 0.01))
    assert order == ["a", "b"]


@pytest.mark.asyncio
async def test_session_lock_times_out_when_busy():
    started = asyncio.Event()

    async def holder():
        async with session_lock("busy-session", timeout=5):
            started.set()
            await asyncio.sleep(0.3)

    task = asyncio.create_task(holder())
    await started.wait()

    with pytest.raises(SessionBusy):
        async with session_lock("busy-session", timeout=0.05):
            pass

    await task
