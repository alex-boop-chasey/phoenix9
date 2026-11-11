"""Proof: key and .env values never reach the model, the event log, the store or any log line; project-create refuses keys."""
import asyncio
import json
import logging

from starlette.applications import Starlette
from starlette.routing import Route

from agentkit import llm, runs
from agentkit.packs.phoenix import build_pack
from agentkit.store import Store
from fake_phoenix import FakePhoenix
from test_approvals import client, requests_in, script
from test_browser_tools import customs
from test_proof_key import everything_the_model_saw, tool_results

SECRET = "plainvalue-55501928-qx"
PLANTED = {"keys": {"STRIPE_KEY": SECRET}, "value": SECRET, "extra": [SECRET], "name": "API_KEY"}
KEY_ASK = {"project": "beta", "name": "API_KEY", "why": "the build needs it"}
ENV_ASK = {"project": "beta", "why": "to load the settings"}


def app_for(r):
    """An app with the browser-results and approval routes."""
    return Starlette(routes=[
        Route("/browser-results/{id}", runs.browser_route(r, lambda _q: False), methods=["POST"]),
        Route("/approvals/{id}", runs.approval_route(r, lambda _q: False), methods=["POST"])])


def test_secret_is_nowhere_after_key_and_env_cards(tmp_path, caplog):
    async def go():
        caplog.set_level(logging.DEBUG)
        pack = build_pack(FakePhoenix().client())
        store, seen = Store(tmp_path / "agent.db"), []
        plan = [("ask_for_key", KEY_ASK), ("ask_env_file", ENV_ASK)]
        r = runs.Runs(store, llm.build_pack_agent(script(plan, seen), pack), pack)
        app = app_for(r)
        tid = store.create_thread()["id"]
        r.start(tid, "set up keys")
        await r.active[tid]
        answers = [{"status": "saved", **PLANTED}, {"status": "saved", "added": 2, "replaced": 1, "kept": 0, **PLANTED}]
        async with client(app) as c:
            for i, result in enumerate(answers):
                asks = customs(store, tid, "browser_tool")
                assert len(asks) == i + 1 and SECRET not in json.dumps(asks[-1])
                await c.post(f"/browser-results/{asks[-1]['browserId']}", json={"result": result})
                await r.active[tid]
        assert [a["toolName"] for a in customs(store, tid, "browser_tool")] == ["ask_for_key", "ask_env_file"]
        results = tool_results(seen[-1:])
        assert [x["data"] for x in results] == [{"status": "saved"}, {"status": "saved", "added": 2, "replaced": 1, "kept": 0}]
        assert SECRET not in json.dumps(results) and SECRET not in everything_the_model_saw(seen)
        assert SECRET not in json.dumps([e for _, e in store.events_after(tid)])
        assert SECRET not in caplog.text
        store.close()
        for f in tmp_path.rglob("*"):
            if f.is_file():
                assert SECRET.encode() not in f.read_bytes(), f

    asyncio.run(go())


def test_project_create_with_a_keys_field_is_refused_before_sending():
    async def go():
        fake = FakePhoenix()
        pack = build_pack(fake.client())
        store, seen = Store(":memory:"), []
        bad = {"name": "gamma", "profile": "node", "keys": {"API_KEY": SECRET}}
        r = runs.Runs(store, llm.build_pack_agent(script([("project-create", bad)], seen), pack), pack)
        tid = store.create_thread()["id"]
        r.start(tid, "create with a key")
        await r.active[tid]
        await asyncio.sleep(0.05)  # the refused call is answered and the run goes on at once
        await r.active.get(tid, asyncio.sleep(0))
        assert fake.requests == [] and fake.created == [] and requests_in(store, tid) == []
        assert store.pending_pauses() == []
        assert runs.BAD_INPUTS in everything_the_model_saw(seen)
        assert SECRET not in json.dumps([e for _, e in store.events_after(tid)])

    asyncio.run(go())
