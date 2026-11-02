"""Tests for the runner: a scripted step library, fake adapters and a temp project with a real git repo."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from phoenix9 import events, gates, paths, runs, state
from phoenix9.runner import Runner, render_prompt

DATA = Path(__file__).parent / "data" / "runlib"
REPO = Path(__file__).resolve().parent.parent

SPEC = """# Spec: Runner test

## Task 1: First thing
Goal: make the first thing work.
Done when:
- the first thing works fine

## Task 2: Second thing
Goal: make the second thing work.
Depends on: 1
Done when:
- the second thing works fine

## Task 3: Third thing
Goal: make the third thing work.
Depends on: none
Done when:
- the third thing works fine
"""


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   check=True, capture_output=True)


@pytest.fixture
def project(tmp_path):
    """A project folder whose code/ is a real git repo with one commit on main."""
    code = paths.projects() / "proj" / "code"
    code.mkdir(parents=True)
    git(code, "init", "-q", "-b", "main")
    (code / "README.md").write_text("hello\n")
    git(code, "add", "-A")
    git(code, "commit", "-q", "-m", "first")
    return paths.projects() / "proj"


@pytest.fixture
def lib(tmp_path):
    """A copy of the scripted library that tests may edit."""
    dest = tmp_path / "lib"
    shutil.copytree(DATA, dest)
    return dest


def make_run(tmp_path, overrides=None, spec=SPEC, script=None):
    """A queued run. These tests check the walk itself, so a failure fails the task at once
    (one try, `continue`); tests/test_attempt_loop.py covers retries and the failure modes."""
    f = tmp_path / "spec.md"
    f.write_text(spec)
    overrides = {"max_tries": 1, "on_failure": "continue", **(overrides or {})}
    run_dir = runs.create_run("proj", f, overrides)
    if script is not None:
        (run_dir / "script.json").write_text(json.dumps(script))
    return run_dir


def calls(run_dir):
    path = run_dir / "calls.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def order(run_dir):
    return [(c["step"], c["task"]) for c in calls(run_dir)]


def test_walks_all_groups_in_order(tmp_path, project, adapters, lib):
    run_dir = make_run(tmp_path)
    assert Runner(adapters, lib).drive(run_dir) == "done"
    expected = [("pick-up", None), ("planner", None), ("branch", None)]
    for n in (1, 2, 3):
        expected += [("builder", n), ("acceptance", n), ("commit", n)]
    expected += [("summary", None)]
    assert order(run_dir) == expected
    st = state.load(run_dir)
    assert st["status"] == "done"
    assert all(t["status"] == "passed" for t in st["tasks"].values())
    assert all(x["status"] == "passed" and x["finished"] for x in st["steps"])
    kinds = [e["type"] for e in events.read(run_dir / "events.jsonl")]
    assert kinds.count("run.step.started") == kinds.count("run.step.finished") == 13
    assert kinds.count("task.started") == kinds.count("task.finished") == 3
    assert kinds[-1] == "run.finished"
    assert (run_dir / "settings.json").is_file() and (run_dir / "plan.json").is_file()
    assert (run_dir / "spec.json").is_file()


def test_things_flow_from_producer_to_consumer(tmp_path, project, adapters, lib):
    script = {"builder:2": {"produces": {"diff": "diff-for-two"}}}
    run_dir = make_run(tmp_path, script=script)
    Runner(adapters, lib).drive(run_dir)
    by = {(c["step"], c["task"]): c["things"] for c in calls(run_dir)}
    assert by[("builder", 1)]["plan"] == "planner:None"
    assert by[("builder", 1)]["baseline"] == "branch:None"
    assert by[("builder", 2)]["task"]["number"] == 2
    assert by[("acceptance", 2)]["diff"] == "diff-for-two"
    assert by[("acceptance", 1)]["diff"] == "builder:1"
    assert by[("commit", 2)]["exit-codes"] == "acceptance:2"
    assert by[("pick-up", None)]["spec"]["title"] == "Spec: Runner test"


def test_switched_off_producer_gives_the_fallback(tmp_path, project, adapters, lib):
    run_dir = make_run(tmp_path, overrides={"steps": {"planner": {"on": False}}})
    assert Runner(adapters, lib).drive(run_dir) == "done"
    assert ("planner", None) not in order(run_dir)
    by = {(c["step"], c["task"]): c["things"] for c in calls(run_dir)}
    assert by[("builder", 1)]["plan"] == "spec-as-written"


def test_failed_task_skips_dependents_and_run_fails(tmp_path, project, adapters, lib):
    script = {"builder:1": {"status": "fail", "reasons": ["it broke"]}}
    run_dir = make_run(tmp_path, script=script)
    assert Runner(adapters, lib).drive(run_dir) == "failed"
    st = state.load(run_dir)
    assert [st["tasks"][n]["status"] for n in "123"] == ["failed", "skipped", "passed"]
    assert st["tasks"]["1"]["failures"] == ["it broke"]
    got = order(run_dir)
    assert ("acceptance", 1) not in got and ("builder", 2) not in got
    assert ("builder", 3) in got and ("summary", None) in got
    line = [x for x in st["steps"] if x["step"] == "builder" and x["task"] == 1][0]
    assert line["status"] == "failed" and line["note"] == "it broke"
    assert events.read(run_dir / "events.jsonl")[-1]["data"]["status"] == "failed"


def test_gate_result_leaves_run_waiting(tmp_path, project, adapters, lib):
    script = {"acceptance:2": {"status": "gate", "gate": {"title": "Look at this", "why": "Check it"}}}
    run_dir = make_run(tmp_path, script=script)
    assert Runner(adapters, lib).drive(run_dir) == "waiting"
    st = state.load(run_dir)
    assert st["status"] == "waiting" and st["tasks"]["2"]["status"] == "waiting"
    (gate,) = gates.list_gates()
    assert gate["title"] == "Look at this" and gate["step"] == "acceptance" and gate["task"] == 2
    assert ("summary", None) not in order(run_dir)
    assert Runner(adapters, lib).drive(run_dir) == "waiting"


def test_gate_step_kind_opens_a_gate(tmp_path, project, adapters, lib):
    run_dir = make_run(tmp_path, overrides={"steps": {"approve": {"on": True}}})
    assert Runner(adapters, lib).drive(run_dir) == "waiting"
    (gate,) = gates.list_gates()
    assert gate["kind"] == "step" and gate["step"] == "approve"


def test_drive_twice_resumes_without_repeating_passed_steps(tmp_path, project, adapters, lib):
    script = {"acceptance:2": {"status": "fail", "reasons": ["flaky"]}}
    run_dir = make_run(tmp_path, script=script)
    runner = Runner(adapters, lib)
    # Simulate a crash: the runner stopped partway, with task 1 done, task 2's attempt still going
    # (no result.json yet, its failed acceptance line not finished) and the run still running.
    st = runner.drive(run_dir)
    assert st == "failed"
    state.set_status(run_dir, "running")
    state.set_task(run_dir, 2, status="running")
    (run_dir / "tasks" / "2" / "attempt-1" / "result.json").unlink()
    (run_dir / "script.json").write_text("{}")
    first = len(calls(run_dir))
    assert runner.drive(run_dir) == "done"
    again = order(run_dir)[first:]
    assert again == [("acceptance", 2), ("commit", 2)]
    assert [c["step"] for c in calls(run_dir)].count("pick-up") == 1
    assert [c["step"] for c in calls(run_dir)].count("builder") == 3


def test_resume_after_things_were_saved(tmp_path, project, adapters, lib):
    run_dir = make_run(tmp_path)
    runner = Runner(adapters, lib)
    runner.drive(run_dir)
    saved = json.loads((run_dir / "things.json").read_text())
    assert saved["commit"] == "commit:3" and saved["baseline"] == "branch:None"


def test_broken_run_py_is_a_failed_step_with_a_reason(tmp_path, project, adapters, lib):
    (lib / "steps" / "builder" / "run.py").write_text("raise RuntimeError('boom at import')\n")
    run_dir = make_run(tmp_path)
    assert Runner(adapters, lib).drive(run_dir) == "failed"
    st = state.load(run_dir)
    assert "boom at import" in st["tasks"]["1"]["failures"][0]
    assert st["tasks"]["1"]["status"] == "failed"
    line = [x for x in st["steps"] if x["step"] == "builder"][0]
    assert line["status"] == "failed" and "could not be loaded" in line["note"]


def test_step_that_crashes_is_a_failed_step(tmp_path, project, adapters, lib):
    (lib / "steps" / "builder" / "run.py").write_text("def run(ctx):\n    raise ValueError('bad day')\n")
    run_dir = make_run(tmp_path)
    assert Runner(adapters, lib).drive(run_dir) == "failed"
    assert "bad day" in state.load(run_dir)["tasks"]["1"]["failures"][0]


def test_real_start_steps(tmp_path, project, adapters, lib):
    for name in ("pick-up", "spec-check", "branch"):
        dest = lib / "steps" / name
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(REPO / "steps" / name, dest)
    (lib / "profiles" / "py").mkdir(parents=True)
    (lib / "profiles" / "py" / "profile.toml").write_text(
        'image = "img:1"\n\n[test]\ncmd = "pytest -q"\n')
    (project / "phoenix.toml").write_text('profile = "py"\n')
    run_dir = make_run(tmp_path)
    final = Runner(adapters, lib).drive(run_dir)
    assert final == "done", events.read(run_dir / "events.jsonl")[-1]
    work = paths.work("proj", run_dir.name)
    assert (work / "README.md").is_file()
    assert json.loads((run_dir / "spec.json").read_text())["title"] == "Spec: Runner test"
    baseline = json.loads((run_dir / "baseline.json").read_text())
    assert baseline["ran"] and baseline["passed"] and baseline["command"] == "pytest -q"
    assert any("pytest -q" in " ".join(a) for a in adapters.docker.argvs)
    assert [e["type"] for e in events.read(run_dir / "events.jsonl")].count("run.started") == 1


def test_spec_check_fails_a_bad_spec(tmp_path, project, adapters, lib):
    shutil.rmtree(lib / "steps" / "pick-up")
    shutil.copytree(REPO / "steps" / "pick-up", lib / "steps" / "pick-up")
    shutil.copytree(REPO / "steps" / "spec-check", lib / "steps" / "spec-check")
    run_dir = make_run(tmp_path, spec="# Spec: Bad\n\n## Task 1: Only\nGoal: x\n")
    assert Runner(adapters, lib).drive(run_dir) == "failed"
    st = state.load(run_dir)
    assert st["tasks"]["1"]["status"] == "skipped"
    line = [x for x in st["steps"] if x["step"] == "spec-check"][0]
    assert line["status"] == "failed" and line["note"]
    assert not (run_dir / "spec.json").exists()


def add_ai_step(lib, after=None):
    d = lib / "steps" / "reviewer"
    d.mkdir()
    (d / "step.toml").write_text(
        'name = "reviewer"\ntitle = "Reviewer"\nkind = "ai"\nlevel = "task"\norder = 70\n'
        'needs = ["task", "worktree", "diff"]\nproduces = []\ndefault = "on"\n\n'
        '[ai]\nmodel = "claude-test"\nmax_turns = 7\ntimeout = 5\n')
    (d / "prompt.md").write_text("Review {{task}} of {{spec_title}}.\nChecks:\n{{checks}}\nExtra: {{extra}}\n")
    (d / "run.py").write_text(after or "def before(ctx):\n    return {'extra': 'EXTRA'}\n")


def test_ai_step_renders_prompt_and_launches_session(tmp_path, project, adapters, lib):
    add_ai_step(lib)
    shutil.rmtree(lib / "steps" / "branch")        # the worktree comes from the real step in this test
    shutil.copytree(REPO / "steps" / "branch", lib / "steps" / "branch")
    run_dir = make_run(tmp_path, spec=SPEC.split("## Task 2")[0])
    assert Runner(adapters, lib).drive(run_dir) == "done"
    (call,) = [c for c in adapters.claude.calls if c[0] == "launch"]
    kw = call[2]
    assert kw["ai"]["model"] == "claude-test" and kw["ai"]["max_turns"] == 7
    prompt = Path(kw["prompt_file"]).read_text()
    assert "Review Task 1: First thing" in prompt and "of Spec: Runner test." in prompt
    assert "- the first thing works fine" in prompt and "Extra: EXTRA" in prompt
    assert Path(kw["workspace"]) == paths.work("proj", run_dir.name)
    assert state.load(run_dir)["usage"]["sessions"] == 1


def test_ai_step_fails_when_session_is_not_ok_and_after_can_judge(tmp_path, project, adapters, lib):
    add_ai_step(lib)
    shutil.rmtree(lib / "steps" / "branch")
    shutil.copytree(REPO / "steps" / "branch", lib / "steps" / "branch")
    adapters.claude.sessions.append({"kind": "error"})
    run_dir = make_run(tmp_path, spec=SPEC.split("## Task 2")[0])
    assert Runner(adapters, lib).drive(run_dir) == "failed"
    assert "error" in state.load(run_dir)["tasks"]["1"]["failures"][0]
    after = ("from phoenix9.stepctx import StepResult\n"
             "def after(ctx, session):\n    return StepResult('pass' if (ctx.worktree / 'ok.txt').exists() else 'fail', ['no ok.txt'])\n")
    add_ai_step_dir = lib / "steps" / "reviewer" / "run.py"
    add_ai_step_dir.write_text(after)
    adapters.claude.sessions.append({"kind": "error", "files": {"ok.txt": "x"}})
    run_dir = make_run(tmp_path, spec=SPEC.split("## Task 2")[0])
    assert Runner(adapters, lib).drive(run_dir) == "done"


def test_render_prompt_keeps_unknown_names():
    assert render_prompt("a {{x}} b {{y}}", {"x": "1"}) == "a 1 b {{y}}"
