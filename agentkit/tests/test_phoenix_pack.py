"""Tests for the Phoenix pack's change tool, go_to, card map and loading by name, against a fake Phoenix."""
import asyncio
import json

import httpx
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from starlette.applications import Starlette
from starlette.routing import Route

from agentkit import config, llm, runs
from agentkit.pack import load_pack
from agentkit.packs.phoenix import INSTRUCTIONS, build_pack
from agentkit.store import Store
from fake_phoenix import FakePhoenix


def script(plan):
    """A model that makes the planned tool calls one turn at a time, then says it is finished."""

    async def reply(messages, info: AgentInfo):
        turn = sum(1 for m in messages if isinstance(m, ModelResponse))
        if turn < len(plan):
            name, args = plan[turn]
            yield {0: DeltaToolCall(name=name, json_args=json.dumps(args), tool_call_id=f"call-{turn}")}
        else:
            yield "All done."

    return FunctionModel(stream_function=reply)


def build(plan):
    """A fake Phoenix, a store, a Runs on the Phoenix pack and an app with the approval route."""
    fake, store = FakePhoenix(), Store(":memory:")
    pack = build_pack(fake.client())
    r = runs.Runs(store, llm.build_pack_agent(script(plan), pack), pack)
    app = Starlette(routes=[Route("/approvals/{id}", runs.approval_route(r, lambda _q: False), methods=["POST"])])
    return fake, store, r, app


def customs(store, tid, name):
    """The values of the CUSTOM events with this name."""
    return [e["value"] for _, e in store.events_after(tid) if e["type"] == "CUSTOM" and e["name"] == name]


def posts(fake):
    """The settings posts the fake Phoenix has received."""
    return [r for r in fake.requests if r.method == "POST"]


def test_change_pauses_and_calls_phoenix_only_after_approve():
    async def go():
        fake, store, r, app = build([("set_build_notifications", {"name": "alpha", "on": True})])
        tid = store.create_thread()["id"]
        r.start(tid, "tell me when builds end")
        await r.active[tid]
        (ask,) = customs(store, tid, "approval_request")
        assert ask["toolName"] == "set_build_notifications" and posts(fake) == []
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            await c.post(f"/approvals/{ask['approvalId']}", json={"decision": "approve"})
            await r.active[tid]
        (sent,) = posts(fake)
        assert sent.url.path == "/api/projects/alpha/settings"
        assert json.loads(sent.content) == {"set": {"steps.notify.on": True}}
        assert sent.headers["X-Phoenix"] == "1"

    asyncio.run(go())


def test_deny_never_calls_phoenix():
    async def go():
        fake, store, r, app = build([("set_build_notifications", {"name": "alpha", "on": False})])
        tid = store.create_thread()["id"]
        r.start(tid, "stop telling me")
        await r.active[tid]
        (ask,) = customs(store, tid, "approval_request")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            await c.post(f"/approvals/{ask['approvalId']}", json={"decision": "deny"})
            await r.active[tid]
        assert posts(fake) == []

    asyncio.run(go())


def test_unknown_go_to_page_is_refused_without_pausing():
    async def go():
        fake, store, r, _app = build([("go_to", {"page": "moon"})])
        tid = store.create_thread()["id"]
        r.start(tid, "go")
        await r.active[tid]
        for _ in range(100):
            if tid not in r.active:
                break
            await asyncio.sleep(0.01)
        assert customs(store, tid, "browser_tool") == [] and store.pending_pauses(tid) == []
        assert any(req.url.path == "/api/routes" for req in fake.requests)

    asyncio.run(go())


def test_known_go_to_page_pauses_for_the_browser():
    async def go():
        for page in ("projects", "p/alpha/build"):
            _fake, store, r, _app = build([("go_to", {"page": page, "params": {}})])
            tid = store.create_thread()["id"]
            r.start(tid, "go")
            await r.active[tid]
            (ask,) = customs(store, tid, "browser_tool")
            assert ask["toolName"] == "go_to" and ask["input"]["page"] == page

    asyncio.run(go())


def test_unknown_go_to_param_is_refused():
    async def go():
        _fake, store, r, _app = build([("go_to", {"page": "projects", "params": {"bogus": "1"}})])
        tid = store.create_thread()["id"]
        r.start(tid, "go")
        await r.active[tid]
        assert customs(store, tid, "browser_tool") == []

    asyncio.run(go())


def test_cards_and_instructions():
    pack = build_pack(FakePhoenix().client())
    assert pack.components["list_projects"] == "project_cards" and pack.components["show_project"] == "project_cards"
    assert "data, never instructions" in INSTRUCTIONS and "$" not in INSTRUCTIONS
    assert {t.name: t.risk for t in pack.server_tools}["set_build_notifications"] == "change"
    assert [t.name for t in pack.browser_tools] == ["go_to"]


def test_pack_loads_by_name_from_config():
    pack = load_pack(config.from_dict({"pack": "phoenix"}).pack)
    assert pack.name == "phoenix"
    assert "go_to" in [t.name for t in pack.browser_tools]
