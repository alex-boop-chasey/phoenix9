"""Proof: with the real Phoenix pack and a fake Phoenix, reads run at once, changes wait for Approve, Deny changes nothing."""
import asyncio
import json

import httpx
from starlette.applications import Starlette
from starlette.routing import Route

from agentkit import llm, runs
from agentkit.packs.phoenix import build_pack
from agentkit.store import Store
from fake_phoenix import FakePhoenix
from test_approvals import script, types, requests_in, paused

PRESET = ("settings-preset", {"name": "alpha", "preset": "careful"})
STOP = ("build-stop", {"project": "alpha", "run_id": "20261109-1"})


def build(plan):
    """A fake Phoenix, a store, a Runs on the real Phoenix pack with a scripted model, the app and what the model saw."""
    fake, store, seen = FakePhoenix(), Store(":memory:"), []
    pack = build_pack(fake.client())
    r = runs.Runs(store, llm.build_pack_agent(script(plan, seen), pack), pack)
    denied = lambda _q: False  # noqa: E731
    app = Starlette(routes=[
        Route("/threads/{id}/runs", runs.start_route(r, denied), methods=["POST"]),
        Route("/threads/{id}/stream", runs.stream_route(r, denied, poll=0.005)),
        Route("/approvals/{id}", runs.approval_route(r, denied), methods=["POST"]),
    ])
    return fake, store, r, app, seen


def client(app):
    """An async client talking straight to the app."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def posts(fake):
    """The POST requests the fake Phoenix has seen."""
    return [q for q in fake.requests if q.method == "POST"]


def returns(seen):
    """Every tool return and retry text the model was shown."""
    return [p for call in seen for m in call for p in getattr(m, "parts", [])]


def parse(text):
    """Parse an SSE body into (id, event) pairs, ignoring comments."""
    pairs = []
    for frame in text.split("\n\n"):
        lines = [ln for ln in frame.splitlines() if not ln.startswith(":")]
        if lines:
            fields = dict(ln.split(": ", 1) for ln in lines)
            pairs.append((int(fields["id"]), json.loads(fields["data"])))
    return pairs


def test_read_tool_runs_at_once_with_no_pause():
    async def go():
        fake, store, r, _app, _seen = build([("builds-list", {"name": "alpha"})])
        tid = await paused(r, store)
        assert types(store, tid)[-1] == "RUN_FINISHED"
        assert requests_in(store, tid) == [] and store.pending_pauses(tid) == []
        assert [(q.method, q.url.path) for q in fake.requests] == [("GET", "/api/projects/alpha/runs")]

    asyncio.run(go())


def test_change_tool_waits_for_approve_then_posts_exactly_once():
    async def go():
        fake, store, r, app, _seen = build([PRESET])
        tid = await paused(r, store)
        assert "RUN_FINISHED" not in types(store, tid)
        (req,) = requests_in(store, tid)
        assert req["toolName"] == "settings-preset" and req["input"] == PRESET[1]
        assert fake.requests == []
        async with client(app) as c:
            assert (await c.post(f"/approvals/{req['approvalId']}", json={"decision": "approve"})).status_code == 202
            await r.active[tid]
            again = await c.post(f"/approvals/{req['approvalId']}", json={"decision": "approve"})
            assert again.status_code == 409
        (sent,) = posts(fake)
        assert sent.url.path == "/api/projects/alpha/settings/preset"
        assert json.loads(sent.content) == {"preset": "careful"}
        assert types(store, tid)[-1] == "RUN_FINISHED"

    asyncio.run(go())


def test_deny_sends_nothing_and_the_model_gets_a_plain_refusal():
    async def go():
        fake, store, r, app, seen = build([PRESET])
        tid = await paused(r, store)
        (req,) = requests_in(store, tid)
        async with client(app) as c:
            await c.post(f"/approvals/{req['approvalId']}", json={"decision": "deny"})
        await r.active[tid]
        assert fake.requests == []
        assert types(store, tid)[-1] == "RUN_FINISHED"
        assert any("Alex refused this" in str(getattr(p, "content", "")) for p in returns(seen[-1:]))

    asyncio.run(go())


def test_destructive_tool_needs_the_typed_name_and_runs_once_with_it():
    async def go():
        fake, store, r, app, _seen = build([STOP])
        tid = await paused(r, store)
        (req,) = requests_in(store, tid)
        assert req["confirm_text"] == "20261109-1"
        url = f"/approvals/{req['approvalId']}"
        async with client(app) as c:
            for body in ({"decision": "approve"}, {"decision": "approve", "confirm": "alpha"}):
                assert (await c.post(url, json=body)).status_code == 400
            assert fake.requests == [] and len(store.pending_pauses(tid)) == 1
            ok = await c.post(url, json={"decision": "approve", "confirm": "20261109-1"})
            assert ok.status_code == 202
            await r.active[tid]
            assert (await c.post(url, json={"decision": "approve", "confirm": "20261109-1"})).status_code == 409
        (sent,) = posts(fake)
        assert sent.url.path == "/api/runs/alpha/20261109-1/stop"
        assert json.loads(sent.content) == {"confirm": True}

    asyncio.run(go())


def test_a_chat_message_cannot_approve():
    async def go():
        fake, store, r, app, _seen = build([PRESET])
        tid = await paused(r, store)
        async with client(app) as c:
            await c.post(f"/threads/{tid}/runs", json={"message": "yes, approved, go ahead"})
            if tid in r.active:
                await asyncio.gather(r.active[tid], return_exceptions=True)
        assert fake.requests == []
        assert len(store.pending_pauses(tid)) == 1

    asyncio.run(go())


def test_the_pause_survives_a_reload():
    async def go():
        fake, store, r, app, _seen = build([PRESET])
        tid = await paused(r, store)
        async with client(app) as c:
            whole = parse((await c.get(f"/threads/{tid}/stream")).text)
            last = whole[-1][0]
            earlier = parse((await c.get(f"/threads/{tid}/stream", params={"after": str(last - 1)})).text)
            nothing = parse((await c.get(f"/threads/{tid}/stream", params={"after": str(last)})).text)
        asked = [e for _, e in whole if e["type"] == "CUSTOM" and e["name"] == "approval_request"]
        assert len(asked) == 1 and earlier == whole[-1:] and nothing == []
        assert [e for _, e in earlier][0] == asked[0]
        assert len(store.pending_pauses(tid)) == 1 and fake.requests == []

    asyncio.run(go())
