"""Tests that a run gets only one repair approval at a time, across threads, with a plain refusal to the model."""
import asyncio

from pydantic import BaseModel

from agentkit import llm, runs
from agentkit.pack import Pack, ServerTool
from agentkit.store import Store
from test_approvals import requests_in, script, types  # noqa: F401


class RepairInputs(BaseModel):
    run_id: str


def make_pack(done):
    """A pack with one guarded repair tool and one unguarded change tool."""

    def repair(run_id):
        done.append(run_id)
        return {"repaired": run_id}

    return Pack(name="t", instructions="", server_tools=(
        ServerTool("repair-skip-task", "Skip.", RepairInputs, "change", repair, one_per="run_id"),
    ))


def build(plan, done, store):
    """A Runs over the shared store with a scripted model."""
    seen = []
    return runs.Runs(store, llm.build_pack_agent(script(plan, seen), make_pack(done)), make_pack(done)), seen


def test_repair_one_at_a_time_across_threads():
    async def go():
        store, done = Store(":memory:"), []
        first, _ = build([("repair-skip-task", {"run_id": "r1"})], done, store)
        second, seen = build([("repair-skip-task", {"run_id": "r1"})], done, store)
        a, b = store.create_thread()["id"], store.create_thread()["id"]
        first.start(a, "go")
        await first.active[a]
        assert len(requests_in(store, a)) == 1
        second.start(b, "go")
        await second.active[b]
        await asyncio.sleep(0.05)
        assert requests_in(store, b) == [] and len(store.pending_pauses()) == 1
        assert types(store, b)[-1] == "RUN_FINISHED" and done == []
        assert runs.REPAIR_BUSY in str(seen)

    asyncio.run(go())


def test_repair_one_at_a_time_other_run_is_allowed():
    async def go():
        store, done = Store(":memory:"), []
        r, _ = build([("repair-skip-task", {"run_id": "r1"})], done, store)
        r2, _ = build([("repair-skip-task", {"run_id": "r2"})], done, store)
        a, b = store.create_thread()["id"], store.create_thread()["id"]
        r.start(a, "go")
        await r.active[a]
        r2.start(b, "go")
        await r2.active[b]
        assert len(requests_in(store, b)) == 1

    asyncio.run(go())


def test_repair_one_at_a_time_same_turn():
    async def go():
        from pydantic_ai.models.function import DeltaToolCall, FunctionModel
        import json
        store, done = Store(":memory:"), []

        async def reply(messages, info):
            from pydantic_ai.messages import ModelResponse
            if not any(isinstance(m, ModelResponse) for m in messages):
                yield {0: DeltaToolCall(name="repair-skip-task", json_args=json.dumps({"run_id": "r1"}), tool_call_id="c0")}
                yield {1: DeltaToolCall(name="repair-skip-task", json_args=json.dumps({"run_id": "r1"}), tool_call_id="c1")}
            else:
                yield "ok"

        pack = make_pack(done)
        r = runs.Runs(store, llm.build_pack_agent(FunctionModel(stream_function=reply), pack), pack)
        t = store.create_thread()["id"]
        r.start(t, "go")
        await r.active[t]
        assert len(requests_in(store, t)) == 1 and len(store.pending_pauses(t)) == 1

    asyncio.run(go())
