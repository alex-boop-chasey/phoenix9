"""Tests for builds-list: each row carries its failure line, and the limit input."""
from phoenix9 import atomic
from phoenix9.ops import controls, runs
from tests.helpers import repair_runs as rr


def _seed(tmp_path):
    """A failed run whose task 2 failed with a note."""
    made = rr.make_run(tmp_path)
    steps = [{"task": 2, "attempt": 1, "step": "build", "status": "failed", "note": "check 1 failed"}]
    atomic.write_json(made["run_dir"] / "state.json", {
        "run_id": rr.RUN, "project": rr.PROJECT, "status": "failed", "created": "2026-01-01T00:00:00Z", "updated": "2026-01-01T00:00:00Z",
        "tasks": {"1": {"title": "One", "status": "passed"}, "2": {"title": "Two", "status": "failed"}}, "steps": steps})


def test_rows_carry_failure_line(phoenix_env, tmp_path):
    _seed(tmp_path)
    row = runs.builds(rr.PROJECT)[0]
    assert row["status"] == "failed" and "finished" in row
    assert row["failed_task"] == 2 and row["failed_reason"] == "check 1 failed"


def test_limit(phoenix_env, tmp_path):
    _seed(tmp_path)
    assert len(runs.builds(rr.PROJECT, 1)) == 1


def test_registry_has_limit():
    c = next(c for c in controls.CONTROLS if c.name == "builds-list")
    assert "limit" in [i.name for i in c.inputs]
