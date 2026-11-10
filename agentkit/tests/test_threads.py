"""Tests for listing, reading and starting threads."""
import asyncio
import time

import httpx
from pydantic_ai.models.test import TestModel
from starlette.applications import Starlette
from starlette.routing import Route

from agentkit import llm, runs
from agentkit.store import Store


def build():
    """A store, a Runs with a scripted model, and an app with the three thread routes."""
    store = Store(":memory:")
    r = runs.Runs(store, llm.build_agent(TestModel(custom_output_text="Hello back")))
    no = lambda _req: False
    app = Starlette(routes=[
        Route("/threads", runs.list_route(r, no), methods=["GET"]),
        Route("/threads", runs.new_route(r, no), methods=["POST"]),
        Route("/threads/{id}", runs.read_route(r, no), methods=["GET"]),
    ])
    return store, r, app


def client(app):
    """An async client talking straight to the app."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def test_list_is_newest_used_first_and_new_keeps_old():
    async def go():
        store, r, app = build()
        async with client(app) as c:
            a = (await c.post("/threads")).json()["id"]
            time.sleep(0.01)
            b = (await c.post("/threads")).json()["id"]
            time.sleep(0.01)
            r.start(a, "x" * 100)
            await r.active[a]
            ids = [t["id"] for t in (await c.get("/threads")).json()["threads"]]
            assert ids == [a, b]
            await c.post("/threads")
            listed = (await c.get("/threads")).json()["threads"]
            assert len(listed) == 3 and {a, b} <= {t["id"] for t in listed}
            first = next(t for t in listed if t["id"] == a)
            assert first["title"] == "x" * 60 and "created" in first and "last_used" in first

    asyncio.run(go())


def test_read_shows_whole_conversation():
    async def go():
        store, r, app = build()
        async with client(app) as c:
            tid = (await c.post("/threads")).json()["id"]
            r.start(tid, "Hi there")
            await r.active[tid]
            body = (await c.get(f"/threads/{tid}")).json()
            assert body["thread"]["title"] == "Hi there"
            events = [e["event"] for e in body["events"]]
            assert [e["value"]["text"] for e in events if e.get("name") == "user_message"] == ["Hi there"]
            said = "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")
            assert said == "Hello back"
            assert events[-1]["type"] == "RUN_FINISHED"

    asyncio.run(go())


def test_unknown_thread_is_404_with_plain_message():
    async def go():
        _, _, app = build()
        async with client(app) as c:
            resp = await c.get("/threads/nope")
            assert resp.status_code == 404 and resp.json()["error"] == "no such thread"

    asyncio.run(go())
