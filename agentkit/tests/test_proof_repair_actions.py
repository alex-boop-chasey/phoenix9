"""Proof: each repair tool pauses for approval and posts once after Approve; Deny, a second repair and an unsafe refusal change nothing."""
import asyncio

import httpx

from agentkit import llm, runs
from agentkit.packs.phoenix import build_pack
from agentkit.store import Store
from fake_phoenix import FAILED_RUN, FakePhoenix
from test_approvals import client, paused, requests_in, script, types

ARGS = {"project": "beta", "run_id": FAILED_RUN}
REPAIRS = {
    "repair-rerun-step": ({**ARGS, "task": 2}, "rerun"),
    "repair-rewrite-checks": ({**ARGS, "task": 2, "why": "the check tested the wrong page"}, "rewrite-checks"),
    "repair-skip-task": ({**ARGS, "task": 2, "why": "not needed"}, "skip"),
    "repair-resume-from": ({**ARGS, "task": 2}, "resume"),
    "repair-restart-preset": ({**ARGS, "preset": "careful"}, "restart"),
    "repair-raise-max-tries": ({**ARGS, "tries": 3}, "max-tries"),
}
UNSAFE = "Refused: this repair would loosen a safety check, so it was not done."


class Unsafe(FakePhoenix):
    """A fake Phoenix that refuses every repair as unsafe (a conflict, as the real one does)."""

    def failed_run(self, request, what, query):
        """Refuse repairs; answer everything else as usual."""
        if request.method == "POST":
            return httpx.Response(409, json={"error": UNSAFE})
        return super().failed_run(request, what, query)


def build(plan, fake):
    """A store, a Runs on the real pack with the scripted model, an approval app and what the model saw."""
    store, seen = Store(":memory:"), []
    pack = build_pack(fake.client())
    r = runs.Runs(store, llm.build_pack_agent(script(plan, seen), pack), pack)
    from starlette.applications import Starlette
    from starlette.routing import Route
    app = Starlette(routes=[Route("/approvals/{id}", runs.approval_route(r, lambda _q: False), methods=["POST"])])
    return store, r, app, seen


def posts(fake):
    """The POST requests that reached the fake Phoenix."""
    return [q for q in fake.requests if q.method == "POST"]


def test_each_repair_pauses_then_posts_exactly_once_after_approve():
    async def go():
        for tool, (args, route) in REPAIRS.items():
            fake = FakePhoenix()
            store, r, app, _seen = build([(tool, args)], fake)
            tid = await paused(r, store)
            assert posts(fake) == [] and types(store, tid)[-1] != "RUN_FINISHED"
            (req,) = requests_in(store, tid)
            assert req["toolName"] == tool and req["input"] == args
            async with client(app) as c:
                assert (await c.post(f"/approvals/{req['approvalId']}", json={"decision": "approve"})).status_code == 202
                await r.active[tid]
            (sent,) = posts(fake)
            assert sent.url.path == f"/api/runs/beta/{FAILED_RUN}/repair/{route}"
            assert types(store, tid)[-1] == "RUN_FINISHED"

    asyncio.run(go())


def test_deny_sends_nothing_to_phoenix():
    async def go():
        for tool, (args, _route) in REPAIRS.items():
            fake = FakePhoenix()
            store, r, app, _seen = build([(tool, args)], fake)
            tid = await paused(r, store)
            (req,) = requests_in(store, tid)
            async with client(app) as c:
                assert (await c.post(f"/approvals/{req['approvalId']}", json={"decision": "deny"})).status_code == 202
                await r.active[tid]
            assert fake.requests == [] and types(store, tid)[-1] == "RUN_FINISHED"

    asyncio.run(go())


def test_second_repair_on_the_same_run_is_refused_while_one_is_pending():
    async def go():
        fake = FakePhoenix()
        store, r, _app, seen = build([("repair-skip-task", REPAIRS["repair-skip-task"][0])], fake)
        first = await paused(r, store)
        assert len(requests_in(store, first)) == 1
        fake2 = FakePhoenix()
        pack = build_pack(fake2.client())
        seen2 = []
        r2 = runs.Runs(store, llm.build_pack_agent(
            script([("repair-raise-max-tries", REPAIRS["repair-raise-max-tries"][0])], seen2), pack), pack)
        second = await paused(r2, store)
        await asyncio.sleep(0.05)
        assert requests_in(store, second) == [] and len(store.pending_pauses()) == 1
        assert runs.REPAIR_BUSY in str(seen2) and fake.requests == [] and fake2.requests == []

    asyncio.run(go())


def test_unsafe_refusal_reaches_the_model_and_nothing_else_is_sent():
    async def go():
        fake = Unsafe()
        tool, (args, _route) = "repair-rewrite-checks", REPAIRS["repair-rewrite-checks"]
        store, r, app, seen = build([(tool, args)], fake)
        tid = await paused(r, store)
        (req,) = requests_in(store, tid)
        async with client(app) as c:
            await c.post(f"/approvals/{req['approvalId']}", json={"decision": "approve"})
            await r.active[tid]
        assert len(fake.requests) == 1 and fake.requests[0].method == "POST"
        assert UNSAFE in str(seen[-1]) and types(store, tid)[-1] == "RUN_FINISHED"

    asyncio.run(go())
