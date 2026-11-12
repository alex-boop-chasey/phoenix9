"""The Verify step: scopes, the fresh checkout, test-report.json, redaction and the Verify-off fallback."""
import json
import shutil
from pathlib import Path

import pytest

from helpers import scripted
from helpers.scripted import on
from helpers.stepunit import load, make_ctx, make_work, write
from phoenix9 import checklock, paths, runs, scrub
from phoenix9.runner import Runner
from phoenix9.stepctx import StepResult
from test_step_builder import SPEC, git, project  # noqa: F401  (project is a fixture)

mod = load("verify")
DATA = Path(__file__).parent / "data" / "reports"
FILES = ["tests/phoenix/task-1/test_1.py"]


def out_mount(argv):
    """The host folder mounted at /out in a docker argv ('' when none)."""
    for a in argv:
        if a.startswith("type=bind,") and ",dst=/out" in a:
            return a.split("src=", 1)[1].split(",", 1)[0]
    return ""


def src_mount(argv):
    """The host folder mounted at /workspace."""
    for a in argv:
        if a.startswith("type=bind,") and ",dst=/workspace" in a:
            return a.split("src=", 1)[1].split(",", 1)[0]
    return ""


@pytest.fixture
def work(tmp_path):
    return make_work(tmp_path)


def script_reports(adapters, *samples):
    """Make each docker run drop the next sample (file name in /out, sample name) into its /out mount."""
    fake, real_run, queue = adapters.docker, adapters.docker.run, list(samples)

    def run(argv, *args, **kwargs):
        out = out_mount(argv)
        if out and queue:
            name, sample = queue.pop(0)
            if sample:
                shutil.copy(DATA / sample, Path(out) / name)
        return real_run(argv, *args, **kwargs)
    fake.run = run


def ctx_for(tmp_path, adapters, work, scope="task", things=None, done_when=()):
    ctx = make_ctx(tmp_path, adapters, work, "verify")
    ctx.step.settings["scope"] = scope
    ctx.task["done_when"] = list(done_when)
    ctx.things = things if things is not None else {"checks": FILES}
    return ctx


def test_verify_task_scope_runs_task_checks_only(tmp_path, adapters, work):
    write(work, {FILES[0]: "x\n"})
    ctx = ctx_for(tmp_path, adapters, work)
    checklock.lock(ctx.run.folder, 1, work, FILES)
    script_reports(adapters, ("pytest.xml", "pytest-pass.xml"))
    res = mod.run(ctx)
    assert res.status == "pass", res.reasons
    assert len(adapters.docker.argvs) == 1
    argv = " ".join(adapters.docker.argvs[0])
    assert FILES[0] in argv and "--junitxml=/out/pytest.xml" in argv


def test_verify_full_scope_runs_suite_too(tmp_path, adapters, work):
    write(work, {FILES[0]: "x\n"})
    ctx = ctx_for(tmp_path, adapters, work, scope="full")
    checklock.lock(ctx.run.folder, 1, work, FILES)
    script_reports(adapters, ("pytest.xml", "pytest-pass.xml"), ("pytest.xml", "pytest-pass.xml"))
    res = mod.run(ctx)
    assert res.status == "pass", res.reasons
    assert len(adapters.docker.argvs) == 2
    first, second = (" ".join(a) for a in adapters.docker.argvs)
    assert "python3 -m pytest -q --junitxml" in first and FILES[0] not in first
    assert FILES[0] in second


def test_verify_uses_fresh_checkout(tmp_path, adapters, work):
    write(work, {FILES[0]: "x\n", "new.txt": "uncommitted\n"})
    seen = {}

    def spy(argv, *a, **k):
        seen["src"] = src_mount(argv)
        seen["has_new"] = (Path(seen["src"]) / "new.txt").read_text()
        return 0
    ctx = ctx_for(tmp_path, adapters, work, things={"checks": "spec-done-when"},
                  done_when=[{"text": "`true`", "command": "true"}])
    adapters.docker.run = spy
    res = mod.run(ctx)
    assert res.status == "pass", res.reasons
    assert seen["src"] != str(work.resolve()) and seen["has_new"] == "uncommitted\n"
    assert not Path(seen["src"]).exists()                      # removed afterwards
    assert "verify-checkout" not in git(work, "worktree", "list")


def test_verify_produces_test_report_json(tmp_path, adapters, work):
    write(work, {FILES[0]: "x\n"})
    ctx = ctx_for(tmp_path, adapters, work)
    checklock.lock(ctx.run.folder, 1, work, FILES)
    script_reports(adapters, ("pytest.xml", "pytest-pass.xml"))
    res = mod.run(ctx)
    path = Path(res.produces["test-report"])
    assert path == ctx.run.folder / "tasks/1/attempt-1/verify/test-report.json"
    data = json.loads(path.read_text())
    assert data["ok"] is True and data["passed"] == 1 and data["reader"] == "pytest-junit"


def test_verify_failing_report_fails_with_feedback(tmp_path, adapters, work):
    write(work, {FILES[0]: "x\n"})
    ctx = ctx_for(tmp_path, adapters, work)
    checklock.lock(ctx.run.folder, 1, work, FILES)
    script_reports(adapters, ("pytest.xml", "pytest-mixed.xml"))
    adapters.docker.outputs.append("FAILED test_bad\n")
    res = mod.run(ctx)
    assert res.status == "fail" and "2 failed" in res.reasons[0] and "FAILED test_bad" in res.reasons[0]


def test_verify_missing_report_fails(tmp_path, adapters, work):
    write(work, {FILES[0]: "x\n"})
    ctx = ctx_for(tmp_path, adapters, work)
    checklock.lock(ctx.run.folder, 1, work, FILES)
    res = mod.run(ctx)
    assert res.status == "fail" and "produced no pytest-junit report" in res.reasons[0]


def test_reports_redacted(tmp_path, adapters, work, monkeypatch):
    monkeypatch.setattr(scrub, "_GLOBAL", scrub.Scrubber())
    scrub.add_secrets(["hunter2-hunter2"])
    write(work, {FILES[0]: "x\n"})
    ctx = ctx_for(tmp_path, adapters, work)
    checklock.lock(ctx.run.folder, 1, work, FILES)
    script_reports(adapters, ("pytest.xml", "pytest-mixed.xml"))
    real = adapters.docker.run

    def leaky(argv, *a, **k):
        rc = real(argv, *a, **k)
        (Path(out_mount(argv)) / "pytest.xml").write_text(
            (DATA / "pytest-pass.xml").read_text().replace("test_ok", "hunter2-hunter2"))
        return rc
    adapters.docker.run = leaky
    mod.run(ctx)
    stashed = ctx.run.folder / "tasks/1/attempt-1/verify/checks/pytest.xml"
    assert "hunter2-hunter2" not in stashed.read_text() and "[secret]" in stashed.read_text()


def test_verify_broken_lock_fails(tmp_path, adapters, work):
    write(work, {FILES[0]: "x\n"})
    ctx = ctx_for(tmp_path, adapters, work)
    checklock.lock(ctx.run.folder, 1, work, FILES)
    write(work, {FILES[0]: "changed\n"})
    res = mod.run(ctx)
    assert res.status == "fail" and adapters.docker.argvs == []


# ---- through the runner: Quick (Verify on) and Simple (Verify off)
REPO = Path(__file__).parents[1]


def make_runner(root, adapters, preset_toml):
    """A scripted library with the real Verify step and a scripted 'reviewer' that needs test-report."""
    steps = {k: v for k, v in scripted.STEPS.items() if k != "checks"}
    steps["reviewer"] = dict(level="task", order=75, needs=["test-report"], produces=[])
    scripted.make_library(root, steps)
    shutil.copytree(REPO / "steps" / "verify", root / "steps" / "verify", dirs_exist_ok=True)
    shutil.copytree(REPO / "profiles", root / "profiles")
    (root / "presets" / "quick.toml").write_text(preset_toml)
    return Runner(adapters, root)


def start(tmp_path):
    f = tmp_path / "spec.md"
    f.write_text(SPEC)
    return runs.create_run("proj", f, None)


def test_quick_run_gives_next_step_the_report_path(tmp_path, adapters, project):
    scripted.reset()
    runner = make_runner(tmp_path / "lib", adapters, 'title = "Quick"\n[steps.verify]\non = true\nscope = "task"\n')
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    got = scripted.calls("reviewer", 1)[0]["things"]["test-report"]
    expected = run_dir / "tasks/1/attempt-1/verify/test-report.json"
    assert Path(got) == expected and json.loads(expected.read_text())["ok"] is True
    assert adapters.docker.argvs and "python3 a.py" in " ".join(adapters.docker.argvs[0])
    scripted.reset()


def test_test_report_fallback_from_exit_codes(tmp_path, adapters, project):
    scripted.reset()
    runner = make_runner(tmp_path / "lib", adapters, 'title = "Simple"\n[steps.verify]\non = false\n')
    on("acceptance", 1, None, lambda ctx: StepResult("pass", produces={
        "exit-codes": [{"command": "python3 a.py", "exit_code": 0}]}))
    run_dir = start(tmp_path)
    runner.drive(run_dir)
    got = scripted.calls("reviewer", 1)[0]["things"]["test-report"]
    assert isinstance(got, dict) and got["ok"] is True and got["reader"] == "exit-codes-only"
    assert adapters.docker.argvs == []
    scripted.reset()


def test_fallback_report_counts_exit_codes(tmp_path, adapters, work):
    from phoenix9 import reports
    ctx = ctx_for(tmp_path, adapters, work, things={
        "exit-codes": [{"command": "a", "exit_code": 0}, {"command": "b", "exit_code": 1}]})
    data = reports.fallback_report(ctx)
    assert data["ok"] is False and data["passed"] == 1 and data["failed"] == 1 and data["first_failed"] == "b"
    ctx.things = {"exit-codes": [{"command": "a", "exit_code": 0}]}
    assert reports.fallback_report(ctx)["ok"] is True


def test_verify_runs_each_sh_check_on_its_own(tmp_path, adapters, work):
    sh = ["tests/phoenix/r/task-1/1-a.sh", "tests/phoenix/r/task-1/2-b.sh"]
    write(work, {sh[0]: "exit 0\n", sh[1]: "exit 1\n"})
    ctx = make_ctx(tmp_path, adapters, work, "verify", profile="platform")
    ctx.step.settings["scope"] = "task"
    ctx.things = {"checks": sh}
    checklock.lock(ctx.run.folder, 1, work, sh)
    adapters.docker.exit_codes += [0, 1]
    res = mod.run(ctx)
    assert len(adapters.docker.argvs) == 2
    assert sh[0] in " ".join(adapters.docker.argvs[0]) and sh[1] not in " ".join(adapters.docker.argvs[0])
    assert sh[1] in " ".join(adapters.docker.argvs[1])
    assert res.status == "fail"


def test_task_and_full_scope_reports_say_their_mode(tmp_path, adapters, work):
    write(work, {FILES[0]: "x\n"})
    for scope, mode, runs in (("task", "checks", 1), ("full", "suite", 2)):
        adapters.docker.argvs.clear()
        ctx = ctx_for(tmp_path, adapters, work, scope=scope)
        checklock.lock(ctx.run.folder, 1, work, FILES)
        script_reports(adapters, ("pytest.xml", "pytest-pass.xml"), ("pytest.xml", "pytest-pass.xml"))
        assert mod.run(ctx).status == "pass"
        data = json.loads((ctx.run.folder / "tasks/1/attempt-1/verify/test-report.json").read_text())
        assert data["mode"] == mode and data["picked"] == [] and len(adapters.docker.argvs) == runs
        assert "suite_pending" not in json.loads((ctx.run.folder / "state.json").read_text())
