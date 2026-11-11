"""Proof: the hotfix and build-start flows end to end with scripted model replies and the fake Phoenix."""
import asyncio

from fake_phoenix import BAD_OVERRIDES_ERROR, FakePhoenix
from test_approvals import client, requests_in, types
from test_browser_tools import customs
from test_proof_new_project import build, flow, posts, start

BRIEF = "Make the Buy button blue on the cart page."


def cards(store, tid, component):
    """The data of the cards of this component."""
    return [c["data"] for c in customs(store, tid, "component") if c["component"] == component]


def hotfix_plan():
    """The scripted calls up to and including the hotfix-start call."""
    return [flow("active", 1, "Describe"), ("hotfix-start", {"name": "beta", "brief": BRIEF})]


def test_hotfix_approve_sends_one_request_with_the_brief():
    async def go():
        fake = FakePhoenix()
        store, r, app, _seen = build(hotfix_plan() + [flow("done", 3, "Started")], fake)
        tid = await start(r, store)
        assert posts(fake) == [] and fake.hotfixes == []
        (req,) = requests_in(store, tid)
        assert req["toolName"] == "hotfix-start" and req["input"]["brief"] == BRIEF
        assert cards(store, tid, "FlowCard")[0]["flow"] == "new-project"
        async with client(app) as c:
            assert (await c.post(f"/approvals/{req['approvalId']}", json={"decision": "approve"})).status_code == 202
            await r.active[tid]
        assert fake.hotfixes == [{"brief": BRIEF}] and len(posts(fake)) == 1
        assert types(store, tid)[-1] == "RUN_FINISHED"

    asyncio.run(go())


def test_hotfix_deny_sends_nothing():
    async def go():
        fake = FakePhoenix()
        store, r, app, _seen = build(hotfix_plan(), fake)
        tid = await start(r, store)
        (req,) = requests_in(store, tid)
        async with client(app) as c:
            await c.post(f"/approvals/{req['approvalId']}", json={"decision": "deny"})
            await r.active[tid]
        assert posts(fake) == [] and fake.hotfixes == []

    asyncio.run(go())


def test_hotfix_refusal_is_passed_on_in_plain_words():
    async def go():
        fake = FakePhoenix()
        fake.hotfix_busy = True
        store, r, app, seen = build(hotfix_plan(), fake)
        tid = await start(r, store)
        (req,) = requests_in(store, tid)
        async with client(app) as c:
            await c.post(f"/approvals/{req['approvalId']}", json={"decision": "approve"})
            await r.active[tid]
        assert len(fake.hotfixes) == 1
        assert "already going" in str(seen[-1])
        assert types(store, tid)[-1] == "RUN_FINISHED"

    asyncio.run(go())


def test_build_start_reads_specs_and_plan_then_pauses_then_starts_once():
    async def go():
        fake = FakePhoenix()
        plan = [flow("active", 1, "Pick a spec"), ("project-specs", {"name": "beta"}),
                ("build-plan", {"name": "beta", "overrides": {"bad": True}}),
                ("build-plan", {"name": "beta"}),
                ("build-start", {"name": "beta", "spec": "specs/cart.md"})]
        store, r, app, _seen = build(plan, fake)
        tid = await start(r, store)
        (specs,) = cards(store, tid, "SpecsCard")
        assert [x["name"] for x in specs["specs"]] == ["specs/cart.md", "plans/ideas.md"]
        plan_cards = cards(store, tid, "PlanCheckCard")
        assert len(plan_cards) == 2 and plan_cards[0]["errors"] == [BAD_OVERRIDES_ERROR] \
            and plan_cards[0]["ok"] is False and plan_cards[1]["ok"] is True
        assert fake.starts == [] and len(fake.plans) == 2
        (req,) = requests_in(store, tid)
        assert req["toolName"] == "build-start"
        async with client(app) as c:
            await c.post(f"/approvals/{req['approvalId']}", json={"decision": "approve"})
            await r.active[tid]
        assert fake.starts == [{"spec": "specs/cart.md"}]
        runcards = cards(store, tid, "run_card")
        assert runcards and runcards[-1]["build"]["run_id"] == "20261111-2"
        assert types(store, tid)[-1] == "RUN_FINISHED"

    asyncio.run(go())
