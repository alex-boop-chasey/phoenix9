"""Proof: a key value typed in the key card never reaches the agent, its event log, its store file or its results."""
import asyncio
import json

from pydantic_ai.messages import ToolReturnPart
from starlette.applications import Starlette
from starlette.routing import Route

from agentkit import llm, runs
from agentkit.packs.phoenix import build_pack
from agentkit.store import Store
from fake_phoenix import FakePhoenix
from test_browser_tools import client, customs, script

SECRET = "plainvalue-91827364-zq"
ASK = {"project": "p", "name": "API_KEY", "why": "the build needs it"}


def everything_the_model_saw(seen):
    """Every part of every message the model was shown, as text, over all its calls."""
    return " ".join(repr(p) for call in seen for m in call for p in getattr(m, "parts", []))


def tool_results(seen):
    """The content of every tool result the model was shown."""
    return [p.content for call in seen for m in call for p in getattr(m, "parts", [])
            if isinstance(p, ToolReturnPart)]


def test_value_is_nowhere_and_reply_is_only_status(tmp_path):
    async def go():
        pack = build_pack(FakePhoenix().client())
        path = tmp_path / "agent.db"
        store, seen = Store(path), []
        r = runs.Runs(store, llm.build_pack_agent(script([("ask_for_key", ASK)], seen), pack), pack)
        app = Starlette(routes=[Route("/browser-results/{id}", runs.browser_route(r, lambda _q: False),
                                      methods=["POST"])])
        tid = store.create_thread()["id"]
        r.start(tid, "set the key")
        await r.active[tid]
        (ask,) = customs(store, tid, "browser_tool")
        assert ask["toolName"] == "ask_for_key" and SECRET not in json.dumps(ask)
        async with client(app) as c:
            await c.post(f"/browser-results/{ask['browserId']}",
                         json={"result": {"status": "saved", "value": SECRET, "name": "API_KEY"}})
        await r.active[tid]

        log = json.dumps([e for _, e in store.events_after(tid)])
        assert SECRET not in log
        assert SECRET not in everything_the_model_saw(seen)
        (result,) = tool_results(seen)
        assert SECRET not in json.dumps(result)
        assert result["data"] == {"status": "saved"}
        store.close()
        for f in tmp_path.rglob("*"):
            if f.is_file():
                assert SECRET.encode() not in f.read_bytes(), f
    asyncio.run(go())
