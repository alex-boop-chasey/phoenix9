"""Tests for the ask_choice and ask_env_file browser tools: valid calls pause, bad ones are refused, results are cut down."""
import asyncio

from agentkit import llm, runs
from agentkit.packs.phoenix import build_pack
from agentkit.store import Store
from starlette.applications import Starlette
from starlette.routing import Route
from test_browser_tools import client, customs, model_text, script, types

OPTS = [{"label": f"o{i}", "hint": "h"} for i in range(12)]


def build(plan):
    """A store, Runs and app around the real Phoenix pack."""
    store, seen, pack = Store(":memory:"), [], build_pack()
    r = runs.Runs(store, llm.build_pack_agent(script(plan, seen), pack), pack)
    app = Starlette(routes=[Route("/browser-results/{id}", runs.browser_route(r, lambda _q: False), methods=["POST"])])
    return store, r, app, seen


async def start(plan):
    """Run the first turn and return the pieces."""
    store, r, app, seen = build(plan)
    tid = store.create_thread()["id"]
    r.start(tid, "go")
    await r.active[tid]
    return store, r, app, seen, tid


def test_valid_calls_pause():
    async def go():
        for name, inp in (("ask_choice", {"question": "Which?", "options": OPTS[:2]}),
                          ("ask_env_file", {"project": "demo", "why": "needs keys"})):
            store, _r, _app, _seen, tid = await start([(name, inp)])
            (ask,) = customs(store, tid, "browser_tool")
            assert ask["toolName"] == name
            assert "RUN_FINISHED" not in types(store, tid)

    asyncio.run(go())


def test_bad_choice_calls_are_refused():
    async def go():
        bad = [{"question": "Q", "options": OPTS[:1]}, {"question": "Q", "options": OPTS + OPTS[:1]},
               {"question": "x" * 201, "options": OPTS[:2]}]
        for inp in bad:
            store, r, _app, seen, tid = await start([("ask_choice", inp)])
            for _ in range(100):
                if tid not in r.active:
                    break
                await r.active[tid]
            assert customs(store, tid, "browser_tool") == []
            assert "were not valid" in model_text(seen)

    asyncio.run(go())


def test_results_are_cut_down():
    async def go():
        store, r, app, seen, tid = await start([("ask_choice", {"question": "Q", "options": OPTS[:3]})])
        (ask,) = customs(store, tid, "browser_tool")
        body = {"result": {"status": "picked", "picked": [1, "secret text"], "extra": "LEAK"}}
        async with client(app) as c:
            await c.post(f"/browser-results/{ask['browserId']}", json=body)
        await r.active[tid]
        text = model_text(seen)
        assert "LEAK" not in text and "secret text" not in text and "picked" in text

        store, r, app, seen, tid = await start([("ask_env_file", {"project": "d", "why": "w"})])
        (ask,) = customs(store, tid, "browser_tool")
        body = {"result": {"status": "saved", "added": 2, "replaced": 999, "value": "LEAK"}}
        async with client(app) as c:
            await c.post(f"/browser-results/{ask['browserId']}", json=body)
        await r.active[tid]
        text = model_text(seen)
        assert "LEAK" not in text and "999" not in text and "added" in text

    asyncio.run(go())
