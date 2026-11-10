"""Tests that a destructive tool needs the exact typed text before it runs, decided by the server alone."""
import asyncio

import httpx
import pytest
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.routing import Route

from agentkit import llm, runs
from agentkit.pack import Pack, PackError, ServerTool, check_pack
from agentkit.store import Store
from test_approvals import script, types, requests_in, paused


class Target(BaseModel):
    name: str


def build(done):
    """A store, a Runs and an app for a pack whose one destructive tool is confirmed by its `name` input."""

    def remove(name):
        done.append(name)
        return {"removed": name}

    pack = Pack(name="t", instructions="", server_tools=(
        ServerTool("remove", "Remove.", Target, "destructive", remove, confirm_field="name"),))
    store = Store(":memory:")
    r = runs.Runs(store, llm.build_pack_agent(script([("remove", {"name": "alpha"})], []), pack), check_pack(pack))
    app = Starlette(routes=[Route("/approvals/{id}", runs.approval_route(r, lambda _q: False), methods=["POST"])])
    return store, r, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def test_request_carries_the_text_to_type():
    async def go():
        done = []
        store, r, _c = build(done)
        tid = await paused(r, store)
        (req,) = requests_in(store, tid)
        assert req["confirm_text"] == "alpha" and done == []
        assert req["description"] == "Remove."

    asyncio.run(go())


def test_wrong_or_missing_text_is_refused_and_the_call_stays_paused():
    async def go():
        done = []
        store, r, c = build(done)
        tid = await paused(r, store)
        aid = requests_in(store, tid)[0]["approvalId"]
        for body in ({"decision": "approve"}, {"decision": "approve", "confirm": "beta"},
                     {"decision": "approve", "confirm": 5}):
            reply = await c.post(f"/approvals/{aid}", json=body)
            assert reply.status_code == 400 and "confirmation" in reply.json()["error"]
        assert done == [] and len(store.pending_pauses(tid)) == 1
        assert "RUN_FINISHED" not in types(store, tid)

    asyncio.run(go())


def test_right_text_runs_it_once():
    async def go():
        done = []
        store, r, c = build(done)
        tid = await paused(r, store)
        aid = requests_in(store, tid)[0]["approvalId"]
        assert (await c.post(f"/approvals/{aid}", json={"decision": "approve", "confirm": "alpha"})).status_code == 202
        await asyncio.gather(*r.active.values())
        assert done == ["alpha"] and types(store, tid)[-1] == "RUN_FINISHED"
        again = await c.post(f"/approvals/{aid}", json={"decision": "approve", "confirm": "alpha"})
        assert again.status_code == 409 and done == ["alpha"]

    asyncio.run(go())


def test_deny_needs_no_text():
    async def go():
        done = []
        store, r, c = build(done)
        tid = await paused(r, store)
        aid = requests_in(store, tid)[0]["approvalId"]
        assert (await c.post(f"/approvals/{aid}", json={"decision": "deny"})).status_code == 202
        await asyncio.gather(*r.active.values())
        assert done == []

    asyncio.run(go())


def test_destructive_tool_without_confirm_field_is_refused_at_load():
    pack = Pack(name="t", instructions="", server_tools=(
        ServerTool("remove", "Remove.", Target, "destructive", lambda name: {}),))
    with pytest.raises(PackError, match="confirm_field"):
        check_pack(pack)
