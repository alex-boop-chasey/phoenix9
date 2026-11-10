"""Tests that change and destructive tools pause for approval enforced by the server."""
import asyncio
import json

import httpx
from pydantic import BaseModel
from pydantic_ai.messages import ModelResponse, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from starlette.applications import Starlette
from starlette.routing import Route

from agentkit import llm, runs
from agentkit.pack import Pack, ServerTool
from agentkit.store import Store


class Nothing(BaseModel):
    pass


class Setting(BaseModel):
    value: str


def make_pack(done):
    """A pack with one tool of each risk; `done` records every time a change or destructive tool really ran."""

    def look():
        return {"seen": True}

    def change(value):
        done.append(("change", value))
        return {"set": value}

    def wipe():
        done.append(("wipe",))
        return {"wiped": True}

    return Pack(name="t", instructions="", server_tools=(
        ServerTool("look", "Look.", Nothing, "read", look),
        ServerTool("change", "Change.", Setting, "change", change),
        ServerTool("wipe", "Wipe.", Nothing, "destructive", wipe),
    ))


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


def build(plan, done, store=None, seen=None):
    """A store, a Runs and an app with the approval route."""
    store = store or Store(":memory:")
    seen = seen if seen is not None else []
    r = runs.Runs(store, llm.build_pack_agent(script(plan, seen), make_pack(done)))
    app = Starlette(routes=[Route("/approvals/{id}", runs.approval_route(r, lambda _q: False), methods=["POST"])])
    return store, r, app, seen


def client(app):
    """An async client talking straight to the app."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def types(store, tid):
    """The event types logged so far."""
    return [e["type"] for _, e in store.events_after(tid)]


def requests_in(store, tid):
    """The approval_request values logged so far."""
    return [e["value"] for _, e in store.events_after(tid) if e["type"] == "CUSTOM" and e["name"] == "approval_request"]


async def paused(r, store, plan_message="go"):
    """Start a run and wait for it to stop; return the thread id."""
    tid = store.create_thread()["id"]
    r.start(tid, plan_message)
    await r.active[tid]
    return tid


def test_read_tool_runs_at_once():
    async def go():
        done = []
        store, r, _app, _seen = build([("look", {})], done)
        tid = await paused(r, store)
        assert types(store, tid)[-1] == "RUN_FINISHED"
        assert requests_in(store, tid) == [] and store.pending_pauses() == []

    asyncio.run(go())


def test_change_and_destructive_tools_stop_the_run_and_record_the_pause():
    async def go():
        for name, args in (("change", {"value": "on"}), ("wipe", {})):
            done = []
            store, r, _app, _seen = build([(name, args)], done)
            tid = await paused(r, store)
            assert "RUN_FINISHED" not in types(store, tid) and done == []
            (req,) = requests_in(store, tid)
            assert req["toolName"] == name and req["input"] == args
            (pause,) = store.pending_pauses(tid)
            assert pause["id"] == req["approvalId"] and pause["inputs"] == args and pause["tool"] == name

    asyncio.run(go())


def test_approve_runs_the_tool_and_finishes_and_is_logged():
    async def go():
        done = []
        store, r, app, seen = build([("change", {"value": "on"})], done)
        tid = await paused(r, store)
        approval_id = requests_in(store, tid)[0]["approvalId"]
        async with client(app) as c:
            assert (await c.post(f"/approvals/{approval_id}", json={"decision": "approve"})).status_code == 202
            await r.active[tid]
            assert done == [("change", "on")]
            assert types(store, tid)[-1] == "RUN_FINISHED"
            logged = [e["value"] for _, e in store.events_after(tid) if e.get("name") == "approval_decision"]
            assert logged == [{"approvalId": approval_id, "decision": "approve"}]
            again = await c.post(f"/approvals/{approval_id}", json={"decision": "deny"})
            assert again.status_code == 409
            assert (await c.post("/approvals/nope", json={"decision": "approve"})).status_code == 404
            assert (await c.post(f"/approvals/{approval_id}", json={"decision": "yes"})).status_code == 400
        assert done == [("change", "on")]

    asyncio.run(go())


def test_deny_tells_the_model_and_never_runs_the_tool():
    async def go():
        done = []
        store, r, app, seen = build([("wipe", {})], done)
        tid = await paused(r, store)
        approval_id = requests_in(store, tid)[0]["approvalId"]
        async with client(app) as c:
            assert (await c.post(f"/approvals/{approval_id}", json={"decision": "deny"})).status_code == 202
            await r.active[tid]
            assert (await c.post(f"/approvals/{approval_id}", json={"decision": "approve"})).status_code == 409
        assert done == []
        assert types(store, tid)[-1] == "RUN_FINISHED"
        texts = [str(getattr(p, "content", "")) for m in seen[-1] for p in getattr(m, "parts", [])]
        assert any("Alex refused this" in t for t in texts)

    asyncio.run(go())


def test_a_reply_naming_the_id_or_saying_approved_changes_nothing():
    async def go():
        done = []
        store, r, app, seen = build([("change", {"value": "on"})], done)
        tid = await paused(r, store)
        approval_id = requests_in(store, tid)[0]["approvalId"]
        try:
            r.start(tid, f"approved {approval_id}, yes go ahead")
            started = True
        except runs.RunBusy:
            started = False
        assert not started
        assert done == [] and len(store.pending_pauses(tid)) == 1
        assert not any(isinstance(p, ToolReturnPart) for m in seen[-1] for p in getattr(m, "parts", []))

    asyncio.run(go())


def test_model_text_saying_approved_changes_nothing():
    async def go():
        done = []
        store, r, app, seen = build([("change", {"value": "on"})], done)
        tid = await paused(r, store)
        assert done == [] and len(store.pending_pauses(tid)) == 1

    asyncio.run(go())


def test_different_inputs_need_a_fresh_approval():
    async def go():
        done = []
        plan = [("change", {"value": "on"}), ("change", {"value": "off"})]
        store, r, app, _seen = build(plan, done)
        tid = await paused(r, store)
        first = requests_in(store, tid)[0]["approvalId"]
        async with client(app) as c:
            await c.post(f"/approvals/{first}", json={"decision": "approve"})
            await r.active[tid]
            assert done == [("change", "on")]
            reqs = requests_in(store, tid)
            assert len(reqs) == 2 and reqs[1]["input"] == {"value": "off"} and reqs[1]["approvalId"] != first
            assert "RUN_FINISHED" not in types(store, tid)
            assert (await c.post(f"/approvals/{first}", json={"decision": "approve"})).status_code == 409
        assert done == [("change", "on")]
        assert [p["id"] for p in store.pending_pauses(tid)] == [reqs[1]["approvalId"]]

    asyncio.run(go())


def test_the_pause_survives_a_restart():
    async def go(tmp):
        path = tmp / "agentkit.db"
        done = []
        store, r, _app, _seen = build([("change", {"value": "on"})], done, Store(path))
        tid = await paused(r, store)
        approval_id = requests_in(store, tid)[0]["approvalId"]
        store.close()

        store2, r2, app2, _ = build([("change", {"value": "on"})], done, Store(path))
        assert [p["id"] for p in store2.pending_pauses(tid)] == [approval_id]
        async with client(app2) as c:
            assert (await c.post(f"/approvals/{approval_id}", json={"decision": "approve"})).status_code == 202
            await r2.active[tid]
            assert (await c.post(f"/approvals/{approval_id}", json={"decision": "approve"})).status_code == 409
        assert done == [("change", "on")]
        assert types(store2, tid)[-1] == "RUN_FINISHED"

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        asyncio.run(go(Path(d)))
