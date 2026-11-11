"""Proof: cancelling a new-project flow at three steps ends the flow, creates nothing and calls no more tools."""
import asyncio

import pytest

from fake_phoenix import FakePhoenix
from test_approvals import client
from test_browser_tools import customs
from test_proof_flow_reload import flow_cards
from test_proof_new_project import CHOICES, answer_choices, ask, build, flow, posts, start

SETUP = [flow("active", 1, "Name"), ("project-check-name", {"name": "gamma"}), ("library-profiles", {}),
         ("library-services", {})]


def tool_names(seen):
    """The names of every tool the model called, over the whole run."""
    return [p.tool_name for m in seen[-1] for p in getattr(m, "parts", []) if hasattr(p, "tool_name")
            and type(p).__name__ == "ToolCallPart"]


@pytest.mark.parametrize("answered", [0, 1, 2])
def test_proof_flow_cancel(answered):
    async def go():
        fake = FakePhoenix()
        asks = [ask(q, o) for q, o in CHOICES]
        plan = SETUP + asks[:answered + 1] + [flow("cancelled", answered + 2, "Cancelled")]
        store, r, app, seen = build(plan, fake)
        tid = await start(r, store)
        await answer_choices(store, r, app, tid, answered)
        n = len(customs(store, tid, "browser_tool"))
        assert n == answered + 1
        async with client(app) as c:
            resp = await c.post(f"/browser-results/{customs(store, tid, 'browser_tool')[-1]['browserId']}",
                                json={"result": {"status": "cancelled"}})
            assert resp.status_code == 202
            await r.active[tid]
        assert flow_cards(store, tid)[-1]["status"] == "cancelled"
        assert fake.created == [] and posts(fake) == []
        called = tool_names(seen)
        assert called[-1] == "flow" and "project-create" not in called
        assert len(customs(store, tid, "browser_tool")) == answered + 1

    asyncio.run(go())
