"""Proof: the next_steps chips for the fake projects follow the rules and pass the chip check."""
import asyncio

from agentkit import llm, runs
from agentkit.packs.phoenix import build_pack
from agentkit.store import Store
from agentkit.suggest import check_actions
from fake_phoenix import FakePhoenix
from test_approvals import script
from test_browser_tools import customs

EXPECTED = {"fresh": ["Start a build"], "delta": ["What went wrong?", "Answer the open question"],
            "busy": ["How is the build doing?"]}


def chips_for(project):
    """Run the agent: next_steps, then suggest_next_actions with exactly what it gave; return the chips shown."""
    async def go():
        pack = build_pack(FakePhoenix().client())
        tools = {t.name: t for t in pack.server_tools}
        chips = tools["next_steps"].function(project=project)["suggestions"]
        store, seen = Store(":memory:"), []
        plan = [("next_steps", {"project": project}), ("suggest_next_actions", {"actions": chips})]
        r = runs.Runs(store, llm.build_pack_agent(script(plan, seen), pack), pack)
        tid = store.create_thread()["id"]
        r.start(tid, "what next?")
        await r.active[tid]
        return [a for v in customs(store, tid, "suggestions") for a in v["actions"]]

    return asyncio.run(go())


def test_proof_next_steps():
    for project, labels in EXPECTED.items():
        shown = chips_for(project)
        assert [c["label"] for c in shown] == labels
        assert check_actions(shown) == shown
        assert all("$" not in c["label"] + c["message"] for c in shown)
