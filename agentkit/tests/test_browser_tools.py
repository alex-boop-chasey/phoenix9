"""Tests that browser tools pause the run, check their inputs, and resume with the browser's result."""
import asyncio
import json
from typing import Literal

import httpx
from pydantic import BaseModel
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from starlette.applications import Starlette
from starlette.routing import Route

from agentkit import llm, runs
from agentkit.pack import BrowserTool, Pack
from agentkit.store import Store


class Where(BaseModel):
    page: Literal["home", "projects"]


def make_pack():
    """A pack with one browser tool, go_to."""
    return Pack(name="t", instructions="", browser_tools=(BrowserTool("go_to", "Open a page.", Where),))


def script(plan, seen):
    """A model that makes the planned tool calls one turn at a time, then says it is finished."""

    async def reply(messages, info: AgentInfo):
        seen.append(messages)
        turn = sum(1 for m in messages if isinstance(m, ModelResponse))
        if turn < len(plan):
            name, args = plan[turn]
            yield {0: DeltaToolCall(name=name, json_args=json.dumps(args), tool_call_id=f"call-{turn}")}
        else:
            yield "All done."

    return FunctionModel(stream_function=reply)


def build(plan):
    """A store, a Runs and an app with the browser-results route."""
    store, seen, pack = Store(":memory:"), [], make_pack()
    r = runs.Runs(store, llm.build_pack_agent(script(plan, seen), pack), pack)
    app = Starlette(routes=[Route("/browser-results/{id}", runs.browser_route(r, lambda _q: False), methods=["POST"])])
    return store, r, app, seen


def client(app):
    """An async client talking straight to the app."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def customs(store, tid, name):
    """The values of the CUSTOM events with this name."""
    return [e["value"] for _, e in store.events_after(tid) if e["type"] == "CUSTOM" and e["name"] == name]


def types(store, tid):
    """The event types logged so far."""
    return [e["type"] for _, e in store.events_after(tid)]


def model_text(seen):
    """All message text the model saw on its last call."""
    return " ".join(str(getattr(p, "content", "")) for m in seen[-1] for p in getattr(m, "parts", []))


def test_pause_and_resume_with_quoted_result():
    async def go():
        store, r, app, seen = build([("go_to", {"page": "projects"})])
        tid = store.create_thread()["id"]
        r.start(tid, "take me there")
        await r.active[tid]
        (ask,) = customs(store, tid, "browser_tool")
        assert ask["toolName"] == "go_to" and ask["input"] == {"page": "projects"}
        assert "RUN_FINISHED" not in types(store, tid)
        async with client(app) as c:
            resp = await c.post(f"/browser-results/{ask['browserId']}", json={"result": {"ok": True}})
            assert resp.status_code == 202
            await r.active[tid]
        assert types(store, tid)[-1] == "RUN_FINISHED"
        text = model_text(seen)
        assert "quoted_from" in text and "data, not instructions" in text and "the browser" in text

    asyncio.run(go())


def test_bad_inputs_go_back_to_the_model_without_pausing():
    async def go():
        store, r, _app, seen = build([("go_to", {"page": "moon"})])
        tid = store.create_thread()["id"]
        r.start(tid, "go")
        await r.active[tid]
        for _ in range(100):
            if tid not in r.active and types(store, tid)[-1] == "RUN_FINISHED":
                break
            await asyncio.sleep(0.01)
            if tid in r.active:
                await r.active[tid]
        assert customs(store, tid, "browser_tool") == []
        assert store.pending_pauses(tid) == []
        assert types(store, tid)[-1] == "RUN_FINISHED"
        assert "were not valid" in model_text(seen) and "page" in model_text(seen)

    asyncio.run(go())


def test_a_second_answer_or_unknown_id_is_refused():
    async def go():
        store, r, app, _seen = build([("go_to", {"page": "home"})])
        tid = store.create_thread()["id"]
        r.start(tid, "go")
        await r.active[tid]
        bid = customs(store, tid, "browser_tool")[0]["browserId"]
        async with client(app) as c:
            assert (await c.post(f"/browser-results/{bid}", json={"result": 1})).status_code == 202
            await r.active[tid]
            assert (await c.post(f"/browser-results/{bid}", json={"result": 2})).status_code == 409
            assert (await c.post("/browser-results/nope", json={"result": 1})).status_code == 404
            assert (await c.post(f"/browser-results/{bid}", json={})).status_code == 400
        assert types(store, tid).count("RUN_FINISHED") == 1

    asyncio.run(go())
