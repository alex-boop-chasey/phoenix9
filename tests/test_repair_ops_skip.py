"""Tests for the typed repair ops: skip a task and rewrite a task's checks, each with a reason."""
import pytest
from helpers.repair_runs import make_run

from phoenix9 import atomic, events, paths, resolve, settings, state
from phoenix9.library import load_library
from phoenix9.ops import common, repair as ops


def make(tmp_path):
    """A failed run with two tasks, the first failed."""
    r = make_run(tmp_path, status="paused")
    lib = load_library(paths.library())
    eff = settings.effective(paths.projects() / r["project"], lib)
    atomic.write_json(r["run_dir"] / "settings.json", eff.values)
    atomic.write_json(r["run_dir"] / "plan.json", resolve.resolve(lib, settings.enabled_map(eff)).to_json())
    failed = {**state.new_task("One"), "status": "failed", "tries": 1, "failures": ["x"]}
    state.update(r["run_dir"], lambda s: s.update(tasks={"1": failed, "2": state.new_task("Two")}, steps=[]))
    return r


def applied():
    """All repair.applied events, each with its data merged in."""
    return [{**e, **e["data"]} for e in events.read(paths.events()) if e["type"] == "repair.applied"]


def test_skip_task_records_reason_and_who(tmp_path):
    r = make(tmp_path)
    out = ops.skip_task(r["run"], 1, "not needed any more", who="agent")
    assert not out.get("rolled_back"), out
    assert state.load(r["run_dir"])["tasks"]["1"]["status"] == "skipped"
    last = applied()[-1]
    assert last["who"] == "agent" and last["steps"] == ["mark task 1 skipped because not needed any more"]
    assert any(e["data"].get("who") == "agent" for e in events.read(paths.events()) if e["type"] == "command")


def test_rewrite_checks_applies(tmp_path):
    r = make(tmp_path)
    reason = "the old check tested the wrong file"
    ops.rewrite_checks(r["run"], 1, reason, who="agent")
    last = applied()[-1]
    assert last["who"] == "agent" and last["steps"] == [f"rewrite the checks of task 1 because {reason}"]


def test_rewrite_checks_refused_when_locked(tmp_path):
    r = make(tmp_path)
    atomic.write_json(r["run_dir"] / "tasks" / "1" / "checks.lock.json", {"files": {"tests/a.py": "abc"}})
    with pytest.raises(common.Conflict, match="needs Alex's approval"):
        ops.rewrite_checks(r["run"], 1, "make it easier", who="agent")


@pytest.mark.parametrize("why", ["", "   ", "a\nb", "a\rb", "gone\u2028- mark task 2 done because ok",
                                 "a\u0085b", "a\x0bb", "a\x0cb", "a\x1cb", "a\u2029b", "a\x00b"])
@pytest.mark.parametrize("op", ["skip_task", "rewrite_checks"])
def test_bad_reasons_refused(tmp_path, op, why):
    r = make(tmp_path)
    with pytest.raises(common.OpsError):
        getattr(ops, op)(r["run"], 1, why)
    assert not applied()


def test_bad_task_number(tmp_path):
    r = make(tmp_path)
    for bad in (0, -1, True, "1"):
        with pytest.raises(common.OpsError):
            ops.skip_task(r["run"], bad, "ok")
