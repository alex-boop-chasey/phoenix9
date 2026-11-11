"""Tests that a run's data lists each task's tries, one line per try."""
import json

from phoenix9 import failmodes, keys, state
from phoenix9.__main__ import main
from phoenix9.ops import runs
from tests.helpers import repair_runs as rr

SECRET = "fake-secret-value-12345"


def _seed(made):
    """Task 1 fails three times (builder passes, checks fail); task 2 has one clean try."""
    run_dir = made["run_dir"]
    state.update(run_dir, lambda s: s.update(tasks={"1": state.new_task("One"), "2": state.new_task("Two")}, steps=[]))
    for k in (1, 2, 3):
        i = state.add_step_line(run_dir, "g", 1, "builder", "running", attempt=k)
        state.set_step_line(run_dir, i, status="passed")
        i = state.add_step_line(run_dir, "g", 1, "checks", "running", attempt=k)
        state.set_step_line(run_dir, i, status="failed", note=f"test {k} failed\n  with {SECRET}")
        failmodes.write_attempt_result(run_dir, 1, k, "failed", [f"test {k} failed"])
    i = state.add_step_line(run_dir, "g", 2, "builder", "running", attempt=1)
    state.set_step_line(run_dir, i, status="passed")


def test_detail_lists_one_line_per_try(phoenix_env, tmp_path):
    made = rr.make_run(tmp_path)
    keys.set_key(rr.PROJECT, "TOKEN", SECRET, secret=True)
    _seed(made)
    got = runs.detail(rr.PROJECT, rr.RUN)
    assert got["tries"] == {"1": 3, "2": 1}
    lines = got["try_lines"]["1"]
    assert [(t["attempt"], t["step"], t["status"]) for t in lines] == [(k, "checks", "failed") for k in (1, 2, 3)]
    assert [t["reason"] for t in lines][0].startswith("test 1 failed with")
    assert SECRET not in json.dumps(got["try_lines"])
    assert all("\n" not in t["reason"] and t["at"] for t in lines)
    assert [t["status"] for t in got["try_lines"]["2"]] == ["passed"]


def test_run_show_prints_tries(phoenix_env, tmp_path, capsys):
    made = rr.make_run(tmp_path)
    _seed(made)
    assert main(["run", "show", rr.PROJECT, rr.RUN]) == 0
    out = capsys.readouterr().out
    assert "task 1: 3 tries" in out
    assert len([x for x in out.splitlines() if x.startswith("task 1, try")]) == 3
    assert main(["run", "show", rr.PROJECT, rr.RUN, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["tries"]["1"] == 3
