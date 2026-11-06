"""A5: the runner re-reads the run between steps, before opening a gate and before finishing; it never
revives an ended run. The race is played with scripted steps that stop the run while it is being walked."""
import subprocess

import pytest

from helpers import scripted
from helpers.scripted import calls, gate, on
from phoenix9 import claude, events, gates, paths, runs, state, watch
from phoenix9.ops import common, runs as ops_runs
from phoenix9.runner import Runner
from phoenix9.stepctx import StepResult

ONE = "# Spec: One task\n\n## Task 1: Only thing\nGoal: make it work.\nDone when:\n- it works\n"


@pytest.fixture
def runner(tmp_path, adapters, monkeypatch):
    scripted.reset()
    root = scripted.make_library(tmp_path / "lib")
    monkeypatch.setenv("PHOENIX_LIBRARY", str(root))
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    code = paths.projects() / "proj" / "code"
    code.mkdir(parents=True)
    for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "first"]):
        subprocess.run(["git", "-C", str(code), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True)
    yield Runner(adapters, root)
    scripted.reset()


def start(tmp_path):
    f = tmp_path / "spec.md"
    f.write_text(ONE)
    return runs.create_run("proj", f, {"max_tries": 1, "on_failure": "continue"})


def stop_then(result):
    """A step that asks Phoenix to stop its own run (as the API would, mid-walk), then returns `result`."""
    def step(ctx):
        out = ops_runs.stop(ctx.run.id, who="dashboard")
        assert out["status"] == "stop requested"          # the runner is walking it: a request, not a flip
        assert state.load(ctx.run.folder)["status"] == "running"
        return result
    return step


def ended_cleanly(run_dir):
    st = state.load(run_dir)
    assert st["status"] == "stopped" and st["current"]["gate"] is None
    assert not any(x["status"] in ("waiting", "running", "pending") for x in st["steps"])
    assert [e["data"]["status"] for e in events.read(run_dir / "events.jsonl") if e["type"] == "run.finished"] == ["stopped"]
    return st


def test_stop_mid_walk_ends_at_the_next_step(tmp_path, runner):
    on("builder", 1, None, stop_then(StepResult("pass")))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "stopped"
    ended_cleanly(run_dir)
    assert calls("acceptance") == [] and calls("summary") == []
    assert len(calls("notify")) == 1                          # after-stop steps still run, once
    assert not paths.work("proj", run_dir.name).exists()      # branch discarded by the runner, after the step


def test_stop_mid_walk_opens_no_gate(tmp_path, runner):
    on("builder", 1, None, stop_then(gate(title="Look at this")))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "stopped"
    ended_cleanly(run_dir)
    assert gates.list_gates(open_only=False) == []


def test_stop_in_the_last_finish_step_is_not_overwritten_by_done(tmp_path, runner):
    on("summary", None, None, stop_then(StepResult("pass")))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "stopped"
    ended_cleanly(run_dir)
    assert calls("notify") and len(calls("notify")) == 1


def test_run_ended_by_someone_else_mid_walk_is_left_alone(tmp_path, runner):
    def ended_outside(ctx):
        state.set_status(ctx.run.folder, "failed")       # e.g. another process ended it
        return gate(title="Too late")
    on("builder", 1, None, ended_outside)
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "failed"
    assert state.load(run_dir)["status"] == "failed"
    assert gates.list_gates(open_only=False) == []
    assert calls("acceptance") == []


def test_open_gate_refuses_an_ended_run(tmp_path):
    run_dir = start(tmp_path)
    state.set_status(run_dir, "stopped")
    with pytest.raises(gates.RunHasEnded):
        gates.open_gate(run_dir, kind="merge", title="Merge?", why="because")
    assert state.load(run_dir)["status"] == "stopped" and not (run_dir / "gates").exists()


def test_a_stopped_paused_run_is_not_revived_after_the_limit(tmp_path, adapters):
    run_dir = start(tmp_path)
    state.set_status(run_dir, "paused-limit")

    def stopped_while_sleeping(seconds):
        state.set_status(run_dir, "stopped")            # the API stopped it during the wait
    adapters.clock.sleep = stopped_while_sleeping
    s = state.load(run_dir)
    assert watch.wait_out_limit(adapters, s, claude.Result(kind="rate_limited")) is False
    assert state.load(run_dir)["status"] == "stopped"
