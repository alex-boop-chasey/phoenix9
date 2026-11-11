"""Tests that the agent's repair routes work through the API and record who `agent` in the run's events."""
import pytest
from helpers.repair_runs import PROJECT, RUN, make_run

from phoenix9 import atomic, events, paths, resolve, settings, state
from phoenix9.library import load_library
from phoenix9.ops import runs as runs_ops
from test_agentaccess import HEADERS, as_agent
from test_api_server import api, dist  # noqa: F401  (fixtures)

BASE = f"/api/runs/{PROJECT}/{RUN}/repair"


def make(tmp_path):
    """A paused run with two tasks, the first failed."""
    r = make_run(tmp_path, status="paused")
    lib = load_library(paths.library())
    eff = settings.effective(paths.projects() / r["project"], lib)
    atomic.write_json(r["run_dir"] / "settings.json", eff.values)
    atomic.write_json(r["run_dir"] / "plan.json", resolve.resolve(lib, settings.enabled_map(eff)).to_json())
    failed = {**state.new_task("One"), "status": "failed", "tries": 1, "failures": ["x"]}
    state.update(r["run_dir"], lambda s: s.update(tasks={"1": failed, "2": state.new_task("Two")}, steps=[]))
    return r


def agent_applied():
    """The repair.applied events of this run whose who is the agent."""
    return [e for e in events.read(paths.events())
            if e["type"] == "repair.applied" and e.get("run") == RUN and e["data"].get("who") == "agent"]


@pytest.mark.parametrize("route, body", [
    ("rerun", {"task": 1}),
    ("resume", {"task": 1}),
    ("skip", {"task": 1, "why": "not needed any more"}),
    ("rewrite-checks", {"task": 1, "why": "the old check tested the wrong file"}),
    ("max-tries", {"tries": 9}),
])
def test_route_records_the_agent(api, tmp_path, route, body):
    make(tmp_path)
    as_agent(api)
    status, reply = api(f"{BASE}/{route}", "POST", HEADERS, body)
    assert status == 200 and reply["ok"], reply
    assert len(agent_applied()) == 1
    assert any(e["type"] == "command" and e["data"].get("who") == "agent" for e in events.read(paths.events()))


def test_restart_route_records_the_agent(api, tmp_path, monkeypatch):
    make_run(tmp_path, status="failed")
    monkeypatch.setattr(runs_ops, "start", lambda project, spec, overrides=None, who="cli":
                        {"run_id": "new-run", "project": project, "status": "queued"})
    as_agent(api)
    status, reply = api(f"{BASE}/restart", "POST", HEADERS, {"preset": "full"})
    assert status == 200 and reply["data"]["new_run_id"] == "new-run", reply
    assert agent_applied()[0]["data"]["new_run"] == "new-run"


def test_bad_bodies_are_refused(api, tmp_path):
    make(tmp_path)
    as_agent(api)
    for route, body in (("resume", {}), ("skip", {"task": 1}), ("skip", {"task": "1", "why": "x"}),
                        ("max-tries", {"tries": True}), ("restart", {}), ("rerun", {"task": 1, "finish_step": 5})):
        assert api(f"{BASE}/{route}", "POST", HEADERS, body)[0] == 400, (route, body)
    assert not agent_applied()


def test_free_text_apply_stays_off_the_agent(api, tmp_path):
    make(tmp_path)
    as_agent(api)
    assert api(f"/api/repair/{RUN}/apply", "POST", HEADERS, {"note": "x", "confirm": True})[0] == 403
