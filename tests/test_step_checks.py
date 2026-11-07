"""Check locking, the Check-writer step and the Red check step (real steps, fake claude/docker, real temp git)."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from helpers import scripted
from helpers.scripted import calls, fail, on
from phoenix9 import aistep, checklock, paths, runs, settings, state
from phoenix9.runner import Runner
from phoenix9.stepctx import ProjectInfo, RunInfo, StepContext, StepInfo

REPO = Path(__file__).resolve().parents[1]
SPEC = """# Spec: Tiny tool

## About
A tiny tool for tests.

## Task 1: Add a
Goal: make a.py.
Done when:
- `python3 a.py`
- it is documented
"""
GOOD = {"tests/phoenix/task-1/test_1.py": "assert False\n", "tests/phoenix/task-1/test_2.py": "assert False\n"}
# what a scripted check writer writes in a real run: the fake claude fills in {run_id}
RUN_GOOD = {k.replace("tests/phoenix/", "tests/phoenix/{run_id}/"): v for k, v in GOOD.items()}


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True, text=True).stdout


def load(step):
    spec = importlib.util.spec_from_file_location(f"{step}_run", REPO / "steps" / step / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def project():
    code = paths.projects() / "proj" / "code"
    code.mkdir(parents=True)
    git(code, "init", "-q", "-b", "main")
    (code / "README.md").write_text("hello\n")
    git(code, "add", "-A")
    git(code, "commit", "-q", "-m", "first")
    (paths.projects() / "proj" / "phoenix.toml").write_text('profile = "python-script"\n')
    return paths.projects() / "proj"


def make_lib(root) -> Path:
    steps = {k: v for k, v in scripted.STEPS.items() if k != "checks"}
    scripted.make_library(root, steps)
    for name in ("check-writer", "red-check", "builder"):
        shutil.rmtree(root / "steps" / name, ignore_errors=True)
    for name in ("check-writer", "red-check"):
        shutil.copytree(REPO / "steps" / name, root / "steps" / name)
    # the scripted builder stays: it fails or passes as scripted
    scripted.make_library(root, {"builder": scripted.STEPS["builder"]})
    shutil.copytree(REPO / "profiles", root / "profiles")
    return root


def start(tmp_path, **overrides) -> Path:
    f = tmp_path / "spec.md"
    f.write_text(SPEC)
    overrides.setdefault("steps", {"check-writer": {"on": True}})
    return runs.create_run("proj", f, overrides)


@pytest.fixture
def runner(tmp_path, adapters, project):
    scripted.reset()
    yield Runner(adapters, make_lib(tmp_path / "lib"))
    scripted.reset()


def run_ctx(tmp_path, project, adapters, work, run_dir, **extra):
    profile = settings.load_profile(REPO, "python-script")
    task = {"number": 1, "title": "Add a", "goal": "make a.py",
            "done_when": [{"text": "it works", "command": None}, {"text": "`true`", "command": "true"}]}
    return StepContext(
        project=ProjectInfo("proj", project, project / "code", {"max_tries": 3}, profile),
        run=RunInfo("r", run_dir, {"title": "T", "about": "About it"}),
        step=StepInfo("check-writer", "ai"), task=task, attempt=1, worktree=work,
        things=extra.get("things", {}), adapters=adapters, emit=lambda *a, **k: None, log=lambda t: None)


@pytest.fixture
def work(tmp_path):
    w = tmp_path / "work"
    w.mkdir()
    git(w, "init", "-q", "-b", "main")
    (w / "README.md").write_text("x\n")
    git(w, "add", "-A")
    git(w, "commit", "-q", "-m", "first")
    return w


def write(work, files):
    for name, text in files.items():
        (work / name).parent.mkdir(parents=True, exist_ok=True)
        (work / name).write_text(text)


# ---------------------------------------------------------------- locking
def test_lock_and_verify_unchanged(tmp_path, work):
    write(work, GOOD)
    data = checklock.lock(tmp_path / "run", 1, work, list(GOOD))
    assert sorted(data["files"]) == sorted(GOOD)
    assert checklock.verify(tmp_path / "run", 1, work) == []
    assert sorted(checklock.locked_paths(tmp_path / "run")) == sorted([*GOOD, "tests/phoenix/task-1/"])


def test_verify_reports_changed_deleted_added(tmp_path, work):
    write(work, GOOD)
    checklock.lock(tmp_path / "run", 1, work, list(GOOD))
    (work / "tests/phoenix/task-1/test_1.py").write_text("assert True\n")
    (work / "tests/phoenix/task-1/test_2.py").unlink()
    write(work, {"tests/phoenix/task-1/test_3.py": "x\n"})
    text = "\n".join(checklock.verify(tmp_path / "run", 1, work))
    assert "test_1.py was changed" in text and "test_2.py was deleted" in text and "test_3.py" in text


def test_task_checks_dir_is_per_run():
    assert checklock.task_checks_dir({"checks_dir": "tests/phoenix"}, "run-a", 1) == "tests/phoenix/run-a/task-1"
    assert checklock.task_checks_dir({"checks_dir": "/checks/phoenix/"}, "run-a", 2) == "checks/phoenix/run-a/task-2"
    assert checklock.task_checks_dir({}, "run-b", 3) == "tests/phoenix/run-b/task-3"
    assert checklock.run_checks_dir({}, "run-b") == "tests/phoenix/run-b"
    for bad in ("", ".", "..", "a/b", "a\\b"):
        with pytest.raises(ValueError):
            checklock.task_checks_dir({}, bad, 1)


def test_two_runs_with_task_1_never_collide(tmp_path, work):
    test = {"checks_dir": "tests/phoenix"}
    first = {f"{checklock.task_checks_dir(test, 'run-a', 1)}/{n}": t for n, t in [("test_1.py", "a\n")]}
    write(work, first)
    checklock.lock(tmp_path / "a", 1, work, list(first))
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "run a merged")      # the first build is in main now
    second = {f"{checklock.task_checks_dir(test, 'run-b', 1)}/{n}": t
              for n, t in [("test_1.py", "b\n"), ("test_2.py", "b\n")]}
    write(work, second)
    checklock.lock(tmp_path / "b", 1, work, list(second))
    assert checklock.verify(tmp_path / "b", 1, work) == []
    assert checklock.verify(tmp_path / "a", 1, work) == []
    assert not any("run-a" in p for p in checklock.locked_paths(tmp_path / "b"))


def test_per_run_lock_still_catches_changes_in_its_own_folder(tmp_path, work):
    test = {"checks_dir": "tests/phoenix"}
    folder = checklock.task_checks_dir(test, "run-b", 1)
    write(work, {"tests/phoenix/run-a/task-1/test_1.py": "a\n"})
    write(work, {f"{folder}/test_1.py": "b\n", f"{folder}/test_2.py": "b\n"})
    checklock.lock(tmp_path / "b", 1, work, [f"{folder}/test_1.py", f"{folder}/test_2.py"])
    (work / folder / "test_1.py").write_text("changed\n")
    write(work, {f"{folder}/test_3.py": "x\n", "tests/phoenix/run-a/task-1/test_9.py": "x\n"})
    text = "\n".join(checklock.verify(tmp_path / "b", 1, work))
    assert f"{folder}/test_1.py was changed" in text
    assert f"A file was added to the locked checks: {folder}/test_3.py" in text
    assert "run-a" not in text


def test_manifest_lives_in_run_folder_not_worktree(tmp_path, work):
    write(work, GOOD)
    checklock.lock(tmp_path / "run", 1, work, list(GOOD))
    assert json.loads((tmp_path / "run/tasks/1/checks.lock.json").read_text())["files"]
    assert "checks.lock" not in git(work, "ls-files", "-o", "--exclude-standard")
    assert not list(work.rglob("checks.lock.json"))


# ---------------------------------------------------------------- check-writer prompt
def test_checkwriter_prompt_no_unfilled_placeholders(tmp_path, adapters, project, work):
    mod = load("check-writer")
    template = (REPO / "steps" / "check-writer" / "prompt.md").read_text()
    for name in sorted(p.name for p in (REPO / "profiles").iterdir() if p.is_dir()):
        profile = settings.load_profile(REPO, name)
        ctx = run_ctx(tmp_path, project, adapters, work, tmp_path / "run")
        ctx.project.profile = profile
        text = aistep.render(template, mod.before(ctx))
        assert "{{" not in text and profile["test"]["checks_dir"] + "/r/task-1/" in text


# ---------------------------------------------------------------- check-writer in a run
def worktree(run_dir):
    st = state.load(run_dir)
    return paths.work(st["project"], st["run_id"])


def session(files, text="CHECKS DONE"):
    return {"files": files, "text": text}


def test_checkwriter_accepts_only_checks_dir(tmp_path, runner):
    runner.adapters.claude.sessions += [session({**RUN_GOOD, "src/x.py": "x = 1\n"})]
    run_dir = start(tmp_path, max_tries=1)
    runner.drive(run_dir)
    line = next(s for s in state.load(run_dir)["steps"] if s["step"] == "check-writer")
    assert line["status"] == "failed"
    assert "src/x.py" in json.dumps(line) or "src/x.py" in json.dumps(state.load(run_dir))
    assert not (run_dir / "tasks/1/checks.lock.json").exists()


def test_checkwriter_commits_and_locks(tmp_path, runner):
    runner.adapters.claude.sessions += [session(RUN_GOOD)]
    runner.adapters.docker.exit_codes += [1]
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    work = worktree(run_dir)
    body = git(work, "log", "-30", "--format=%B")
    assert "Checks for task 1" in body and "Phoenix-Task: 1" in body and "Phoenix-Run:" in body
    lock = json.loads((run_dir / "tasks/1/checks.lock.json").read_text())
    run_id = state.load(run_dir)["run_id"]
    assert sorted(lock["files"]) == sorted(k.format(run_id=run_id) for k in RUN_GOOD)
    assert lock["dir"] == f"tests/phoenix/{run_id}/task-1"
    assert not list(work.rglob("checks.lock.json"))


def test_second_build_ignores_checks_left_in_main_by_earlier_builds(tmp_path, runner, project):
    """Agent build 1b: an earlier build's task-1 checks were merged into main and broke the next lock."""
    code = project / "code"
    write(code, {"tests/phoenix/task-1/1-transcript-tests-pass.sh": "old layout\n",
                 "tests/phoenix/20261106-000000-earlier/task-1/test_1.py": "earlier run\n"})
    git(code, "add", "-A")
    git(code, "commit", "-q", "-m", "an earlier build, merged")
    runner.adapters.claude.sessions += [session(RUN_GOOD)]
    runner.adapters.docker.exit_codes += [1]
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    steps = state.load(run_dir)["steps"]
    assert [s["status"] for s in steps if s["step"] == "check-writer"] == ["passed"]
    assert "A file was added" not in json.dumps(state.load(run_dir))
    run_id = state.load(run_dir)["run_id"]
    assert json.loads((run_dir / "tasks/1/checks.lock.json").read_text())["dir"] == f"tests/phoenix/{run_id}/task-1"


def test_checkwriter_no_checks_fails(tmp_path, runner):
    runner.adapters.claude.sessions += [session({})]
    run_dir = start(tmp_path, max_tries=1)
    runner.drive(run_dir)
    assert "The check writer wrote no checks" in json.dumps(state.load(run_dir))


# ---------------------------------------------------------------- red check
def red_ctx(tmp_path, project, adapters, work):
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    ctx = run_ctx(tmp_path, project, adapters, work, run_dir, things={"checks": list(GOOD)})
    ctx.run.folder = run_dir
    return ctx


def test_red_check_requires_failure(tmp_path, adapters, project, work):
    mod = load("red-check")
    adapters.docker.exit_codes += [0, 1]
    adapters.docker.outputs += ["all passed", "boom"]
    ctx = red_ctx(tmp_path, project, adapters, work)
    res = mod.run(ctx)
    assert res.status == "fail" and "prove nothing" in res.reasons[0] and "test_1.py" in res.reasons[0]
    assert mod.run(ctx).status == "pass"
    assert (ctx.run.folder / "tasks/1/attempt-1/red-check.txt").read_text() == "boom"


def test_once_steps_not_rerun_on_attempt_2(tmp_path, runner):
    runner.adapters.claude.sessions += [session(RUN_GOOD)]
    runner.adapters.docker.exit_codes += [1]
    on("builder", 1, 1, fail("nope"))
    run_dir = start(tmp_path, max_tries=2)
    runner.drive(run_dir)
    assert len(runner.adapters.claude.calls) == 1
    assert len(calls("builder")) == 2
    assert len(runner.adapters.docker.argvs) == 1
