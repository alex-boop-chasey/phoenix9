"""Tests that the stream replays logged events from any number, then follows live."""
import asyncio
import json

import httpx
from pydantic_ai.models.function import FunctionModel
from starlette.applications import Starlette
from starlette.routing import Route

from agentkit import llm, runs
from agentkit.store import Store

CHUNKS = ["one ", "two ", "three"]


def build(gate=None):
    """A store, a Runs with a scripted model (optionally gated mid-reply) and the app."""

    async def say(messages, info):
        yield CHUNKS[0]
        if gate is not None:
            await gate.wait()
        for chunk in CHUNKS[1:]:
            yield chunk

    store = Store(":memory:")
    r = runs.Runs(store, llm.build_agent(FunctionModel(stream_function=say)))
    app = Starlette(routes=[Route("/threads/{id}/stream", runs.stream_route(r, lambda _req: False, poll=0.005))])
    return store, r, app


def parse(text):
    """Parse an SSE body into (id, event) pairs, ignoring comments."""
    pairs = []
    for frame in text.split("\n\n"):
        lines = [ln for ln in frame.splitlines() if not ln.startswith(":")]
        if lines:
            fields = dict(ln.split(": ", 1) for ln in lines)
            pairs.append((int(fields["id"]), json.loads(fields["data"])))
    return pairs


async def read(app, tid, **kw):
    """GET the stream and return (id, event) pairs."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await asyncio.wait_for(c.get(f"/threads/{tid}/stream", **kw), 5)
    return r.text, parse(r.text)


def test_streams_in_order_while_the_run_goes():
    async def go():
        store, r, app = build()
        tid = store.create_thread()["id"]
        r.start(tid, "hi")
        return await read(app, tid)  # joins while the run is still going

    _, pairs = asyncio.run(go())
    assert [n for n, _ in pairs] == list(range(1, len(pairs) + 1))
    types = [e["type"] for _, e in pairs]
    assert types[0] == "RUN_STARTED" and types[-1] == "RUN_FINISHED"
    assert "".join(e["delta"] for _, e in pairs if e["type"] == "TEXT_MESSAGE_CONTENT") == "".join(CHUNKS)


def test_dropped_connection_then_reconnect_has_no_gaps_or_repeats():
    async def go():
        gate = asyncio.Event()
        store, r, app = build(gate)
        tid = store.create_thread()["id"]
        r.start(tid, "hi")
        await asyncio.sleep(0.05)  # first chunk logged, run held at the gate
        seen = store.events_after(tid)
        assert seen and not any(e["type"] == "RUN_FINISHED" for _, e in seen)
        last = seen[-1][0]
        # the first connection saw everything up to `last`, then dropped
        gate.set()
        _, rest = await read(app, tid, headers={"Last-Event-ID": str(last)})
        return seen, rest

    seen, rest = asyncio.run(go())
    assert rest[0][0] == seen[-1][0] + 1
    numbers = [n for n, _ in seen] + [n for n, _ in rest]
    assert numbers == list(range(1, len(numbers) + 1))
    assert rest[-1][1]["type"] == "RUN_FINISHED"


def test_reader_joining_after_the_run_gets_everything_and_after_n_skips():
    async def go():
        store, r, app = build()
        tid = store.create_thread()["id"]
        r.start(tid, "hi")
        await r.active[tid]
        whole = await read(app, tid)
        part = await read(app, tid, params={"after": "2"})
        idle = await read(app, tid, params={"after": "999"})
        return whole, part, idle

    (_, whole), (_, part), (idle_text, idle) = asyncio.run(go())
    assert [n for n, _ in whole] == list(range(1, len(whole) + 1))
    assert whole[-1][1]["type"] == "RUN_FINISHED"
    assert [n for n, _ in part] == [n for n, _ in whole][2:]
    assert idle == [] and idle_text.startswith(": heartbeat")
