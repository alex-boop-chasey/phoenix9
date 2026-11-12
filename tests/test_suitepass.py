"""Remembered whole-suite passes: the store, and the Branch and Full suite steps that use it."""
import json

from helpers.stepunit import load, make_ctx, make_work
from phoenix9 import git, paths, suitepass
from phoenix9.git import git as run_git

branch = load("branch")
full_suite = load("full-suite")


def test_hit_and_miss():
    k = suitepass.key("tree1", "pytest", "img", "py")
    assert suitepass.lookup("p", k) is None
    suitepass.remember("p", k, {"step": "x"})
    assert suitepass.lookup("p", k)["facts"] == {"step": "x"}
    assert suitepass.lookup("other", k) is None


def test_key_changes_with_every_part():
    base = suitepass.key("t", "c", "i", "p")
    assert base == suitepass.key("t", "c", "i", "p") and len(base) == 64
    for other in (("t2", "c", "i", "p"), ("t", "c2", "i", "p"), ("t", "c", "i2", "p"), ("t", "c", "i", "p2")):
        assert suitepass.key(*other) != base


def test_corrupt_file_means_nothing_remembered():
    k = suitepass.key("t", "c", "i", "p")
    suitepass.remember("p", k, {})
    suitepass._file("p").write_text("{not json")
    assert suitepass.lookup("p", k) is None
    suitepass.remember("p", k, {})
    assert suitepass.lookup("p", k) is not None


def test_cap_keeps_newest_50():
    for i in range(60):
        suitepass.remember("p", f"k{i}", {})
    assert len(json.loads(suitepass._file("p").read_text())) == 50
    assert suitepass.lookup("p", "k0") is None and suitepass.lookup("p", "k59")


def test_setting_off_means_no_lookups_or_writes(monkeypatch):
    monkeypatch.setattr(suitepass.settings, "remember_suite_passes", lambda: False)
    suitepass.remember("p", "k", {})
    assert not suitepass._file("p").exists()
    monkeypatch.setattr(suitepass.settings, "remember_suite_passes", lambda: True)
    suitepass.remember("p", "k", {})
    monkeypatch.setattr(suitepass.settings, "remember_suite_passes", lambda: False)
    assert suitepass.lookup("p", "k") is None


def test_global_setting_reads_global_toml(tmp_path):
    from phoenix9 import settings
    assert settings.remember_suite_passes() is True
    (paths.config()).mkdir(parents=True, exist_ok=True)
    (paths.config() / "global.toml").write_text("remember_suite_passes = false\n")
    assert settings.remember_suite_passes() is False


# ------------------------------------------------------------- steps
def suite_ctx(tmp_path, adapters):
    ctx = make_ctx(tmp_path, adapters, make_work(tmp_path), "full-suite")
    ctx.task = None
    ctx.project.profile["test"]["report"] = "exit-code"
    return ctx


def test_full_suite_skips_on_a_remembered_pass_and_then_changed_file_runs(tmp_path, adapters):
    ctx = suite_ctx(tmp_path, adapters)
    assert full_suite.run(ctx).status == "pass"          # never tested before: it really runs
    ran = len(adapters.docker.argvs)
    assert ran >= 1
    ctx2 = ctx
    res = full_suite.run(ctx2)
    assert res.status == "pass" and "already passed on exactly this code" in res.reasons[0]
    assert len(adapters.docker.argvs) == ran
    assert json.loads((ctx2.run.folder / "final-report.json").read_text())["ok"] is True
    (ctx2.worktree / "new.txt").write_text("changed\n")   # different files -> a miss, runs again
    assert full_suite.run(ctx2).status == "pass" and len(adapters.docker.argvs) > ran


def test_full_suite_failure_is_not_remembered(tmp_path, adapters):
    ctx = suite_ctx(tmp_path, adapters)
    adapters.docker.exit_codes.append(1)
    assert full_suite.run(ctx).status == "fail"
    assert full_suite.run(ctx).status == "pass" and len(adapters.docker.argvs) == 2


def test_full_suite_runs_for_another_command(tmp_path, adapters):
    ctx = suite_ctx(tmp_path, adapters)
    full_suite.run(ctx)
    ran = len(adapters.docker.argvs)
    ctx.project.profile["test"]["cmd"] += " -x"
    full_suite.run(ctx)
    assert len(adapters.docker.argvs) > ran


def test_branch_skips_on_remembered_pass(tmp_path, adapters):
    work = make_work(tmp_path)
    ctx = make_ctx(tmp_path, adapters, work, "branch")
    target = paths.work(ctx.project.name, ctx.run.id)
    target.parent.mkdir(parents=True, exist_ok=True)
    work.rename(target)                    # Branch finds its worktree already made
    ctx.project.profile["test"]["cmd"] = "pytest -q"
    first = branch.run(ctx).produces["baseline"]
    assert first["ran"] is True and first["passed"] is True
    ran = len(adapters.docker.argvs)
    again = branch.run(ctx).produces["baseline"]
    assert again["ran"] is False and again["passed"] is True and again["remembered"] is True
    assert "already passed on exactly this code" in again["note"]
    assert len(adapters.docker.argvs) == ran


def test_verify_full_scope_remembers_a_pass_for_full_suite(tmp_path, adapters):
    verify = load("verify")
    ctx = make_ctx(tmp_path, adapters, make_work(tmp_path), "verify")
    ctx.step.settings["scope"] = "full"
    ctx.project.profile["test"]["report"] = "exit-code"
    ctx.things["checks"] = []
    assert verify.run(ctx).status == "pass"
    ctx.task = None
    ran = len(adapters.docker.argvs)
    res = full_suite.run(ctx)
    assert res.status == "pass" and "already passed" in res.reasons[0] and len(adapters.docker.argvs) == ran
