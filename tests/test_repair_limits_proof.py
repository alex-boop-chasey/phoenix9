"""Proof of the repair limits on a seeded failed run: who is `agent`, unsafe repairs are refused, one at a time."""
import pytest
from test_repair_ops_skip import applied, make as seed

from phoenix9 import atomic, events, paths, state
from phoenix9.ops import common, repair as ops, runs as runs_ops
from phoenix9.repair import lock


def make(tmp_path, status="paused"):
    """The seeded failed run (one failing task), with its tries matching the two attempt folders it has."""
    r = seed(tmp_path)
    state.update(r["run_dir"], lambda s: (s["tasks"]["1"].update(tries=2, failures=["SPEC_PROBLEM: the bullet contradicts itself"]),
                                         s.update(status=status)))
    return r


def agent_events(kind):
    """The events of one type whose data says who `agent`."""
    return [e for e in events.read(paths.events()) if e["type"] == kind and e["data"].get("who") == "agent"]


def _rerun(r):
    return ops.rerun_step(r["run"], task=1, who="agent")


def _resume(r):
    return ops.resume_from(r["run"], 1, who="agent")


def _skip(r):
    return ops.skip_task(r["run"], 1, "not needed any more", who="agent")


def _rewrite(r):
    return ops.rewrite_checks(r["run"], 1, "the old check tested the wrong file", who="agent")


def _raise(r):
    return ops.raise_max_tries(r["run"], 5, who="agent")


@pytest.mark.parametrize("repair", [_rerun, _resume, _skip, _rewrite, _raise])
def test_each_repair_records_who_agent(tmp_path, repair):
    """Every repair applied as agent leaves a repair event and a command event that say who `agent`."""
    r = make(tmp_path, "failed" if repair is _resume else "paused")
    if repair is _resume:
        state.update(r["run_dir"], lambda s: s["tasks"].pop("2"))
    out = repair(r)
    if repair is not _rewrite:   # the agent may not unlock checks itself: its rewrite is tried, rolled back, recorded
        assert not out.get("rolled_back"), (out.get("refused"), out.get("steps"))
    assert applied()[-1]["who"] == "agent"
    assert agent_events("repair.applied") and agent_events("command")


def test_restart_on_preset_records_who_agent(tmp_path, monkeypatch):
    """Restarting on another preset records who `agent` on the old run's events."""
    r = make(tmp_path, "failed")
    monkeypatch.setattr(runs_ops, "start", lambda project, spec, overrides=None, who="cli":
                        {"run_id": "new-run", "project": project, "status": "queued"})
    ops.restart_on_preset(r["project"], r["run"], "full", who="agent")
    done = agent_events("repair.applied")
    assert done and done[-1]["run"] == r["run"] and agent_events("command")


def test_unsafe_repair_refused_and_run_unchanged(tmp_path):
    """Rewriting locked checks is refused in plain words; state, checks and events stay as they were."""
    r = make(tmp_path)
    lock_file = r["run_dir"] / "tasks" / "1" / "checks.lock.json"
    atomic.write_json(lock_file, {"files": {"tests/a.py": "abc"}})
    before = (state.load(r["run_dir"]), lock_file.read_text(), len(events.read(paths.events())),
              sorted(p.name for p in r["run_dir"].rglob("*")))
    with pytest.raises(common.Conflict, match="loosen a safety check") as err:
        ops.rewrite_checks(r["run"], 1, "make it easier", who="agent")
    assert "Traceback" not in str(err.value) and len(str(err.value)) > 20
    after = (state.load(r["run_dir"]), lock_file.read_text(), len(events.read(paths.events())),
             sorted(p.name for p in r["run_dir"].rglob("*")))
    assert after == before
    assert not applied()


def test_second_concurrent_repair_refused(tmp_path):
    """While one repair holds the run, another repair on it is refused and changes nothing."""
    r = make(tmp_path)
    before = state.load(r["run_dir"])
    with lock.held(r["run_dir"]):
        for repair in (_rerun, _skip, _raise):
            with pytest.raises(common.Conflict, match="Another repair on this run is still going"):
                repair(r)
    assert state.load(r["run_dir"]) == before and not applied()
    _skip(r)
    assert applied()[-1]["who"] == "agent"
