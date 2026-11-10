"""Tests for the ask_for_key browser tool: it exists, takes no value, and only `status` comes back."""
import asyncio

import pytest
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.routing import Route

from agentkit import llm, runs
from agentkit.packs.phoenix import build_pack
from agentkit.store import Store
from test_browser_tools import client, customs, model_text, script

SECRET = "sk-test-VALUE-12345-zzz"


def tool():
    """The ask_for_key tool from a fresh Phoenix pack."""
    from fake_phoenix import FakePhoenix  # noqa: F401
    pack = build_pack(FakePhoenix().client())
    return pack, next(t for t in pack.browser_tools if t.name == "ask_for_key")


def test_tool_exists_without_value_field():
    pack, t = tool()
    assert set(t.inputs.model_fields) == {"project", "name", "why"}
    assert pack.components["ask_for_key"] == "KeyInputCard"
    assert t.result_fields == {"status": ("saved", "cancelled")}
    assert "masked" in t.description
    with pytest.raises(ValidationError):
        t.inputs(project="p", name="bad name", why="x")


def test_result_value_never_reaches_model():
    async def go():
        pack, _ = tool()
        store, seen = Store(":memory:"), []
        r = runs.Runs(store, llm.build_pack_agent(
            script([("ask_for_key", {"project": "p", "name": "API_KEY", "why": "needed"})], seen), pack), pack)
        app = Starlette(routes=[Route("/browser-results/{id}", runs.browser_route(r, lambda _q: False), methods=["POST"])])
        tid = store.create_thread()["id"]
        r.start(tid, "set key")
        await r.active[tid]
        (ask,) = customs(store, tid, "browser_tool")
        async with client(app) as c:
            await c.post(f"/browser-results/{ask['browserId']}", json={"result": {"status": "saved", "value": SECRET}})
        await r.active[tid]
        text = model_text(seen)
        assert SECRET not in text and "saved" in text
    asyncio.run(go())
