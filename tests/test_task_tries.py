"""Tests for the failing-task read tool: ops, API route, CLI and registry entry."""
import json

from phoenix9 import atomic
from phoenix9.__main__ import main
from phoenix9.ops import controls, runs
from tests.helpers import repair_runs as rr


def _seed(tmp_path):
    """A failed run whose task 1 has two failed tries."""
    made = rr.make_run(tmp_path)
    steps = [{"task": 1, "attempt": k, "step": "build", "status": "failed", "note": f"check {k} failed"} for k in (1, 2)]
    atomic.write_json(made["run_dir"] / "state.json", {
        "run_id": rr.RUN, "project": rr.PROJECT, "status": "failed",
        "tasks": {"1": {"title": "One", "status": "failed"}, "2": {"title": "Two", "status": "pending"}}, "steps": steps})
    return made


def test_default_is_failing_task(phoenix_env, tmp_path):
    _seed(tmp_path)
    got = runs.task_tries(rr.PROJECT, rr.RUN)
    assert got["task"] == 1 and got["title"] == "One" and got["status"] == "failed"
    assert [t["attempt"] for t in got["tries"]] == [1, 2]
    assert got["tries"][1]["reason"] == "check 2 failed"
    assert got["max_tries"] is None or isinstance(got["max_tries"], int)


def test_named_task_and_unknown_task(phoenix_env, tmp_path):
    _seed(tmp_path)
    assert runs.task_tries(rr.PROJECT, rr.RUN, 2)["tries"] == []
    try:
        runs.task_tries(rr.PROJECT, rr.RUN, 9)
    except runs.common.NotFound:
        return
    raise AssertionError("expected NotFound")


def test_cli_json(phoenix_env, tmp_path, capsys):
    _seed(tmp_path)
    assert main(["run", "tries", rr.PROJECT, rr.RUN, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["task"] == 1


def test_registry_entry():
    c = next(c for c in controls.CONTROLS if c.name == "task-tries")
    assert c.risk == "read" and c.agent == "tool" and c.card == "tries_card"
