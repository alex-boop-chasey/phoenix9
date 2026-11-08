"""One stop path (A4): the API/CLI stop goes through the runner's own clean stop, or leaves a stop request."""
import json
import subprocess

import pytest

from helpers import scripted
from helpers.scripted import calls, fail, on
from phoenix9 import events, gates, paths, runend, runs, state, watch
from phoenix9.__main__ import main
from phoenix9.cli import run as cli_run
from phoenix9.ops import common, runs as ops_runs
from phoenix9.runner import Runner

ONE = "# Spec: One task\n\n## Task 1: Only thing\nGoal: make it work.\nDone when:\n- it works\n"


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True, text=True).stdout


@pytest.fixture
def lib(tmp_path, monkeypatch):
    scripted.reset()
    root = scripted.make_library(tmp_path / "lib")
    monkeypatch.setenv("PHOENIX_LIBRARY", str(root))      # the library ops' stop loads for the runner
    yield root
    scripted.reset()


@pytest.fixture
def runner(adapters, lib, monkeypatch):
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    code = paths.projects() / "proj" / "code"
    code.mkdir(parents=True)
    git(code, "init", "-q", "-b", "main")
    git(code, "commit", "-q", "--allow-empty", "-m", "first")
    (paths.projects() / "proj" / "CLAUDE.md").write_text("# proj\n")
    return Runner(adapters, lib)


def start(tmp_path, **overrides):
    f = tmp_path / "spec.md"
    f.write_text(ONE)
    return runs.create_run("proj", f, overrides or None)


def waiting_run(tmp_path, runner):
    on("builder", 1, 1, fail("broke"))
    run_dir = start(tmp_path, max_tries=1, on_failure="pause")
    assert runner.drive(run_dir) == "waiting"
    return run_dir


def test_stop_of_a_waiting_run_is_the_runners_clean_stop(tmp_path, runner):
    run_dir = waiting_run(tmp_path, runner)
    out = ops_runs.stop(run_dir.name, who="cli")
    assert out["status"] == "stopped"
    st = state.load(run_dir)
    assert st["status"] == "stopped" and st["current"]["gate"] is None
    assert st["tasks"]["1"]["status"] == "skipped" and st["tasks"]["1"]["gate"] is None
    assert not any(x["status"] in ("waiting", "running", "pending") for x in st["steps"])
    assert len(calls("notify")) == 1 and calls("summary") == []       # after-stop steps only
    assert not paths.work("proj", run_dir.name).exists()
    assert gates.list_gates() == [] and gates.run_gates(run_dir)[0]["state"] == "closed"
    finished = [e for e in events.read(run_dir / "events.jsonl") if e["type"] == "run.finished"]
    assert len(finished) == 1 and finished[0]["data"]["who"] == "cli"
    assert runner.drive(run_dir) == "stopped"                          # never revived


def test_stop_of_a_queued_run_never_started(tmp_path, runner):
    run_dir = start(tmp_path)
    assert ops_runs.stop(run_dir.name)["status"] == "stopped"
    st = state.load(run_dir)
    assert st["status"] == "stopped" and st["tasks"]["1"]["status"] == "skipped"
    assert calls() == []


def test_stop_while_the_runner_walks_leaves_a_request(tmp_path, runner, monkeypatch):
    run_dir = start(tmp_path)
    state.set_status(run_dir, "running")
    with runend.lock(run_dir):                       # the runner is walking it
        out = ops_runs.stop(run_dir.name, who="dashboard")
    assert out["status"] == "stop requested"
    assert state.load(run_dir)["status"] == "running"
    assert runend.stop_requested(run_dir)["who"] == "dashboard"
    assert runner.drive(run_dir) == "stopped"        # the runner acts on it through its clean stop
    assert runend.stop_requested(run_dir) is None
    assert state.load(run_dir)["tasks"]["1"]["status"] == "skipped"


def test_already_ended_is_refused(tmp_path, runner):
    run_dir = start(tmp_path)
    state.set_status(run_dir, "done")
    with pytest.raises(common.OpsError, match="already done"):
        ops_runs.stop(run_dir.name)


def test_stop_checks_the_same_permission_as_answering(tmp_path, runner):
    run_dir = start(tmp_path)
    with pytest.raises(common.OpsError, match="may not stop"):
        ops_runs.stop(run_dir.name, who="chat:home")
    assert state.load(run_dir)["status"] == "queued"
    (paths.projects() / "proj" / "phoenix.toml").write_text('home_chat_may_answer = ["escalation"]\n')
    assert ops_runs.stop(run_dir.name, who="chat:home")["status"] == "stopped"


@pytest.mark.parametrize("who", ["cli", "dashboard"])
def test_stop_allowed_callers(tmp_path, runner, who):
    run_dir = start(tmp_path)
    assert ops_runs.stop(run_dir.name, who=who)["status"] == "stopped"


def test_cli_waits_for_the_runner_to_stop_it(tmp_path, runner, monkeypatch, capsys):
    run_dir = start(tmp_path)
    state.set_status(run_dir, "running")
    lk = runend.lock(run_dir)
    lk.__enter__()

    def runner_moves(seconds):                       # the runner reaches its next boundary
        lk.__exit__()
        runner.drive(run_dir)
    monkeypatch.setattr(cli_run.time, "sleep", runner_moves)
    assert main(["run", "stop", run_dir.name, "--yes"]) == 0
    assert f"Stopped run {run_dir.name}." in capsys.readouterr().out


def test_cli_says_when_the_runner_has_not_acted(tmp_path, runner, monkeypatch, capsys):
    run_dir = start(tmp_path)
    state.set_status(run_dir, "running")
    monkeypatch.setattr(cli_run, "STOP_WAIT_S", 0)
    with runend.lock(run_dir):
        assert main(["run", "stop", run_dir.name, "--yes", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "stop requested"


def test_watch_fail_uses_the_same_end(tmp_path, runner, adapters):
    run_dir = waiting_run(tmp_path, runner)
    watch._fail(adapters, state.load(run_dir), "boom")
    st = state.load(run_dir)
    assert st["status"] == "failed" and st["error"] == "boom" and st["current"]["gate"] is None
    assert st["tasks"]["1"]["status"] == "skipped"
    assert not any(x["status"] in ("waiting", "running") for x in st["steps"])
    assert gates.list_gates() == []
    assert paths.work("proj", run_dir.name).exists()      # a failed run keeps its worktree for repair
