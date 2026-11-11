"""Proof: the new-project flow end to end with scripted model replies and the fake Phoenix."""
import asyncio

from starlette.applications import Starlette
from starlette.routing import Route

from agentkit import llm, runs
from agentkit.packs.phoenix import build_pack
from agentkit.store import Store
from fake_phoenix import JOB_ID, FakePhoenix
from test_approvals import client, requests_in, script, types
from test_browser_tools import customs

CHOICES = [
    ("Which type of project?", ["Node and TypeScript", "Python"]),
    ("Which framework?", ["React", "None"]),
    ("Which services?", ["Stripe payments", "None"]),
]
CREATE = {"name": "gamma", "description": "A test shop", "profile": "node", "source": {"kind": "empty"},
          "new_repo": {"on": True, "owner": "alex"}, "services": ["stripe"]}


def flow(status, step, label):
    """A scripted flow call."""
    return ("flow", {"flow": "new-project", "status": status, "step": step, "steps": 6, "label": label})


def ask(q, options):
    """A scripted ask_choice call."""
    return ("ask_choice", {"question": q, "options": [{"label": o} for o in options]})


def plan_for(name):
    """The scripted calls up to and including the project-create call."""
    return [flow("active", 1, "Name"), ("project-check-name", {"name": name}), ("library-profiles", {}),
            ("library-services", {}), *[ask(q, o) for q, o in CHOICES], ("project-create", CREATE)]


def build(plan, fake):
    """A store, a Runs, an app with approval and browser routes, and what the model saw."""
    store, seen = Store(":memory:"), []
    pack = build_pack(fake.client())
    r = runs.Runs(store, llm.build_pack_agent(script(plan, seen), pack), pack)
    app = Starlette(routes=[
        Route("/approvals/{id}", runs.approval_route(r, lambda _q: False), methods=["POST"]),
        Route("/browser-results/{id}", runs.browser_route(r, lambda _q: False), methods=["POST"])])
    return store, r, app, seen


async def answer_choices(store, r, app, tid, count):
    """Answer `count` choice cards with the first option, one after another."""
    async with client(app) as c:
        for i in range(count):
            asks = customs(store, tid, "browser_tool")
            assert len(asks) == i + 1 and asks[-1]["toolName"] == "ask_choice"
            resp = await c.post(f"/browser-results/{asks[-1]['browserId']}",
                                json={"result": {"status": "picked", "picked": [0]}})
            assert resp.status_code == 202
            await r.active[tid]


async def start(r, store):
    """Start the run and wait until it stops (at a card or the end)."""
    tid = store.create_thread()["id"]
    r.start(tid, "make a new project")
    await r.active[tid]
    return tid


def posts(fake):
    """The POSTs that reached the fake."""
    return [q for q in fake.requests if q.method == "POST"]


def test_full_flow_creates_once_and_follows_the_job():
    async def go():
        fake = FakePhoenix()
        plan = plan_for("gamma") + [("job-status", {"job_id": JOB_ID}), ("job-status", {"job_id": JOB_ID}),
                                    flow("done", 6, "Created")]
        store, r, app, seen = build(plan, fake)
        tid = await start(r, store)
        await answer_choices(store, r, app, tid, 3)
        assert fake.created == [] and posts(fake) == []
        (req,) = requests_in(store, tid)
        assert req["toolName"] == "project-create" and req["input"] == CREATE
        async with client(app) as c:
            assert (await c.post(f"/approvals/{req['approvalId']}", json={"decision": "approve"})).status_code == 202
            await r.active[tid]
        assert fake.created == [CREATE] and "keys" not in fake.created[0]
        assert len(posts(fake)) == 1 and fake.job_calls == 2
        assert types(store, tid)[-1] == "RUN_FINISHED"
        assert "done" in str(seen[-1]) and "Created" in str(seen[-1])

    asyncio.run(go())


def test_deny_sends_nothing():
    async def go():
        fake = FakePhoenix()
        store, r, app, _seen = build(plan_for("gamma"), fake)
        tid = await start(r, store)
        await answer_choices(store, r, app, tid, 3)
        (req,) = requests_in(store, tid)
        async with client(app) as c:
            await c.post(f"/approvals/{req['approvalId']}", json={"decision": "deny"})
            await r.active[tid]
        assert posts(fake) == [] and fake.created == [] and fake.job_calls == 0
        assert types(store, tid)[-1] == "RUN_FINISHED"

    asyncio.run(go())


def test_taken_name_creates_nothing_and_the_agent_asks_again():
    async def go():
        fake = FakePhoenix()
        store, r, _app, seen = build([flow("active", 1, "Name"), ("project-check-name", {"name": "alpha"})], fake)
        tid = await start(r, store)
        assert types(store, tid)[-1] == "RUN_FINISHED"
        assert "already exists" in str(seen[-1]) and posts(fake) == [] and fake.created == []
        assert requests_in(store, tid) == []
        assert any(q.url.path == "/api/projects/check-name" and q.url.params["name"] == "alpha"
                   for q in fake.requests)

    asyncio.run(go())
