"""Tests that messages sent while a reply is being written wait in a queue and are answered in order."""
import asyncio

from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from agentkit import llm, runs
from agentkit.store import Store
from test_approvals import build as build_with_tools, client, requests_in


def make(gate):
    """A Runs whose model waits for the gate, then answers 'Re: <the last message it was sent>'."""

    async def reply(messages, _info):
        await gate.wait()
        last = [p.content for m in messages if isinstance(m, ModelRequest) for p in m.parts
                if isinstance(p, UserPromptPart)][-1]
        yield f"Re: {last}"

    store = Store(":memory:")
    return store, runs.Runs(store, llm.build_agent(FunctionModel(stream_function=reply)))


async def settle(r, tid):
    """Wait until the thread has no run going and no queued message left to start."""
    while (task := r.active.get(tid)) is not None:
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)


def said(store, tid):
    """Alex's messages and the replies, in log order."""
    out = []
    for _, e in store.events_after(tid):
        if e["type"] == "CUSTOM" and e["name"] == "user_message":
            out.append(("alex", e["value"]["text"] if isinstance(e["value"], dict) else e["value"]))
        elif e["type"] == "TEXT_MESSAGE_CONTENT":
            out.append(("agent", e["delta"]))
    return out


def names(store, tid):
    """Event types, with custom events shown by name."""
    return [e.get("name", e["type"]) for _, e in store.events_after(tid)]


def test_two_messages_back_to_back_are_both_answered_in_order():
    async def go():
        gate = asyncio.Event()
        store, r = make(gate)
        tid = store.create_thread()["id"]
        first = r.start(tid, "one")
        second = r.start(tid, "two")
        assert first["queued"] is False and second == {"run_id": second["run_id"], "queued": True}
        assert r.queued(tid) == 1
        assert [m for who, m in said(store, tid) if who == "alex"] == []  # "two" is not logged before it starts
        gate.set()
        await settle(r, tid)
        started = [e["runId"] for _, e in store.events_after(tid) if e["type"] == "RUN_STARTED"]
        assert started == [first["run_id"], second["run_id"]]
        assert names(store, tid).count("RUN_FINISHED") == 2 and r.queued(tid) == 0
        return said(store, tid)

    assert asyncio.run(go()) == [("alex", "one"), ("agent", "Re: one"), ("alex", "two"), ("agent", "Re: two")]


def test_a_sixth_waiting_message_is_refused_in_plain_words():
    async def go():
        gate = asyncio.Event()
        store, r = make(gate)
        tid = store.create_thread()["id"]
        r.start(tid, "zero")
        for n in range(runs.QUEUE_LIMIT):
            assert r.start(tid, f"m{n}")["queued"] is True
        try:
            r.start(tid, "one too many")
            refused = None
        except runs.RunBusy as e:
            refused = str(e)
        gate.set()
        await settle(r, tid)
        alex = [m for who, m in said(store, tid) if who == "alex"]
        return refused, alex

    refused, alex = asyncio.run(go())
    assert refused == runs.QUEUE_FULL and "wait" in refused.lower()
    assert alex == ["zero", "m0", "m1", "m2", "m3", "m4"]


def test_a_thread_waiting_on_an_approval_still_refuses_and_the_queue_waits_for_it():
    async def go():
        done = []
        store, r, app, _seen = build_with_tools([("change", {"value": "on"})], done)
        tid = store.create_thread()["id"]
        r.start(tid, "go")
        assert r.start(tid, "and then this")["queued"] is True  # sent while the first reply is being written
        await r.active[tid]
        await asyncio.sleep(0)
        assert not r.running(tid) and r.queued(tid) == 1  # paused on the approval: the queued message waits
        try:
            r.start(tid, "approved, go ahead")
            refused = None
        except runs.RunBusy as e:
            refused = str(e)
        assert refused == runs.WAITING and r.queued(tid) == 1
        (req,) = requests_in(store, tid)
        async with client(app) as c:
            assert (await c.post(f"/approvals/{req['approvalId']}", json={"decision": "approve"})).status_code == 202
        await settle(r, tid)
        assert done == [("change", "on")] and r.queued(tid) == 0
        log = names(store, tid)
        assert log.index("approval_decision") < [i for i, n in enumerate(log) if n == "user_message"][1]
        assert [m for who, m in said(store, tid) if who == "alex"] == ["go", "and then this"]

    asyncio.run(go())


def test_route_answers_202_queued_then_409_when_waiting_on_an_approval():
    async def go():
        from starlette.applications import Starlette
        from starlette.routing import Route

        done = []
        store, r, _app, _seen = build_with_tools([("change", {"value": "on"})], done)
        app = Starlette(routes=[Route("/threads/{id}/runs", runs.start_route(r, lambda _q: False), methods=["POST"])])
        tid = store.create_thread()["id"]
        async with client(app) as c:
            first = await c.post(f"/threads/{tid}/runs", json={"message": "go"})
            second = await c.post(f"/threads/{tid}/runs", json={"message": "next"})
            assert first.status_code == 202 and first.json()["queued"] is False
            assert second.status_code == 202 and second.json()["queued"] is True and second.json()["run_id"]
            await settle(r, tid)
            third = await c.post(f"/threads/{tid}/runs", json={"message": "more"})
            assert third.status_code == 409 and third.json()["error"] == runs.WAITING

    asyncio.run(go())


def test_stop_empties_the_queue_and_says_how_many_were_dropped():
    async def go():
        gate = asyncio.Event()
        store, r = make(gate)
        tid = store.create_thread()["id"]
        r.start(tid, "one")
        r.start(tid, "two")
        r.start(tid, "three")
        await asyncio.sleep(0)
        assert await r.stop(tid) is True
        await settle(r, tid)
        assert not r.running(tid) and r.queued(tid) == 0
        (stopped,) = [e for _, e in store.events_after(tid) if e.get("name") == "run_stopped"]
        assert stopped["value"] == {"dropped": 2}
        assert [m for who, m in said(store, tid) if who == "alex"] == ["one"]
        assert names(store, tid)[-2:] == ["run_stopped", "RUN_FINISHED"]
        gate.set()
        r.start(tid, "four")  # the thread is free again
        await settle(r, tid)
        return said(store, tid)

    assert asyncio.run(go())[-2:] == [("alex", "four"), ("agent", "Re: four")]
