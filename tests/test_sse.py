import asyncio

from core.sse import HEARTBEAT_FRAME, with_heartbeat


def collect(events):
    async def run():
        return [item async for item in events]

    return asyncio.run(run())


def test_heartbeat_is_emitted_while_idle():
    async def slow():
        yield "data: a\n\n"
        await asyncio.sleep(0.1)
        yield "data: b\n\n"

    frames = collect(with_heartbeat(slow(), 0.02))

    assert frames[0] == "data: a\n\n"
    assert HEARTBEAT_FRAME in frames
    assert frames[-1] == "data: b\n\n"


def test_heartbeat_disabled_passes_through():
    async def quick():
        yield "data: a\n\n"

    assert collect(with_heartbeat(quick(), 0)) == ["data: a\n\n"]


def test_heartbeat_stops_after_source_error():
    async def broken():
        yield "data: a\n\n"
        raise RuntimeError("boom")

    assert collect(with_heartbeat(broken(), 0.05)) == ["data: a\n\n"]
