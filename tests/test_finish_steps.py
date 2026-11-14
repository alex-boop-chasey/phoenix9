"""The finish steps: Full suite, Summary and Notify."""
import re
import shutil
from pathlib import Path

import pytest

from helpers import scripted
from helpers.scripted import fail, on
from helpers.stepunit import git, load, make_ctx, make_work, write
from phoenix9 import gates, runs, scrub, state
from phoenix9.ops import runs as ops_runs
from phoenix9.runner import Runner
from test_attempt_loop import ONE, THREE, project, start  # noqa: F401  (project is a fixture)

REPO = Path(__file__).resolve().parents[1]
full_suite = load("full-suite")
notify_step = load("notify")


# ------------------------------------------------------------- full suite
def suite_ctx(tmp_path, adapters, profile_change=None):
    ctx = make_ctx(tmp_path, adapters, make_work(tmp_path), "full-suite")
    ctx.task = None
    if profile_change:
        profile_change(ctx.project.profile)
    return ctx


def test_full_suite_runs_suite_command_on_clean_checkout(tmp_path, adapters):
    ctx = suite_ctx(tmp_path, adapters)
    (ctx.worktree / "stray.txt").write_text("uncommitted\n")
    seen = {}

    def spy(argv, *a, **k):
        src = next(x for x in argv if x.startswith("type=bind,") and ",dst=/workspace" in x)
        seen["src"] = Path(src.split("src=", 1)[1].split(",", 1)[0])
        seen["argv"] = " ".join(argv)
        seen["has_readme"] = (seen["src"] / "README.md").exists()
        return 0
    adapters.docker.run = spy
    # an exit-code reader is enough for this test
    ctx.project.profile["test"]["report"] = "exit-code"
    res = full_suite.run(ctx)
    assert res.status == "pass", res.reasons
    assert "python3 -m pytest -q" in seen["argv"] and seen["has_readme"]
    assert seen["src"] != ctx.worktree.resolve() and not seen["src"].exists()
    assert (ctx.run.folder / "final-report.json").exists()
    assert res.produces["test-report"] == str(ctx.run.folder / "final-report.json")
    assert list((ctx.run.folder / "logs" / "full-suite").glob("*.txt"))


def test_full_suite_failure_fails_run(tmp_path, adapters):
    ctx = suite_ctx(tmp_path, adapters)
    ctx.project.profile["test"]["report"] = "exit-code"
    adapters.docker.exit_codes.append(1)
    adapters.docker.outputs.append("FAILED test_x\n")
    res = full_suite.run(ctx)
    assert res.status == "fail" and "FAILED test_x" in res.reasons[0] and "exited 1" in res.reasons[0]
    assert (ctx.run.folder / "final-report.json").exists()


def test_full_suite_failure_makes_run_failed(tmp_path, adapters, project):
    scripted.reset()
    lib = scripted.make_library(tmp_path / "lib")
    shutil.copytree(REPO / "steps" / "full-suite", lib / "steps" / "full-suite")
    on("full-suite", None, None, fail("suite red"))
    (lib / "steps" / "full-suite" / "run.py").write_text(
        "from helpers.scripted import respond\n\n\ndef run(ctx):\n    return respond(ctx)\n")
    run_dir = start(tmp_path, ONE)
    assert Runner(adapters, lib).drive(run_dir) == "failed"
    scripted.reset()


def test_failed_run_names_the_finish_step_it_failed_at(tmp_path, adapters, project, capsys):
    """Every task passed but the full suite failed: the run says which step failed and why, everywhere."""
    from phoenix9 import events
    from phoenix9.__main__ import main
    scripted.reset()
    lib = scripted.make_library(tmp_path / "lib")
    shutil.copytree(REPO / "steps" / "full-suite", lib / "steps" / "full-suite")
    on("full-suite", None, None, fail("The checks did not pass: 2 tests failed\n\nLast lines of output:\nFAILED test_x"))
    (lib / "steps" / "full-suite" / "run.py").write_text(
        "from helpers.scripted import respond\n\n\ndef run(ctx):\n    return respond(ctx)\n")
    run_dir = start(tmp_path, ONE)
    assert Runner(adapters, lib).drive(run_dir) == "failed"
    st = state.load(run_dir)
    assert all(t["status"] == "passed" for t in st["tasks"].values())
    assert st["failed_step"] == "full-suite"
    assert st["error"] == "Full suite failed: 2 tests failed"
    assert st["failed_at"] == {"step": "full-suite", "title": "Full suite", "reason": "2 tests failed",
                               "text": "Failed at: Full suite: 2 tests failed"}
    row = ops_runs.list_("proj")[0]
    assert row["failed_at"]["text"] == "Failed at: Full suite: 2 tests failed"
    finished = [e for e in events.read(run_dir / "events.jsonl") if e["type"] == "run.finished"]
    assert finished[-1]["data"]["reason"] == st["error"]
    capsys.readouterr()
    assert main(["run", "status", run_dir.name]) == 0
    assert "Failed at: Full suite: 2 tests failed" in capsys.readouterr().out
    assert main(["run", "show", "proj", run_dir.name]) == 0
    assert "Failed at: Full suite: 2 tests failed" in capsys.readouterr().out
    # the step passes on a rerun: the run is done and no longer names a failed step
    on("full-suite", None, None, scripted.StepResult("pass"))
    assert Runner(adapters, lib).rerun_finish_step(run_dir, "full-suite")[0] == "done"
    st = state.load(run_dir)
    assert "failed_step" not in st and "failed_at" not in st and "error" not in st
    scripted.reset()


def test_failed_run_start_step_is_named_too(tmp_path):
    """A run-start step failure gives the same fields; a secret in its note is scrubbed."""
    from phoenix9 import runend
    st = {"steps": [{"group": "run-start", "task": None, "step": "branch", "status": "failed",
                     "note": "could not branch ghp_" + "a" * 36 + "\nmore"}]}
    found = runend.failed_step(st, lambda name: "Branch")
    assert found["step"] == "branch" and found["text"].startswith("Failed at: Branch: could not branch")
    assert "ghp_" + "a" * 36 not in found["text"] and found["error"].startswith("Branch failed: could not branch")
    assert runend.failed_step({"steps": [{**st["steps"][0], "status": "passed"}]}, str) is None


def test_full_suite_skips_without_suite_command(tmp_path, adapters):
    ctx = suite_ctx(tmp_path, adapters, lambda p: p.pop("test"))
    res = full_suite.run(ctx)
    assert res.status == "skip" and res.reasons == ["the profile has no full suite command"]
    assert adapters.docker.argvs == []


def fake_pnpm(command, script):
    """What pnpm runs for a command: extra arguments to `pnpm test` reach only the last tool of the test script."""
    if command.startswith("pnpm test"):
        extra = command[len("pnpm test"):]
        parts = [p.strip() for p in script.split("&&")]
        return parts[:-1] + [parts[-1] + extra]
    return [command.removeprefix("pnpm exec ")]


def test_web_full_suite_runs_vitest_with_its_report_when_test_script_chains_playwright(tmp_path, adapters):
    # the rachel-showcase shape: the project's own test script runs Vitest and then Playwright
    work = make_work(tmp_path)
    script = "vitest run && playwright test"
    write(work, {"package.json": '{"scripts": {"test": "%s"}}\n' % script})
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "package")
    ctx = make_ctx(tmp_path, adapters, work, "full-suite", profile="web")
    ctx.task = None
    seen = {}

    def spy(argv, *a, **k):
        out = Path(next(x for x in argv if ",dst=/out" in x).split("src=", 1)[1].split(",", 1)[0])
        command = argv[-1]
        seen["command"] = command
        for tool in fake_pnpm(command, script):
            if tool.startswith("playwright"):
                return 1                     # Playwright stops on an option meant for Vitest (or a missing browser)
            if "--outputFile=/out/vitest.json" in tool:
                shutil.copy(REPO / "tests" / "data" / "reports" / "vitest-pass.json", out / "vitest.json")
        return 0
    adapters.docker.run = spy
    res = full_suite.run(ctx)
    assert res.status == "pass", res.reasons
    assert "pnpm test" not in seen["command"] and "playwright" not in seen["command"]
    assert "vitest run --passWithNoTests --reporter=json --outputFile=/out/vitest.json" in seen["command"]
    assert fake_pnpm(f"pnpm test {ctx.project.profile['test']['report_args']}", script)[-1].startswith("playwright")


# ------------------------------------------------------------- scripted runs with the real finish steps
@pytest.fixture
def lib(tmp_path):
    scripted.reset()
    root = scripted.make_library(tmp_path / "lib")
    for name in ("summary", "notify"):
        shutil.rmtree(root / "steps" / name)
        shutil.copytree(REPO / "steps" / name, root / "steps" / name)
    yield root
    scripted.reset()


def finished_run(tmp_path, adapters, lib, spec=THREE, **overrides):
    run_dir = start(tmp_path, spec, **overrides)
    Runner(adapters, lib).drive(run_dir)
    return run_dir


def test_summary_lists_failed_tasks_with_reason_and_flags(tmp_path, adapters, lib, project):
    on("builder", 1, None, fail("the build broke"))
    run_dir = finished_run(tmp_path, adapters, lib, max_tries=2, on_failure="continue")
    text = (run_dir / "summary.md").read_text()
    assert "Task 1: First - failed, 2 tries [FAILED: the build broke]" in text
    assert "Task 2: Second - skipped" in text and "SKIPPED: depends on task 1, which failed" in text
    assert "Task 3: Third - passed" in text
    assert "1 passed, 1 failed, 1 skipped" in text
    assert (run_dir / "summary.html").exists()


def test_summary_shows_escalations_and_who_acked(tmp_path, adapters, lib, project):
    on("builder", 1, 1, fail("missing config"))
    run_dir = start(tmp_path, ONE, max_tries=1)
    runner = Runner(adapters, lib)
    assert runner.drive(run_dir) == "waiting"
    (g,) = [x for x in gates.list_gates() if x["run"] == run_dir.name]
    gates.answer(g["id"], "acknowledged", note="added it", who="alex")
    assert runner.drive(run_dir) == "done"
    text = (run_dir / "summary.md").read_text()
    assert "Task 1: acknowledged by alex" in text


def test_summary_html_escapes_values(tmp_path, adapters, lib, project):
    run_dir = finished_run(tmp_path, adapters, lib, ONE.replace("Only thing", "<script>alert(1)</script>"))
    page = (run_dir / "summary.html").read_text()
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_summary_no_unfilled_placeholders(tmp_path, adapters, lib, project):
    run_dir = finished_run(tmp_path, adapters, lib)
    for name in ("summary.md", "summary.html"):
        assert not re.search(r"\{\{\w+\}\}", (run_dir / name).read_text()), name


def test_simple_run_writes_summary_and_one_message(tmp_path, adapters, lib, project):
    run_dir = finished_run(tmp_path, adapters, lib, ONE)
    assert (run_dir / "summary.md").exists() and (run_dir / "summary.html").exists()
    assert len(adapters.notify.messages) == 1


def test_run_log_summary(tmp_path, adapters, lib, project):
    run_dir = finished_run(tmp_path, adapters, lib, ONE)
    assert "Task 1" in ops_runs.summary(run_dir.name)["summary"]


# ------------------------------------------------------------- notify
def test_notify_message_counts(tmp_path, adapters, lib, project):
    on("builder", 1, None, fail("boom"))
    finished_run(tmp_path, adapters, lib, max_tries=1, on_failure="continue")
    (msg,) = adapters.notify.messages
    assert msg.startswith("proj: Spec: Three tasks failed: 1 passed, 1 failed, 1 skipped (boom)")
    assert "summary.md" in msg


def test_notify_says_finished_when_all_passed(tmp_path, adapters, lib, project):
    finished_run(tmp_path, adapters, lib, ONE)
    assert adapters.notify.messages[0].startswith("proj: Spec: One task finished: 1 passed, 0 failed, 0 skipped")


def test_notify_runs_after_stop(tmp_path, adapters, lib, project):
    on("builder", 1, None, fail("it broke"))
    run_dir = start(tmp_path, ONE, max_tries=1)
    runner = Runner(adapters, lib)
    assert runner.drive(run_dir) == "waiting"
    adapters.notify.messages.clear()
    (g,) = [x for x in gates.list_gates() if x["run"] == run_dir.name]
    gates.answer(g["id"], "stop", who="alex")
    assert runner.drive(run_dir) == "stopped"
    (msg,) = adapters.notify.messages
    assert " stopped: 0 passed, 0 failed, 1 skipped" in msg


def test_notify_with_empty_state(tmp_path, adapters):
    ctx = make_ctx(tmp_path, adapters, make_work(tmp_path), "notify")
    state.update(ctx.run.folder, lambda s: s["tasks"].clear())
    assert notify_step.run(ctx).status == "pass"
    assert "0 passed, 0 failed, 0 skipped" in adapters.notify.messages[0]


def test_notify_never_contains_secret(tmp_path, adapters, monkeypatch):
    monkeypatch.setattr(scrub, "_GLOBAL", scrub.Scrubber())
    scrub.add_secrets(["hunter2-hunter2"])
    ctx = make_ctx(tmp_path, adapters, make_work(tmp_path), "notify")
    state.set_task(ctx.run.folder, 1, status="failed", flagged="bad key hunter2-hunter2 used")
    notify_step.run(ctx)
    (msg,) = adapters.notify.messages
    assert "hunter2-hunter2" not in msg and "failed" in msg


# ------------------------------------------------------------- the summary's final status
def test_summary_written_mid_run_says_finishing(tmp_path, adapters, lib, project):
    from phoenix9 import summary
    run_dir = start(tmp_path, ONE)
    state.set_status(run_dir, "running")
    facts = summary.facts(run_dir)
    for text in (summary.markdown(facts), summary.html(facts)):
        assert "finishing (the last steps were still running when this was written)" in text
        assert "not yet" in text
        assert "Status: running" not in text


def test_summary_refreshed_with_final_status_when_run_ends(tmp_path, adapters, lib, project):
    run_dir = finished_run(tmp_path, adapters, lib, ONE)
    text = (run_dir / "summary.md").read_text()
    assert "Status: done" in text and "finishing" not in text and "Finished: not yet" not in text
    assert "done" in (run_dir / "summary.html").read_text()
    assert not (run_dir / "logs" / "summary.log").exists()


def test_summary_refresh_skipped_when_no_summary(tmp_path, adapters, lib, project):
    shutil.rmtree(lib / "steps" / "summary")
    run_dir = finished_run(tmp_path, adapters, lib, ONE)
    assert not (run_dir / "summary.md").exists() and not (run_dir / "summary.html").exists()


def test_stopped_run_summary_says_stopped(tmp_path, adapters, lib, project):
    toml = lib / "steps" / "summary" / "step.toml"
    toml.write_text(toml.read_text() + "\n[settings]\nafter_stop = true\n")
    on("builder", 1, 1, fail("missing config"))
    run_dir = start(tmp_path, ONE, max_tries=1)
    runner = Runner(adapters, lib)
    assert runner.drive(run_dir) == "waiting"
    (g,) = [x for x in gates.list_gates() if x["run"] == run_dir.name]
    gates.answer(g["id"], "stop", who="alex")
    assert runner.drive(run_dir) == "stopped"
    assert "Status: stopped" in (run_dir / "summary.md").read_text()
