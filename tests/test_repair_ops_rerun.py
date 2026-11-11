"""Tests for the typed repair ops: re-run a step and resume from a step."""
import pytest
from helpers.repair_runs import make_run

from phoenix9 import atomic, events, paths, resolve, settings, state
from phoenix9.library import load_library
from phoenix9.ops import common, repair as ops
from phoenix9.repair import lock


def make(tmp_path):
    """A failed run with one failed task."""
    r = make_run(tmp_path, status="paused")
    lib = load_library(paths.library())
    eff = settings.effective(paths.projects() / r["project"], lib)
    atomic.write_json(r["run_dir"] / "settings.json", eff.values)
    atomic.write_json(r["run_dir"] / "plan.json", resolve.resolve(lib, settings.enabled_map(eff)).to_json())
    task = {**state.new_task("One"), "status": "failed", "tries": 1, "failures": ["x"]}
    state.update(r["run_dir"], lambda s: s.update(tasks={"1": task}, steps=[]))
    return r


def events_of(kind):
    """All events of one type from the events log, each with its data merged in."""
    return [{**e, **e["data"]} for e in events.read(paths.events()) if e["type"] == kind]


def test_rerun_task_records_who(tmp_path):
    r = make(tmp_path)
    out = ops.rerun_step(r["run"], task=1, who="agent")
    assert not out.get("rolled_back"), out
    assert state.load(r["run_dir"])["tasks"]["1"]["status"] != "failed"
    applied = events_of("repair.applied")
    assert applied and applied[-1]["who"] == "agent" and applied[-1]["steps"] == ["retry task 1"]
    assert any(e.get("who") == "agent" for e in events_of("command"))


def test_needs_exactly_one_target(tmp_path):
    r = make(tmp_path)
    with pytest.raises(common.OpsError):
        ops.rerun_step(r["run"])
    with pytest.raises(common.OpsError):
        ops.rerun_step(r["run"], task=1, finish_step="x")
    with pytest.raises(common.OpsError):
        ops.rerun_step(r["run"], finish_step="bad name\n- force")


def test_resume_from_builds_two_steps(tmp_path):
    r = make(tmp_path)
    ops.resume_from(r["run"], 1, who="agent")
    applied = events_of("repair.applied")
    assert applied[-1]["steps"] == ["retry task 1", "resume"] and applied[-1]["who"] == "agent"


def test_refused_while_locked(tmp_path):
    r = make(tmp_path)
    with lock.held(r["run_dir"]):
        with pytest.raises(common.Conflict, match="Another repair"):
            ops.rerun_step(r["run"], task=1)
        with pytest.raises(common.Conflict, match="Another repair"):
            ops.resume_from(r["run"], 1)
