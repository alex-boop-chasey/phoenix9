"""Tests that a browser tool's declared result fields are the only thing kept from the browser's answer."""
import asyncio
import json
import tempfile
from pathlib import Path

from pydantic import BaseModel

from agentkit import llm, runs
from agentkit.pack import BrowserTool, Pack
from agentkit.store import Store
from test_browser_tools import client, customs, model_text, script
from starlette.applications import Starlette
from starlette.routing import Route

SECRET = "sk-test-VALUE-12345-zzz"


class Nothing(BaseModel):
    name: str


def test_extra_fields_leave_no_trace():
    async def go():
        db = Path(tempfile.mkdtemp()) / "t.db"
        store, seen = Store(str(db)), []
        pack = Pack(name="t", instructions="", browser_tools=(
            BrowserTool("ask", "Ask.", Nothing, result_fields={"status": ("saved", "cancelled")}),))
        r = runs.Runs(store, llm.build_pack_agent(script([("ask", {"name": "k"})], seen), pack), pack)
        app = Starlette(routes=[Route("/browser-results/{id}", runs.browser_route(r, lambda _q: False), methods=["POST"])])
        tid = store.create_thread()["id"]
        r.start(tid, "go")
        await r.active[tid]
        (ask,) = customs(store, tid, "browser_tool")
        body = {"result": {"status": "saved", "value": SECRET, "extra": SECRET}}
        async with client(app) as c:
            assert (await c.post(f"/browser-results/{ask['browserId']}", json=body)).status_code == 202
        await r.active[tid]
        log = json.dumps([e for _, e in store.events_after(tid)])
        assert SECRET not in log
        assert SECRET not in model_text(seen)
        assert "saved" in model_text(seen)
        store.close() if hasattr(store, "close") else None
        raw = b"".join(p.read_bytes() for p in db.parent.iterdir() if p.name.startswith("t.db"))
        assert SECRET.encode() not in raw
    asyncio.run(go())


def test_limit_result_rules():
    f = {"status": ("saved", "cancelled")}
    assert runs.limit_result(f, {"status": "saved", "x": 1}) == {"status": "saved"}
    assert runs.limit_result(f, {"status": SECRET}) == {}
    assert runs.limit_result(f, {"status": ["saved"]}) == {}
    assert runs.limit_result(f, "saved") == {}
    assert runs.limit_result(None, {"a": 1}) == {"a": 1}
