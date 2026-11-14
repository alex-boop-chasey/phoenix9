"""Tests that runs live on the server, not on a stream connection."""
import asyncio

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient
from pydantic_ai.models.function import FunctionModel

from agentkit import llm, runs
from agentkit.store import Store


def make(gate=None):
    async def say(messages, info):
        if gate is not None:
            await gate.wait()
        yield "Hello "
        yield "Alex"

    store = Store(":memory:")
    agent = llm.build_agent(FunctionModel(stream_function=say))
    return store, runs.Runs(store, agent)


def texts(store, tid):
    return "".join(e["delta"] for _, e in store.events_after(tid) if e["type"] == "TEXT_MESSAGE_CONTENT")


def test_run_finishes_with_no_stream_reader_and_reply_is_in_the_log():
    async def go():
        store, r = make()
        tid = store.create_thread()["id"]
        run_id = r.start(tid, "hi")
        assert run_id and r.running(tid)
        await r.active[tid]
        return store, tid

    store, tid = asyncio.run(go())
    types = [e["type"] for _, e in store.events_after(tid)]
    assert types[0] == "RUN_STARTED" and types[-1] == "RUN_FINISHED"
    assert texts(store, tid) == "Hello Alex"


def test_second_start_while_running_is_queued_and_a_sixth_waiting_is_refused():
    async def go():
        gate = asyncio.Event()
        store, r = make(gate)
        tid = store.create_thread()["id"]
        r.start(tid, "one")
        queued = [r.start(tid, f"q{n}")["queued"] for n in range(runs.QUEUE_LIMIT)]
        try:
            r.start(tid, "two")
            refused = False
        except runs.RunBusy as e:
            refused = "waiting" in str(e)
        gate.set()
        while (task := r.active.get(tid)) is not None:
            await task
            await asyncio.sleep(0)
        r.start(tid, "three")
        await r.active[tid]
        return all(queued) and refused

    assert asyncio.run(go())


def test_route_answers_with_run_id_and_queues_when_busy():
    gate_box = {}

    async def go():
        gate_box["g"] = asyncio.Event()
        return make(gate_box["g"])

    loop = asyncio.new_event_loop()
    store, r = loop.run_until_complete(go())
    tid = store.create_thread()["id"]
    route = runs.start_route(r, lambda req: False)
    app = Starlette(routes=[Route("/threads/{id}/runs", route, methods=["POST"])])
    with TestClient(app) as client:
        first = client.post(f"/threads/{tid}/runs", json={"message": "hi"})
        assert first.status_code == 202 and first.json()["run_id"]
        second = client.post(f"/threads/{tid}/runs", json={"message": "again"})
        assert second.status_code == 202 and second.json()["queued"] is True and second.json()["run_id"]
        for n in range(runs.QUEUE_LIMIT - 1):
            assert client.post(f"/threads/{tid}/runs", json={"message": f"more {n}"}).status_code == 202
        full = client.post(f"/threads/{tid}/runs", json={"message": "too many"})
        assert full.status_code == 409 and full.json()["error"] == runs.QUEUE_FULL
