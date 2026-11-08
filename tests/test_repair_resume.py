"""Tests for resuming a repaired run: the resume step, `phoenix repair resume`, refusals and the runner's next drive."""
import json
import shutil
from pathlib import Path

import pytest
from helpers.repair_runs import make_run

from phoenix9 import atomic, events, git as git_mod, heartbeat, paths, runs, state
from phoenix9.ops import common, repair as ops
from phoenix9.repair import apply as apply_mod, resume, snapshot
from phoenix9.runner import Runner
from phoenix9.watch import all_states, next_run
from test_runner import SPEC, calls, git, order  # noqa: F401  (the scripted library and its helpers)

DATA = Path(__file__).parent / "data" / "runlib"


@pytest.fixture
def lib(tmp_path, monkeypatch):
    """A copy of the scripted library, also the library the repair check reads."""
    dest = tmp_path / "lib"
    shutil.copytree(DATA, dest)
    monkeypatch.setenv("PHOENIX_LIBRARY", str(dest))
    return dest


def failed_run(tmp_path, adapters, lib, script):
    """A real run driven until it failed: task 1 fails, so task 2 is skipped and task 3 passes."""
    code = paths.projects() / "proj" / "code"
    code.mkdir(parents=True)
    git(code, "init", "-q", "-b", "main")
    (code / "README.md").write_text("hello\n")
    git(code, "add", "-A")
    git(code, "commit", "-q", "-m", "first")
    f = tmp_path / "spec.md"
    f.write_text(SPEC)
    run_dir = runs.create_run("proj", f, {"max_tries": 1, "on_failure": "continue"})
    (run_dir / "script.json").write_text(json.dumps(script))
    assert Runner(adapters, lib).drive(run_dir) == "failed"
    git_mod.make_worktree(code, run_dir.name, paths.work("proj", run_dir.name))    # the scripted branch step makes none
    head = git_mod.head(paths.work("proj", run_dir.name))
    state.update(run_dir, lambda s: [t.update(attempt_base=head) for t in s["tasks"].values()])
    return run_dir


def note(tmp_path, run_dir, *steps):
    """Write a repair note for the run."""
    path = tmp_path / "note.md"
    path.write_text(f"# Repair {run_dir.name}\n\nWhy: test\n\n## Steps\n\n" + "\n".join(f"- {s}" for s in steps) + "\n")
    return path


def status(run_dir):
    return state.load(run_dir)["status"]


BROKEN = {"builder:1": {"status": "fail", "reasons": ["it broke"]}}


def test_resume_after_retry_continues_from_task_one(tmp_path, adapters, lib):
    run_dir = failed_run(tmp_path, adapters, lib, BROKEN)
    before = len(calls(run_dir))
    (run_dir / "script.json").write_text("{}")
    out = apply_mod.apply(note(tmp_path, run_dir, "retry task 1", "resume"), "agent")
    assert out["ok"] and not out["rolled_back"], out["refused"]
    st = state.load(run_dir)
    assert st["status"] == "running" and st["current"]["gate"] is None and "error" not in st
    assert st["tasks"]["3"]["status"] == "passed"
    kinds = [e for e in events.read(run_dir / "events.jsonl") if e["type"] == "run.started"]
    assert kinds[-1]["data"]["who"] == "agent"
    assert Runner(adapters, lib).drive(run_dir) == "failed" or status(run_dir) in ("done", "failed")
    new = [c for c in calls(run_dir)[before:]]
    assert ("builder", 1) in [(c["step"], c["task"]) for c in new]
    assert ("builder", 3) not in [(c["step"], c["task"]) for c in new]


def test_resume_after_redo_runs_the_later_tasks_again(tmp_path, adapters, lib):
    run_dir = failed_run(tmp_path, adapters, lib, BROKEN)
    before = len(calls(run_dir))
    (run_dir / "script.json").write_text("{}")
    out = apply_mod.apply(note(tmp_path, run_dir, "redo task 1 from scratch", "resume"), "cli")
    assert out["ok"], out["refused"]
    assert status(run_dir) == "queued"          # a full redo: nothing has started, so it takes its turn in the queue
    assert next_run(all_states())["run_id"] == run_dir.name
    assert Runner(adapters, lib).drive(run_dir) == "done"
    got = [(c["step"], c["task"]) for c in calls(run_dir)[before:]]
    for n in (1, 2, 3):
        assert ("builder", n) in got


def test_resume_is_not_done_without_a_note_or_command(tmp_path, adapters, lib):
    run_dir = failed_run(tmp_path, adapters, lib, BROKEN)
    assert Runner(adapters, lib).drive(run_dir) == "failed"
    assert next_run(all_states()) is None


def test_resume_command_records_everything(tmp_path, adapters, lib):
    run_dir = failed_run(tmp_path, adapters, lib, BROKEN)
    apply_mod.apply(note(tmp_path, run_dir, "retry task 1"), "cli")
    out = ops.resume(run_dir.name, who="alex")
    assert out["status"] == "running" and out["snapshot"] >= 2
    assert status(run_dir) == "running"
    types = [(e["type"], e["data"].get("who")) for e in events.read(run_dir / "events.jsonl")]
    assert ("run.started", "alex") in types and ("repair.applied", "alex") in types
    log = (paths.logs() / "commands.jsonl").read_text()
    assert "repair resume" in log
    assert "Resume the run" in (paths.projects() / "proj" / "notes" / "changelog.md").read_text()


def test_resume_refused_when_the_check_fails(tmp_path, adapters, lib):
    run_dir = failed_run(tmp_path, adapters, lib, BROKEN)
    values = atomic.read_json(run_dir / "settings.json")
    values["no_such_setting"] = 1
    atomic.write_json(run_dir / "settings.json", values)
    with pytest.raises(common.OpsError, match="problems"):
        ops.resume(run_dir.name)
    assert status(run_dir) == "failed"


def test_resume_refused_while_another_run_runs(tmp_path, adapters, lib, monkeypatch):
    run_dir = failed_run(tmp_path, adapters, lib, BROKEN)
    other = paths.runs("other") / "20261108-000000-other"
    other.mkdir(parents=True)
    atomic.write_json(other / "state.json", {"run_id": other.name, "project": "other", "status": "waiting", "tasks": {}})
    with pytest.raises(common.OpsError, match="Another run"):
        ops.resume(run_dir.name)
    assert status(run_dir) == "failed"


def test_resume_refused_while_the_runner_walks_it(tmp_path, adapters, lib):
    run_dir = failed_run(tmp_path, adapters, lib, BROKEN)
    state.set_status(run_dir, "running")
    heartbeat.write(__import__("time").time())
    with pytest.raises(snapshot.RepairRefused, match="Stop it first"):
        resume.resume(run_dir, "cli")


def test_resume_refused_for_a_run_that_is_done_or_queued(tmp_path, adapters, lib):
    run_dir = failed_run(tmp_path, adapters, lib, BROKEN)
    state.set_status(run_dir, "queued")
    assert "only a failed or stopped" in resume.refusal(run_dir)


def test_run_that_never_started_goes_through_the_queue(tmp_path, adapters, lib):
    run_dir = failed_run(tmp_path, adapters, lib, {"pick-up": {"status": "fail", "reasons": ["no"]}})
    out = apply_mod.apply(note(tmp_path, run_dir, "redo task 1 from scratch", "resume"), "cli")
    assert out["ok"], out["refused"]
    assert status(run_dir) == "queued"
    assert next_run(all_states())["run_id"] == run_dir.name


def test_note_step_rolls_back_when_the_run_is_not_resumable(tmp_path, adapters, lib):
    run_dir = failed_run(tmp_path, adapters, lib, BROKEN)
    other = paths.runs("other") / "20261108-000000-other"
    other.mkdir(parents=True)
    atomic.write_json(other / "state.json", {"run_id": other.name, "project": "other", "status": "running", "tasks": {}})
    out = apply_mod.apply(note(tmp_path, run_dir, "retry task 1", "resume"), "cli")
    assert out["rolled_back"] and "Another run" in out["refused"]
    assert status(run_dir) == "failed" and state.load(run_dir)["tasks"]["1"]["status"] == "failed"
