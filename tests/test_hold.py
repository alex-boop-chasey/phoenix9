"""The update hold: the runner stops at a task boundary while an update asks; what counts as busy."""
import contextlib
import fcntl
import subprocess

import pytest

from helpers import scripted
from helpers.scripted import calls, on
from phoenix9 import atomic, events, hold, paths, runs, state, watch
from phoenix9.runner import Runner
from phoenix9.stepctx import StepResult

TWO = """# Spec: Two tasks

## Task 1: First
Goal: one.
Done when:
- one works

## Task 2: Second
Goal: two.
Done when:
- two works
"""


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   check=True, capture_output=True)


@pytest.fixture
def project():
    code = paths.projects() / "proj" / "code"
    code.mkdir(parents=True)
    git(code, "init", "-q", "-b", "main")
    (code / "README.md").write_text("hello\n")
    git(code, "add", "-A")
    git(code, "commit", "-q", "-m", "first")
    return code.parent


@pytest.fixture
def lib(tmp_path):
    scripted.reset()
    yield scripted.make_library(tmp_path / "lib")
    scripted.reset()


def start(tmp_path, name="spec.md"):
    f = tmp_path / name
    f.write_text(TWO)
    return runs.create_run("proj", f, None)


@contextlib.contextmanager
def update_running():
    """Act as a running updater: hold HOME/update/lock (a hold only counts while it is held)."""
    lock = hold.lock_file()
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a") as fd:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)


def make_state(run_id, status, held=None, project="proj"):
    run_dir = paths.runs(project) / run_id
    run_dir.mkdir(parents=True)
    st = state.new_state(run_id, project, {"1": state.new_task("a"), "2": state.new_task("b")})
    st["status"] = status
    st["tasks"]["1"]["status"] = "running" if status == "running" else "waiting"
    if held is not None:
        st["current"]["held"] = held
    atomic.write_json(run_dir / "state.json", st)
    return run_dir


# 8
def test_runner_holds_at_task_boundary(tmp_path, project, lib, adapters):
    run_dir = start(tmp_path)

    def builder_1(ctx):
        hold.request_hold("update to v9.1")     # the update asks while task 1 is mid-way
        assert hold.harness_busy()[0]
        return StepResult("pass", produces={"diff": "builder:1"})
    on("builder", 1, None, builder_1)
    during_2 = []

    def builder_2(ctx):
        during_2.append(state.load(run_dir)["current"].get("held"))
        return StepResult("pass", produces={"diff": "builder:2"})
    on("builder", 2, None, builder_2)
    seen = []
    real_sleep = adapters.clock.sleep

    def sleep(s):
        st = state.load(run_dir)
        seen.append((s, st["current"].get("held"), st["tasks"]["1"]["status"], len(calls("builder", 2)),
                     hold.harness_busy()[0]))
        if len(seen) == 2:
            hold.release_hold()
        real_sleep(s)
    adapters.clock.sleep = sleep
    with update_running():
        assert Runner(adapters, lib).drive(run_dir) == "done"
    assert seen == [(5, True, "passed", 0, False)] * 2      # held, task 1 done, task 2 not started, not busy
    st = state.load(run_dir)
    assert st["tasks"]["2"]["status"] == "passed" and not st["current"].get("held")
    assert len(calls("builder", 2)) == 1 and during_2 == [None]    # each step start resets `current`
    assert [e["type"] for e in events.read(run_dir / "events.jsonl")].count("run.held") == 1


def test_service_loop_takes_no_queued_run_while_held(tmp_path, project, lib, adapters):
    run_dir = start(tmp_path)
    runner = Runner(adapters, lib)
    hold.request_hold("update to v9.1")
    with update_running():
        assert watch.watch_once(adapters, runner) is None
        assert state.load(run_dir)["status"] == "queued" and calls() == []
    hold.release_hold()
    assert watch.watch_once(adapters, runner) == run_dir.name
    assert state.load(run_dir)["status"] == "done"


def test_old_state_without_held_still_loads(tmp_path, project, lib, adapters):
    run_dir = start(tmp_path)
    st = state.load(run_dir)
    assert "held" not in st["current"]
    assert Runner(adapters, lib).drive(run_dir) == "done"
    assert "held" not in state.load(run_dir)["current"]      # never written when no hold was asked


# 9
def test_waiting_and_queued_runs_are_not_busy():
    make_state("a", "waiting")
    make_state("b", "queued")
    make_state("c", "paused-limit")
    make_state("d", "done")
    make_state("e", "running", held=True)
    assert hold.harness_busy() == (False, "")
    make_state("f", "running")
    assert hold.harness_busy() == (True, "run f (proj) is on task 1 of 2")


def test_hold_counts_only_while_an_updater_holds_the_lock():
    """No expiry: the hold file counts only while HOME/update/lock is held (a killed updater's lock dies with it)."""
    hold.request_hold("update to v9.1")
    assert not hold.hold_requested() and hold.hold_info() is None     # file, but no updater: no hold
    with update_running():
        assert hold.hold_requested()
        info = hold.hold_info()
        assert info["why"] == "update to v9.1" and isinstance(info["at"], float)
    assert not hold.hold_requested()                                   # the updater died: runs go on
    with update_running():
        hold.release_hold()
        assert not hold.hold_requested() and hold.hold_info() is None
        (paths.home() / "update" / "hold").write_text("not json")
        assert hold.hold_info() == {"why": "update", "at": 0}           # damaged file still holds


def test_lock_held_probe_is_read_only():
    lock = hold.lock_file()
    assert not hold.lock_held() and not lock.exists()                  # missing = not held, never created
    with update_running():
        assert hold.lock_held()
    assert not hold.lock_held()
    lock.chmod(0o444)
    assert not hold.lock_held()


def test_leftover_held_is_cleared_without_a_hold(tmp_path, project, lib, adapters):
    """A run restarted while it was held (state says held) goes on and is no longer marked held."""
    run_dir = start(tmp_path)
    state.update(run_dir, lambda s: s["current"].__setitem__("held", True))
    Runner(adapters, lib)._hold_point(run_dir)
    assert state.load(run_dir)["current"]["held"] is False


def test_hold_point_on_state_without_current(tmp_path, project, lib, adapters):
    """Old state files may lack `current`: the hold point must not raise KeyError."""
    run_dir = start(tmp_path)
    st = state.load(run_dir)
    st.pop("current", None)
    atomic.write_json(run_dir / "state.json", st)
    adapters.clock.sleep = lambda s: hold.release_hold()
    hold.request_hold("update")
    with update_running():
        Runner(adapters, lib)._hold_point(run_dir)
    assert state.load(run_dir)["current"]["held"] is False
