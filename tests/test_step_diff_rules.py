"""The Diff rules step: what the builder may not touch (real step, real temp git repo)."""
import os
import shutil

import pytest

from helpers import scripted
from helpers.scripted import on
from helpers.stepunit import REPO, git, load, make_ctx, make_work, write
from phoenix9 import checklock, paths, runs
from phoenix9.runner import Runner
from phoenix9.stepctx import StepResult

mod = load("diff-rules")


@pytest.fixture
def work(tmp_path):
    return make_work(tmp_path)


def run_step(tmp_path, adapters, work, **settings):
    return mod.run(make_ctx(tmp_path, adapters, work, "diff-rules", settings))


def test_allows_normal_files_and_md(tmp_path, adapters, work):
    write(work, {"src/a.py": "x = 1\n", "docs/notes.md": "hi\n", "README.md": "changed\n"})
    result = run_step(tmp_path, adapters, work)
    assert result.status == "pass" and result.reasons == []
    assert "src/a.py" in (tmp_path / "run/tasks/1/attempt-1/diff-rules.txt").read_text()


@pytest.mark.parametrize("path", [".git/x", ".github/workflows/a.yml", ".env", ".env.local", "CLAUDE.md",
                                  ".claude/settings.json", ".mcp.json"])
def test_denies_each_default(tmp_path, adapters, work, path):
    write(work, {path: "x\n"})
    if path.startswith(".git/"):
        # git itself never lists .git; check the rule on a change record instead
        from phoenix9.git import Change
        bad = adapters.git.check_changes([Change(status="A", path=path, mode="100644")])
        assert bad and path in bad[0]
        return
    result = run_step(tmp_path, adapters, work)
    assert result.status == "fail" and path in result.reasons[0]


def test_denies_symlink(tmp_path, adapters, work):
    os.symlink("/etc/passwd", work / "link")
    result = run_step(tmp_path, adapters, work)
    assert result.status == "fail" and "link" in result.reasons[0] and "symlink" in result.reasons[0]


def test_denies_submodule(tmp_path, adapters, work):
    sub = tmp_path / "sub"
    sub.mkdir()
    git(sub, "init", "-q", "-b", "main")
    (sub / "f").write_text("x\n")
    git(sub, "add", "-A")
    git(sub, "commit", "-q", "-m", "s")
    (work / "vendor").mkdir()
    shutil.copytree(sub, work / "vendor" / "sub")   # a nested repo becomes a submodule entry
    result = run_step(tmp_path, adapters, work)
    assert result.status == "fail" and "vendor/sub" in result.reasons[0]


def test_denies_locked_check_edit(tmp_path, adapters, work):
    write(work, {"tests/phoenix/task-1/test_1.py": "assert False\n"})
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "checks")
    ctx = make_ctx(tmp_path, adapters, work, "diff-rules")
    checklock.lock(ctx.run.folder, 1, work, ["tests/phoenix/task-1/test_1.py"])
    (work / "tests/phoenix/task-1/test_1.py").write_text("assert True\n")
    result = mod.run(ctx)
    text = "\n".join(result.reasons)
    assert result.status == "fail" and "test_1.py" in text and "locked" in text


def test_project_deny_extra(tmp_path, adapters, work):
    write(work, {"secrets/list.txt": "x\n", "src/a.py": "x\n"})
    result = run_step(tmp_path, adapters, work, diff={"deny_extra": ["secrets/*"], "allow_extra": []})
    assert result.status == "fail" and len(result.reasons) == 1 and "secrets/list.txt" in result.reasons[0]


def test_project_allow_extra_cannot_reallow_git_or_symlink(tmp_path, adapters, work):
    os.symlink("/etc/passwd", work / "CLAUDE.md")
    write(work, {".mcp.json": "{}\n"})
    result = run_step(tmp_path, adapters, work, diff={"allow_extra": ["CLAUDE.md", ".mcp.json", ".git*"]})
    text = "\n".join(result.reasons)
    assert result.status == "fail" and "CLAUDE.md" in text and ".mcp.json" not in text   # plain file re-allowed, symlink not
    from phoenix9.git import Change
    bad = adapters.git.check_changes([Change(status="A", path=".git/hooks/x", mode="100644")], allow_extra=[".git/*", "*"])
    assert bad


def test_profile_allow_extra_is_used(tmp_path, adapters, work):
    write(work, {".mcp.json": "{}\n"})
    ctx = make_ctx(tmp_path, adapters, work, "diff-rules")
    ctx.project.profile["diff_allow_extra"] = [".mcp.json"]
    assert mod.run(ctx).status == "pass"


def test_reasons_name_each_path(tmp_path, adapters, work):
    write(work, {".env": "A=1\n", ".github/workflows/ci.yml": "on: push\n", "ok.py": "x\n"})
    result = run_step(tmp_path, adapters, work)
    assert len(result.reasons) == 2
    text = "\n".join(result.reasons)
    assert "Not allowed to change .env (" in text and ".github/workflows/ci.yml" in text and "ok.py" not in text


def test_builder_writing_env_fails_attempt_and_next_prompt_shows_it(tmp_path, adapters):
    code = paths.projects() / "proj" / "code"
    code.mkdir(parents=True)
    git(code, "init", "-q", "-b", "main")
    (code / "README.md").write_text("hello\n")
    git(code, "add", "-A")
    git(code, "commit", "-q", "-m", "first")
    (paths.projects() / "proj" / "phoenix.toml").write_text('profile = "python-script"\n')
    scripted.reset()
    lib = tmp_path / "lib"
    steps = {k: v for k, v in scripted.STEPS.items() if k not in ("builder", "checks")}
    scripted.make_library(lib, steps)
    for name in ("builder", "diff-rules"):
        shutil.copytree(REPO / "steps" / name, lib / "steps" / name)
    shutil.copytree(REPO / "profiles", lib / "profiles")
    adapters.claude.sessions += [{"files": {".env": "KEY=1\n"}, "text": "STEP DONE"},
                                 {"files": {"a.py": "x = 1\n"}, "text": "STEP DONE"}]
    spec = tmp_path / "spec.md"
    spec.write_text("# Spec: T\n\n## About\nx\n\n## Task 1: A\nGoal: g.\nDone when:\n- `true`\n")
    run_dir = runs.create_run("proj", spec, {"max_tries": 2, "steps": {"diff-rules": {"on": True}}})
    Runner(adapters, lib).drive(run_dir)
    attempt1 = (run_dir / "tasks/1/attempt-1")
    assert (attempt1 / "diff-rules.txt").exists()
    prompt = (run_dir / "tasks/1/attempt-2/builder-prompt.md").read_text()
    assert "Not allowed to change .env" in prompt
    scripted.reset()
