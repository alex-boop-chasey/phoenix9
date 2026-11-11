"""Tests for the typed diagnosis of a failed run: rules, ops, API route, CLI and registry entry."""
import json

from phoenix9 import atomic
from phoenix9.__main__ import main
from phoenix9.ops import controls, repair
from tests.helpers import repair_runs as rr


def _seed(tmp_path, reasons=("check 1 failed", "check 2 failed"), max_tries=2, task_status="failed", status="failed"):
    """A run whose task 1 has one failed try per reason."""
    made = rr.make_run(tmp_path, status=status)
    steps = [{"task": 1, "attempt": k, "step": "build", "status": "failed", "note": r} for k, r in enumerate(reasons, 1)]
    atomic.write_json(made["run_dir"] / "state.json", {
        "run_id": rr.RUN, "project": rr.PROJECT, "status": status,
        "tasks": {"1": {"title": "One", "status": task_status, "tries": len(reasons)}}, "steps": steps})
    atomic.write_json(made["run_dir"] / "settings.json", {"model": "fake", "max_tries": max_tries})
    for k, r in enumerate(reasons, 1):
        atomic.write_json(made["run_dir"] / f"tasks/1/attempt-{k}/result.json", {"attempt": k, "status": "failed", "reasons": [r]})
    return made


def _controls(got):
    return [o["control"] for o in got["options"]]


def test_out_of_tries(phoenix_env, tmp_path):
    _seed(tmp_path)
    got = repair.diagnose(rr.PROJECT, rr.RUN)
    assert got["cause_code"] == "out-of-tries" and "2" in got["cause"]
    assert len(got["tried"]) == 2 and "check 2 failed" in got["tried"][1]
    assert _controls(got) == ["max-tries-raise", "step-rerun", "task-skip"]
    for o in got["options"]:
        assert set(o) == {"control", "label", "inputs"}


def test_same_failure(phoenix_env, tmp_path):
    _seed(tmp_path, reasons=("same", "same"), max_tries=5)
    assert repair.diagnose(rr.PROJECT, rr.RUN)["cause_code"] == "same-failure"


def test_spec_problem(phoenix_env, tmp_path):
    _seed(tmp_path, reasons=("SPEC_PROBLEM: contradicts",), max_tries=3)
    got = repair.diagnose(rr.PROJECT, rr.RUN)
    assert got["cause_code"] == "spec-problem" and "max-tries-raise" not in _controls(got)


def test_stopped_run(phoenix_env, tmp_path):
    _seed(tmp_path, reasons=(), task_status="running", status="stopped")
    got = repair.diagnose(rr.PROJECT, rr.RUN)
    assert got["cause_code"] == "run-stopped" and "run-resume-from" in _controls(got)


def test_cli_json_and_text(phoenix_env, tmp_path, capsys):
    _seed(tmp_path)
    assert main(["repair", "diagnose", rr.RUN, "--project", rr.PROJECT, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["cause_code"] == "out-of-tries"
    assert main(["repair", "diagnose", rr.RUN, "--project", rr.PROJECT]) == 0
    assert "Option:" in capsys.readouterr().out


def test_registry_entry():
    c = next(c for c in controls.CONTROLS if c.name == "run-diagnose")
    assert c.risk == "read" and c.agent == "tool" and c.route.endswith("/diagnose")
