"""The Builder step: prompt filling, the diff it leaves behind, and how sessions that end badly are judged.

Uses the scripted library for every other step, the real steps/builder, fake claude/docker and a real
temp git repo.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

from helpers import scripted
from helpers.scripted import on
from phoenix9 import aistep, events, paths, runs, settings, state, summary
from phoenix9.runner import Runner
from phoenix9.stepctx import StepResult

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


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True, text=True).stdout


def make_lib(root, with_checks=True, red_check=False) -> Path:
    steps = {k: v for k, v in scripted.STEPS.items() if k != "builder" and (with_checks or k != "checks")}
    if red_check:
        steps["red-check"] = dict(level="task", order=20, needs=["checks"], produces=[], settings={"once": True})
    scripted.make_library(root, steps)
    shutil.copytree(REPO / "steps" / "builder", root / "steps" / "builder")
    shutil.copytree(REPO / "profiles", root / "profiles")
    return root


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


@pytest.fixture
def setup(tmp_path, adapters, project):
    scripted.reset()
    yield lambda with_checks=True, red_check=False: Runner(adapters, make_lib(tmp_path / "lib", with_checks, red_check))
    scripted.reset()


def start(tmp_path, **overrides) -> Path:
    f = tmp_path / "spec.md"
    f.write_text(SPEC)
    return runs.create_run("proj", f, overrides or None)


def prompt_of(run_dir, k=1) -> str:
    return (run_dir / "tasks" / "1" / f"attempt-{k}" / "builder-prompt.md").read_text()


def test_prompt_has_no_unfilled_placeholders(tmp_path, adapters, project):
    template = (REPO / "steps" / "builder" / "prompt.md").read_text()
    import importlib.util
    spec = importlib.util.spec_from_file_location("builder_run", REPO / "steps" / "builder" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    task = {"number": 1, "title": "Add a", "goal": "make a.py",
            "done_when": [{"text": "it works", "command": None}, {"text": "`true`", "command": "true"}]}
    from phoenix9.stepctx import ProjectInfo, RunInfo, StepContext, StepInfo
    work = tmp_path / "w"
    work.mkdir()
    git(work, "init", "-q")
    for name in sorted(p.name for p in (REPO / "profiles").iterdir() if p.is_dir()):
        profile = settings.load_profile(REPO, name)
        ctx = StepContext(
            project=ProjectInfo("proj", project, project / "code", {"max_tries": 3}, profile),
            run=RunInfo("r", tmp_path, {"title": "T", "about": "About it"}),
            step=StepInfo("builder", "ai"), task=task, attempt=2, worktree=work,
            things={"checks": ["tests/phoenix/test_a.py"], "failures": ["first reason"]},
            adapters=adapters, emit=lambda *a, **k: None, log=lambda t: None)
        text = aistep.render(template, mod.before(ctx))   # strict: an unfilled placeholder raises
        assert "{{" not in text and "1. first reason" in text
        assert "do NOT run the whole test suite" in text.replace("Do NOT", "do NOT")
        if profile["test"].get("affected_cmd"):
            assert profile["test"]["affected_cmd"] in text and "One exception" not in text
        else:
            assert "the tests that cover the files you changed" in text and "One exception" in text
            assert profile["test"]["cmd"] in text


def test_prompt_failures_listed_on_retry(tmp_path, setup):
    runner = setup()
    runner.adapters.claude.sessions += [
        {"files": {"a.py": "print('hi')\n"}, "text": "STEP DONE"},
        {"files": {"a.py": "print('hi')\n"}, "text": "STEP DONE"}]
    on("acceptance", 1, 1, StepResult("fail", ["checks failed: a.py is wrong"]))
    run_dir = start(tmp_path, max_tries=3)
    runner.drive(run_dir)
    assert "None: this is the first try" in prompt_of(run_dir, 1)
    assert "1. checks failed: a.py is wrong" in prompt_of(run_dir, 2)
    assert "try 2 of 3" in prompt_of(run_dir, 2)


def test_checks_fallback_uses_done_when_commands(tmp_path, setup):
    runner = setup(with_checks=False)
    runner.adapters.claude.sessions += [{"files": {"a.py": "x\n"}, "text": "STEP DONE"}]
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    text = prompt_of(run_dir)
    assert "- `python3 a.py`" in text and "python3 a.py\n```" in text
    assert "1. `python3 a.py`" in text and "2. it is documented" in text


def test_checks_come_from_locked_files(tmp_path, setup):
    runner = setup()
    on("checks", 1, None, StepResult("pass", produces={"checks": ["tests/phoenix/test_a.py"]}))
    runner.adapters.claude.sessions += [{"files": {"a.py": "x\n"}, "text": "STEP DONE"}]
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    text = prompt_of(run_dir)
    assert "- `tests/phoenix/test_a.py`" in text and "python3 -m pytest -q tests/phoenix/test_a.py" in text


def test_builder_read_only_hint_names_this_runs_checks_folder(tmp_path, setup):
    runner = setup()
    runner.adapters.claude.sessions += [{"files": {"a.py": "x\n"}, "text": "STEP DONE"}]
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    run_id = state.load(run_dir)["run_id"]
    assert f"`tests/phoenix/{run_id}/` is read-only for you" in prompt_of(run_dir)


def test_builder_produces_diff_patch(tmp_path, setup):
    runner = setup()
    runner.adapters.claude.sessions += [{"files": {"src/a.py": "print('hi')\n"}, "text": "STEP DONE"}]
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    patch = run_dir / "tasks" / "1" / "attempt-1" / "diff.patch"
    assert "src/a.py" in patch.read_text() and "+print('hi')" in patch.read_text()
    line = [x for x in state.load(run_dir)["steps"] if x["step"] == "builder"][0]
    assert line["status"] == "passed"


def builder_line(run_dir, k=1):
    return [x for x in state.load(run_dir)["steps"] if x["step"] == "builder" and x.get("attempt") == k][0]


def test_builder_empty_diff_fails(tmp_path, setup):
    runner = setup()
    runner.adapters.claude.sessions += [{"text": "I looked around.\nSTEP BLOCKED: no idea"}]
    run_dir = start(tmp_path, max_tries=1, on_failure="continue")
    runner.drive(run_dir)
    line = builder_line(run_dir)
    assert line["status"] == "failed" and "changed no files" in line["note"] and "no idea" in line["note"]


def test_builder_early_end_fails(tmp_path, setup):
    runner = setup()
    runner.adapters.claude.sessions += [{"kind": "timed_out", "text": "tail of the output",
                                         "files": {"a.py": "x\n"}}]
    run_dir = start(tmp_path, max_tries=1, on_failure="continue")
    runner.drive(run_dir)
    note = builder_line(run_dir)["note"]
    assert "ended before it finished (timed_out)" in note and "tail of the output" in note


def test_spec_problem_reason(tmp_path, setup):
    runner = setup()
    runner.adapters.claude.sessions += [{"text": "SPEC_PROBLEM: bullets 1 and 2 contradict"}]
    run_dir = start(tmp_path, max_tries=5)
    assert runner.drive(run_dir) == "waiting"
    assert builder_line(run_dir)["note"] == "SPEC_PROBLEM: bullets 1 and 2 contradict"
    assert state.load(run_dir)["tasks"]["1"]["tries"] == 1


def test_builder_ignores_step_done_claim(tmp_path, setup):
    runner = setup()
    runner.adapters.claude.sessions += [{"text": "All checks pass.\nSTEP DONE"}]
    on("acceptance", 1, 1, StepResult("fail", ["check a failed"]))
    run_dir = start(tmp_path, max_tries=1, on_failure="continue")
    runner.drive(run_dir)
    assert builder_line(run_dir)["status"] == "passed"      # the checks decide, not the claim
    assert state.load(run_dir)["tasks"]["1"]["status"] == "failed"


def test_no_change_passes_when_checks_pass(tmp_path, setup):
    runner = setup()
    runner.adapters.claude.sessions += [{"text": "Already there.\nSTEP DONE"}]
    run_dir = start(tmp_path, max_tries=1)
    runner.drive(run_dir)
    task = state.load(run_dir)["tasks"]["1"]
    assert task["status"] == "passed" and task["note"] == "already done: nothing needed changing"
    assert "already done" in summary.markdown(summary.facts(run_dir))
    assert any(e["type"] == "task.finished" and "already done" in e["data"].get("note", "")
               for e in events.read(run_dir / "events.jsonl"))


def test_no_change_without_checks_fails(tmp_path, setup):
    runner = setup(with_checks=False)
    runner.adapters.claude.sessions += [{"text": "STEP DONE"}]
    text = SPEC.replace("- `python3 a.py`\n- it is documented", "- it is documented")
    f = tmp_path / "spec2.md"
    f.write_text(text)
    run_dir = runs.create_run("proj", f, {"max_tries": 1, "on_failure": "continue"})
    runner.drive(run_dir)
    line = builder_line(run_dir)
    assert line["status"] == "failed" and "changed no files" in line["note"]


def test_no_change_after_red_check_fails(tmp_path, setup):
    runner = setup(red_check=True)
    runner.adapters.claude.sessions += [{"text": "STEP DONE"}]
    run_dir = start(tmp_path, max_tries=1, on_failure="continue")
    runner.drive(run_dir)
    line = builder_line(run_dir)
    assert line["status"] == "failed" and "changed no files" in line["note"]


def test_profile_test_block_validated(tmp_path):
    lib = tmp_path / "lib"
    shutil.copytree(REPO / "profiles", lib / "profiles")
    shutil.copytree(REPO / "steps", lib / "steps")
    assert settings.check_profile(lib, "web") == []
    path = lib / "profiles" / "web" / "profile.toml"
    path.write_text(path.read_text() + 'bogus = "x"\n')
    assert any("test.bogus" in p for p in settings.check_profile(lib, "web"))
    path.write_text(path.read_text().replace('["vitest-json", "playwright-json"]', '["vitest-json", "nope"]')
                    .replace('bogus = "x"\n', ""))
    assert any("unknown report 'nope'" in p for p in settings.check_profile(lib, "web"))


def test_finish_line_reading():
    assert aistep.finish_line("x\nSTEP DONE\n") == ("done", "")
    assert aistep.finish_line("STEP BLOCKED: no key") == ("blocked", "no key")
    assert aistep.finish_line("SPEC_PROBLEM: bad") == ("spec_problem", "bad")
    assert aistep.finish_line("ok") == ("none", "")
    with pytest.raises(ValueError, match="nope"):
        aistep.render("a {{nope}}", {})


def test_prompts_tell_how_to_build_key_shaped_values():
    builder = (REPO / "steps" / "builder" / "prompt.md").read_text()
    assert "build it at run time from harmless pieces" in builder and "test files included, fails the task" in builder
    writer = (REPO / "steps" / "check-writer" / "prompt.md").read_text()
    assert "build it at run time from harmless pieces" in writer
