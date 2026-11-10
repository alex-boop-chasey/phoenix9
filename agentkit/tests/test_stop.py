"""Tests that stop cancels a run at once, logs it, closes pauses and lets a new run start."""
import asyncio
import time

import httpx
from pydantic_ai.models.function import FunctionModel
from starlette.applications import Starlette
from starlette.routing import Route

from agentkit import llm, runs
from agentkit.store import Store


def build(state):
    """A Runs whose model waits forever mid-stream on the first call, then answers normally."""

    async def reply(messages, info):
        state["calls"] = state.get("calls", 0) + 1
        if state["calls"] == 1:
            yield "Thinking "
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                state["cancelled"] = True
                raise
        yield "Done."

    store = Store(":memory:")
    r = runs.Runs(store, llm.build_agent(FunctionModel(stream_function=reply)))
    app = Starlette(routes=[
        Route("/threads/{id}/stop", runs.stop_route(r, lambda _q: False), methods=["POST"])])
    return store, r, app


def names(store, tid):
    """Event types, with custom events shown by name."""
    return [e.get("name", e["type"]) for _, e in store.events_after(tid)]


def test_stop_cancels_the_model_call_logs_it_and_a_new_run_can_start():
    async def go():
        state = {}
        store, r, app = build(state)
        tid = store.create_thread()["id"]
        r.start(tid, "hi")
        for _ in range(200):
            if state.get("calls"):
                break
            await asyncio.sleep(0.01)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            began = time.monotonic()
            resp = await c.post(f"/threads/{tid}/stop")
            took = time.monotonic() - began
            again = await c.post(f"/threads/{tid}/stop")
        assert resp.json()["stopped"] is True and took < 1
        assert state.get("cancelled") and not r.running(tid)
        assert again.json()["stopped"] is False and "nothing" in again.json()["message"].lower()
        log = names(store, tid)
        assert log[-2:] == ["run_stopped", "RUN_FINISHED"]
        r.start(tid, "again")
        await r.active[tid]
        assert names(store, tid)[-1] == "RUN_FINISHED"
        assert "Done." in "".join(
            e.get("delta", "") for _, e in store.events_after(tid) if e["type"] == "TEXT_MESSAGE_CONTENT")

    asyncio.run(go())


def test_stop_closes_a_pending_pause_as_stopped():
    async def go():
        store = Store(":memory:")
        r = runs.Runs(store, llm.build_agent(FunctionModel(stream_function=lambda m, i: None)))
        tid = store.create_thread()["id"]
        pid = store.create_pause(tid, "approval", "change", {})
        assert await r.stop(tid) is True
        assert store.get_pause(pid)["state"] == "stopped" and not store.pending_pauses(tid)
        assert names(store, tid)[-2:] == ["run_stopped", "RUN_FINISHED"]

    asyncio.run(go())
