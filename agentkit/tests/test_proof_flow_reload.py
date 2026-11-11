"""Proof: after a reload the newest flow card is the saved step, and a new run continues from the saved history."""
import asyncio

import httpx
from starlette.applications import Starlette
from starlette.routing import Route

from agentkit import llm, runs
from agentkit.packs.phoenix import build_pack
from fake_phoenix import FakePhoenix
from test_approvals import client, script
from test_browser_tools import customs
from test_proof_new_project import ask, flow, start
from agentkit.store import Store

FACTS = {"name": "gamma", "type": "Node and TypeScript"}


def flow_cards(store, tid):
    """The data of every flow card in the log, oldest first."""
    return [c["data"] for c in customs(store, tid, "component") if c["component"] == "FlowCard"]


def step2():
    """A scripted flow call for step 2 with its facts."""
    return ("flow", {"flow": "new-project", "status": "active", "step": 2, "steps": 6, "label": "Pick a type",
                     "values": FACTS})


def test_proof_flow_reload(tmp_path):
    async def go():
        fake = FakePhoenix()
        pack = build_pack(fake.client())
        store = Store(tmp_path / "agent.db")
        plan = [flow("active", 1, "Name"), ask("Which type of project?", ["Node and TypeScript", "Python"]), step2()]
        r = runs.Runs(store, llm.build_pack_agent(script(plan, []), pack), pack)
        app = Starlette(routes=[Route("/browser-results/{id}", runs.browser_route(r, lambda _q: False), methods=["POST"]),
                                Route("/threads/{id}", runs.read_route(r, lambda _q: False))])
        tid = await start(r, store)
        async with client(app) as c:
            await c.post(f"/browser-results/{customs(store, tid, 'browser_tool')[-1]['browserId']}",
                         json={"result": {"status": "picked", "picked": [0]}})
            await r.active[tid]

        # Reload: a fresh store and Runs on the same file, and the same replay GET /threads/<id> serves.
        store2 = Store(tmp_path / "agent.db")
        plan2 = plan + [("flow", {"flow": "new-project", "status": "active", "step": 4, "steps": 6, "label": "x"}),
                        ("flow", {"flow": "new-project", "status": "active", "step": 3, "steps": 6,
                                  "label": "Pick services", "values": FACTS})]
        r2 = runs.Runs(store2, llm.build_pack_agent(script(plan2, []), pack), pack)
        app2 = Starlette(routes=[Route("/threads/{id}", runs.read_route(r2, lambda _q: False))])
        async with client(app2) as c:
            body = (await c.get(f"/threads/{tid}")).json()
        shown = [e["event"]["value"]["data"] for e in body["events"]
                 if e["event"]["type"] == "CUSTOM" and e["event"]["name"] == "component"
                 and e["event"]["value"]["component"] == "FlowCard"]
        assert shown[-1]["step"] == 2 and shown[-1]["values"] == FACTS and shown[-1]["status"] == "active"
        assert body["running"] is False

        r2.start(tid, "carry on")
        await r2.active[tid]
        newest = flow_cards(store2, tid)[-1]
        assert newest["step"] == 3 and newest["values"] == FACTS

    asyncio.run(go())
