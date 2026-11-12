"""Repair, not restart: a failed try keeps the working folder when the next builder can fix it (scripted steps)."""
import pytest

from helpers import scripted
from helpers.scripted import STEPS, calls, fail, on
from helpers.stepunit import git as ugit, load, make_ctx, make_work, write
from phoenix9 import checklock, failmodes, pause, state
from phoenix9.ops import runs as ops_runs
from phoenix9.runner import Runner
from phoenix9.stepctx import StepResult
from test_attempt_loop import ONE, project, start, task, worktree  # noqa: F401  (fixtures and helpers)


def steps(retry="repair"):
    """The scripted steps plus the judging steps of a real plan, with the builder's `retry` set."""
    out = {k: dict(v) for k, v in STEPS.items()}
    out["builder"]["settings"] = {"retry": retry}
    extra = {"diff-rules": 35, "secret-scan": 36, "verify": 65, "reviewer": 70}
    for name, order in extra.items():
        out[name] = dict(level="task", order=order, needs=["worktree"], produces=[])
    return out


def make_runner(adapters, tmp_path, retry="repair"):
    scripted.reset()
    return Runner(adapters, scripted.make_library(tmp_path / "lib", steps(retry)))


def builder_writes(name_by_attempt):
    """A builder script that writes the files given per attempt, and notes what it found on arrival."""
    seen = {}

    def build(ctx):
        seen[ctx.attempt] = sorted(p.name for p in ctx.worktree.glob("*.txt"))
        for name in name_by_attempt.get(ctx.attempt, ()):
            (ctx.worktree / name).write_text(f"{name}\n")
        return StepResult("pass")
    on("builder", 1, None, build)
    return seen


def starts(run_dir):
    return task(run_dir).get("attempt_starts")


@pytest.mark.parametrize("step", ["acceptance", "verify", "reviewer", "secret-scan"])
def test_work_kept_after_a_judging_step_fails(tmp_path, adapters, project, step):
    runner = make_runner(adapters, tmp_path)
    seen = builder_writes({1: ["one.txt"], 2: ["two.txt"]})
    on(step, 1, 1, fail("needs a small fix"))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "done"
    assert seen[2] == ["one.txt"]
    assert starts(run_dir) == {"1": "clean", "2": "kept"}
    assert failmodes.attempt_result(run_dir, 1, 1)["kept"] is True
    assert calls("builder", 1)[1]["failures"] == ["needs a small fix"]


@pytest.mark.parametrize("step", ["diff-rules", "builder"])
def test_work_reset_after_diff_rules_or_builder_fails(tmp_path, adapters, project, step):
    runner = make_runner(adapters, tmp_path)
    seen = builder_writes({1: ["one.txt"]})
    on(step, 1, 1, fail("no good"))
    if step == "builder":
        on("builder", 1, 1, lambda ctx: (ctx.worktree / "one.txt").write_text("x\n") or fail("session failed"))
        on("builder", 1, 2, lambda ctx: StepResult("pass"))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "done"
    assert seen.get(2, []) == [] and starts(run_dir)["2"] == "clean"
    assert failmodes.attempt_result(run_dir, 1, 1)["kept"] is False


def test_last_try_always_starts_clean(tmp_path, adapters, project):
    runner = make_runner(adapters, tmp_path)
    seen = builder_writes({1: ["one.txt"], 2: ["two.txt"]})
    on("reviewer", 1, 1, fail("first note"))
    on("reviewer", 1, 2, fail("second note"))
    run_dir = start(tmp_path, max_tries=3)
    assert runner.drive(run_dir) == "done"
    assert starts(run_dir) == {"1": "clean", "2": "kept", "3": "clean"}
    assert seen[3] == []


def test_two_tries_means_the_second_is_clean(tmp_path, adapters, project):
    runner = make_runner(adapters, tmp_path)
    seen = builder_writes({1: ["one.txt"]})
    on("reviewer", 1, 1, fail("note"))
    run_dir = start(tmp_path, max_tries=2)
    assert runner.drive(run_dir) == "done"
    assert seen[2] == [] and starts(run_dir)["2"] == "clean"


def test_restart_setting_behaves_as_before(tmp_path, adapters, project):
    runner = make_runner(adapters, tmp_path, retry="restart")
    seen = builder_writes({1: ["one.txt"]})
    on("reviewer", 1, 1, fail("note"))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "done"
    assert seen[2] == [] and starts(run_dir)["2"] == "clean"


def test_touched_locked_checks_reset_the_folder(tmp_path, adapters, project, monkeypatch):
    runner = make_runner(adapters, tmp_path)
    seen = builder_writes({1: ["one.txt"]})
    on("acceptance", 1, 1, fail("The locked check x was changed"))
    monkeypatch.setattr(checklock, "verify", lambda *a: ["The locked check x was changed"])
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "done"
    assert seen[2] == [] and starts(run_dir)["2"] == "clean"


def test_attempt_base_stays_at_the_task_start_on_a_kept_try(tmp_path, adapters, project):
    runner = make_runner(adapters, tmp_path)
    builder_writes({1: ["one.txt"]})
    on("reviewer", 1, 1, fail("note"))
    run_dir = start(tmp_path)
    base_seen = []
    on("commit", 1, None, lambda ctx: base_seen.append(task(run_dir)["attempt_base"]) or StepResult("pass"))
    runner.drive(run_dir)
    assert base_seen and base_seen[0] == ugit(worktree(run_dir), "rev-parse", "HEAD").strip()


def test_pause_and_resume_in_the_middle_of_a_kept_try(tmp_path, adapters, project, monkeypatch):
    from phoenix9.ops import common
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    runner = make_runner(adapters, tmp_path)
    seen = builder_writes({1: ["one.txt"], 2: ["two.txt"]})
    on("reviewer", 1, 1, fail("note"))
    plain = scripted.SCRIPT[("builder", 1, None)][0]

    def pausing(ctx):
        out = plain(ctx)
        if ctx.attempt == 2 and not seen.get("paused"):
            seen["paused"] = True
            pause.request(ctx.run.folder, "cli")
        return out
    on("builder", 1, None, pausing)
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "paused"
    assert (worktree(run_dir) / "one.txt").exists() and (worktree(run_dir) / "two.txt").exists()
    ops_runs.resume(run_dir.name)
    assert runner.drive(run_dir) == "done"
    assert starts(run_dir) == {"1": "clean", "2": "kept"} and task(run_dir)["tries"] == 2


def test_no_more_tries_resets_the_kept_work(tmp_path, adapters, project):
    runner = make_runner(adapters, tmp_path)
    builder_writes({1: ["one.txt"], 2: ["one.txt"]})
    on("reviewer", 1, None, fail("the same note"))
    run_dir = start(tmp_path, max_tries=5, on_failure="continue")
    assert runner.drive(run_dir) == "failed"
    assert not (worktree(run_dir) / "one.txt").exists()


def test_commit_after_a_passing_repair_try_has_the_full_change(tmp_path, adapters, project):
    runner = make_runner(adapters, tmp_path)
    builder_writes({1: ["one.txt"], 2: ["two.txt"]})
    on("reviewer", 1, 1, fail("note"))
    on("commit", 1, None, lambda ctx: StepResult("pass", produces={"commit": ctx.adapters.git.commit(
        ctx.worktree, "Task 1", {"Phoenix-Task": "1"})}))
    run_dir = start(tmp_path)
    assert runner.drive(run_dir) == "done"
    files = ugit(worktree(run_dir), "show", "--name-only", "--format=", "HEAD").split()
    assert sorted(files) == ["one.txt", "two.txt"]


# -- the real gates measure the whole change since the task began --------------------------------
def second_try(tmp_path, adapters, step, first_try, second_try_files=None, setup=None):
    """A real step's context on a kept try 2: try 1's files are left in place, try 2 added its own."""
    work = make_work(tmp_path)
    ctx = make_ctx(tmp_path, adapters, work, step)
    if setup:
        setup(ctx, work)
    write(work, first_try)
    state.set_task(ctx.run.folder, 1, tries=2, attempt_starts={"1": "clean", "2": "kept"})
    ctx.attempt = 2
    write(work, second_try_files or {"harmless.txt": "fine\n"})
    return ctx, work


def test_diff_rules_still_catch_a_try_one_problem(tmp_path, adapters):
    ctx, _ = second_try(tmp_path, adapters, "diff-rules", {".env": "KEY=abc\n"})
    result = load("diff-rules").run(ctx)
    assert result.status == "fail" and ".env" in result.reasons[0]


def test_secret_scan_still_catches_a_try_one_secret(tmp_path, adapters):
    ctx, _ = second_try(tmp_path, adapters, "secret-scan",
                        {"t.py": "t = 'ghp_" + "a" * 30 + "'\n"})
    result = load("secret-scan").run(ctx)
    assert result.status == "fail" and "t.py" in result.reasons[0]


def test_acceptance_still_sees_a_try_one_locked_check_edit(tmp_path, adapters):
    files = ["tests/phoenix/task-1/test_1.py"]

    def lock(ctx, work):
        write(work, {files[0]: "x\n"})
        checklock.lock(ctx.run.folder, 1, work, files)
        ugit(work, "add", "-A")
        ugit(work, "commit", "-q", "-m", "checks")
        state.set_task(ctx.run.folder, 1, attempt_base=ugit(work, "rev-parse", "HEAD").strip())
        ctx.things = {"checks": files}
    ctx, _ = second_try(tmp_path, adapters, "acceptance", {files[0]: "changed\n"}, setup=lock)
    result = load("acceptance").run(ctx)
    assert result.status == "fail" and "locked check" in result.reasons[0]


def test_verify_still_picks_tests_for_a_try_one_change(tmp_path, adapters):
    import json
    from test_step_verify import script_reports
    from phoenix9 import settings as _s  # noqa: F401

    def prepare(ctx, work):
        write(work, {"src/a.py": "a = 1\n", "tests/test_a.py": "import a\n"})
        ctx.step.settings.update(scope="affected", suite_every=0)
        ctx.things = {"checks": []}
        ugit(work, "add", "-A")
        ugit(work, "commit", "-q", "-m", "base")
        state.set_task(ctx.run.folder, 1, attempt_base=ugit(work, "rev-parse", "HEAD").strip())
    ctx, _ = second_try(tmp_path, adapters, "verify", {"src/a.py": "a = 2\n"}, {"notes.txt": "x\n"}, setup=prepare)
    script_reports(adapters, ("pytest.xml", "pytest-pass.xml"))
    assert load("verify").run(ctx).status == "pass"
    data = json.loads((ctx.run.folder / "tasks/1/attempt-2/verify/test-report.json").read_text())
    assert data["picked"] == ["tests/test_a.py"]


def test_reviewer_patch_and_prompt_on_a_kept_try(tmp_path, adapters, project):
    from test_step_builder import make_lib, prompt_of
    scripted.reset()
    (project / "phoenix.toml").write_text('profile = "python-script"\n')
    runner = Runner(adapters, make_lib(tmp_path / "lib2"))
    runner.adapters.claude.sessions += [
        {"files": {"src/a.py": "a = 1\n"}, "text": "STEP DONE"},
        {"files": {"src/b.py": "b = 1\n"}, "text": "STEP DONE"}]
    on("acceptance", 1, 1, fail("checks failed: a.py is wrong"))
    run_dir = start(tmp_path, max_tries=3)
    assert runner.drive(run_dir) == "done"
    patch = (run_dir / "tasks/1/attempt-2/diff.patch").read_text()
    assert "src/a.py" in patch and "src/b.py" in patch            # the reviewer reads the whole change
    first, second = prompt_of(run_dir, 1), prompt_of(run_dir, 2)
    assert "Your earlier work is still here" in second and "checks failed: a.py is wrong" in second
    assert "earlier work" not in first and "{{" not in first
    scripted.reset()
