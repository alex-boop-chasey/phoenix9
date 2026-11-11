"""Tests for the repair op that restarts a stopped or failed build on another preset."""
import pytest
from helpers.repair_runs import make_run

from phoenix9 import atomic, events, paths, state
from phoenix9.ops import common, repair as ops, runs as runs_ops


@pytest.fixture
def started(monkeypatch):
    """Replace the start path with a recorder, so no Docker is needed."""
    calls = []

    def fake(project, spec_path, overrides=None, who="cli"):
        calls.append((project, str(spec_path), overrides, who))
        return {"run_id": "new-run", "project": project, "status": "queued"}
    monkeypatch.setattr(runs_ops, "start", fake)
    return calls


def test_restart_starts_new_run_and_records(tmp_path, started):
    r = make_run(tmp_path, status="failed")
    out = ops.restart_on_preset(r["project"], r["run"], "full", who="agent")
    assert out["new_run_id"] == "new-run"
    assert started[0][2]["preset"] == "full" and started[0][1].endswith("spec.md")
    evs = events.read(paths.events())
    done = [e for e in evs if e["type"] == "repair.applied"][-1]
    assert done["run"] == r["run"] and done["data"]["who"] == "agent" and done["data"]["new_run"] == "new-run"
    assert any(e["type"] == "command" and e["data"].get("who") == "agent" for e in evs)


def test_refused_while_running(tmp_path, started):
    r = make_run(tmp_path, status="running")
    with pytest.raises(common.Conflict):
        ops.restart_on_preset(r["project"], r["run"], "full")
    assert not started


def test_unknown_preset_refused(tmp_path, started):
    r = make_run(tmp_path, status="stopped")
    with pytest.raises(common.OpsError):
        ops.restart_on_preset(r["project"], r["run"], "nope")
    assert not started


def test_same_preset_refused(tmp_path, started, monkeypatch):
    r = make_run(tmp_path, status="failed")
    monkeypatch.setattr(runs_ops, "detail", lambda project, run_id: {"preset": "quick"})
    with pytest.raises(common.Conflict):
        ops.restart_on_preset(r["project"], r["run"], "quick")
    assert not started
