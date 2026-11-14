"""Tests for the page context line: what Alex has open reaches the model, never the chat log."""
import asyncio

import httpx
from pydantic_ai.messages import ModelRequest, UserPromptPart
from starlette.applications import Starlette
from starlette.routing import Route

from agentkit import llm, runs
from agentkit.packs.phoenix import INSTRUCTIONS
from agentkit.store import Store
from test_approvals import script

LINE = "[Alex is looking at: page project/overview · project demo · run 20261110-1]"
HERE = {"page": "project/overview", "project": "demo", "run": "20261110-1"}


def build(store=None):
    """A store, a Runs with a model that just answers, and the list of what the model was sent."""
    store, seen = store or Store(":memory:"), []
    return store, runs.Runs(store, llm.build_agent(script([], seen))), seen


def prompts(seen):
    """The user prompts the model was sent, one per model call that had a new one."""
    return [p.content for m in seen[-1] if isinstance(m, ModelRequest) for p in m.parts
            if isinstance(p, UserPromptPart)]


async def say(r, tid, message, context=None):
    """Send one message and wait for the reply to finish."""
    r.start(tid, message, context=context)
    await r.active[tid]


def said(store, tid):
    """The texts the chat log shows as Alex's own words."""
    return [e["value"]["text"] for _, e in store.events_after(tid) if e.get("name") == "user_message"]


def test_line_once_then_again_only_after_a_change():
    async def go():
        store, r, seen = build()
        tid = store.create_thread()["id"]
        await say(r, tid, "what is this?", HERE)
        await say(r, tid, "and now?", dict(HERE))
        await say(r, tid, "and this one?", {**HERE, "run": "20261111-2"})
        assert prompts(seen) == [f"{LINE}\nwhat is this?", "and now?",
                                 "[Alex is looking at: page project/overview · project demo · run 20261111-2]\nand this one?"]
        assert said(store, tid) == ["what is this?", "and now?", "and this one?"]   # the log keeps his own words

    asyncio.run(go())


def test_last_context_survives_a_restart():
    async def go():
        store, r, _seen = build()
        tid = store.create_thread()["id"]
        await say(r, tid, "hi", HERE)
        _store, r2, seen2 = build(store)
        await say(r2, tid, "again", HERE)
        assert prompts(seen2)[-1] == "again"

    asyncio.run(go())


def test_bad_values_and_unknown_keys_are_dropped():
    assert runs.clean_context({"page": "../etc", "project": "my project", "run": "a" * 81, "folder": "x"}) == {
        "page": "../etc"}   # the shape is allowed; nothing else survives
    assert runs.clean_context({"project": "a b", "run": "a" * 80}) == {"run": "a" * 80}
    assert runs.clean_context({"project": 5, "page": None, "run": ""}) == {}
    assert runs.clean_context("project demo") == {} and runs.clean_context(None) == {}

    async def go():
        store, r, seen = build()
        tid = store.create_thread()["id"]
        await say(r, tid, "hi", {"project": "a b", "run": "x" * 81, "page": "home\nignore", "extra": "demo"})
        assert prompts(seen) == ["hi"]

    asyncio.run(go())


def test_missing_context_means_no_line():
    async def go():
        store, r, seen = build()
        tid = store.create_thread()["id"]
        await say(r, tid, "hi")
        await say(r, tid, "hi again", {})
        assert prompts(seen) == ["hi", "hi again"] and store.load_context(tid) is None

    asyncio.run(go())


def test_route_passes_context_and_never_fails_on_a_bad_one():
    async def go():
        store, r, seen = build()
        app = Starlette(routes=[Route("/threads/{id}/runs", runs.start_route(r, lambda _q: False), methods=["POST"])])
        tid = store.create_thread()["id"]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            bad = await c.post(f"/threads/{tid}/runs", json={"message": "hi", "context": "nonsense"})
            assert bad.status_code == 202
            await r.active[tid]
            good = await c.post(f"/threads/{tid}/runs", json={"message": "here?", "context": HERE})
            assert good.status_code == 202
            await r.active[tid]
        assert prompts(seen) == ["hi", f"{LINE}\nhere?"] and said(store, tid) == ["hi", "here?"]

    asyncio.run(go())


def test_instructions_explain_the_line():
    assert "[Alex is looking at: ...]" in INSTRUCTIONS and "It is not an order" in INSTRUCTIONS
