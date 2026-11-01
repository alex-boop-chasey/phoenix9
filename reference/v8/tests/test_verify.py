"""Tests for phoenix/verify.py. Report fixtures in tests/fixtures/ are real Vitest 3.2.4 and
Playwright 1.64.1 output, made in the step image by tests/fixtures/generate.py."""
import base64
import json
import os
import subprocess
from pathlib import Path

import pytest

from phoenix import checks, config, runs, verify
from phoenix import git as pgit
from phoenix.verify import judge_playwright, judge_vitest

from test_checks import GOOD_FILES, REPO, RUN, locked_run, run, step  # noqa: F401  (run is a fixture)

FIX = Path(__file__).parent / "fixtures"


def check_paths(step_no, *names):
    """Repo paths of check files in a fixture step folder."""
    return [f"tests/phoenix/step-{step_no:02d}/{n}" for n in names]


# ------------------------------------------------------------- judge_vitest
def test_vitest_all_pass():
    v = judge_vitest(FIX / "vitest-pass.json", check_paths(1, "1-adds.test.ts"))
    assert (v.passed, v.failed, v.skipped, v.flaky, v.ok) == (1, 0, 0, 0, True)


def test_vitest_one_fail_names_the_test():
    v = judge_vitest(FIX / "vitest-fail.json", check_paths(3, "1-fail.test.ts"))
    assert (v.passed, v.failed, v.ok) == (1, 1, False)
    assert v.reason == "1 failed: tests/phoenix/step-03/1-fail.test.ts > the sum is right"


def test_vitest_one_skip():
    v = judge_vitest(FIX / "vitest-skip.json", check_paths(4, "1-skip.test.ts"))
    assert (v.passed, v.failed, v.skipped, v.ok) == (1, 0, 1, False)
    assert v.reason.startswith("1 skipped: ") and "is skipped" in v.reason


def test_vitest_one_todo():
    v = judge_vitest(FIX / "vitest-todo.json", check_paths(5, "1-todo.test.ts"))
    assert (v.passed, v.skipped, v.ok) == (1, 1, False)
    assert "is todo (todo)" in v.reason


def test_vitest_only_skipped_is_not_ok_although_vitest_says_success():
    assert json.loads((FIX / "vitest-allskip.json").read_text())["success"] is True
    v = judge_vitest(FIX / "vitest-allskip.json", check_paths(7, "1-allskip.test.ts"))
    assert (v.passed, v.skipped, v.ok) == (0, 2, False)


def test_vitest_mixed_sample():
    v = judge_vitest(FIX / "vitest-mixed.json", check_paths(2, "1-mixed.test.ts"))
    assert (v.passed, v.failed, v.skipped, v.ok) == (1, 1, 2, False)
    assert "fails" in v.reason


def test_vitest_file_that_does_not_load_is_a_failure():
    v = judge_vitest(FIX / "vitest-loaderror.json", check_paths(8, "1-ok.test.ts", "2-broken.test.ts"))
    assert (v.passed, v.failed, v.ok) == (1, 1, False)
    assert "2-broken.test.ts could not run: cannot load this file" in v.reason


def test_vitest_report_listing_fewer_files_than_the_step_folder():
    v = judge_vitest(FIX / "vitest-pass.json", check_paths(1, "1-adds.test.ts", "3-extra.test.ts"))
    assert v.ok is False
    assert v.reason == "not in the report: tests/phoenix/step-01/3-extra.test.ts"


def test_vitest_missing_or_broken_report(tmp_path):
    assert judge_vitest(tmp_path / "nope.json") == verify.Verdict(reason="no report")
    (tmp_path / "bad.json").write_text("{not json")
    assert judge_vitest(tmp_path / "bad.json").reason == "no report"
    (tmp_path / "list.json").write_text("[]")
    assert judge_vitest(tmp_path / "list.json").ok is False


def test_vitest_empty_report_is_not_ok(tmp_path):
    (tmp_path / "v.json").write_text(json.dumps({"numPassedTests": 0, "success": True, "testResults": []}))
    v = judge_vitest(tmp_path / "v.json")
    assert (v.passed, v.ok, v.reason) == (0, False, "no checks passed (0 passed)")


# ------------------------------------------------------------- judge_playwright
def test_playwright_stats_field_names_are_the_real_ones():
    stats = json.loads((FIX / "playwright-pass.json").read_text())["stats"]
    assert {"expected", "unexpected", "skipped", "flaky"} <= set(stats)


def test_playwright_all_pass():
    files = check_paths(1, "1-home-page-shows-coming-soon-heading.spec.ts", "2-title.spec.ts")
    v = judge_playwright(FIX / "playwright-pass.json", files)
    assert (v.passed, v.failed, v.skipped, v.flaky, v.ok) == (2, 0, 0, 0, True)


def test_playwright_one_fail_names_the_test():
    v = judge_playwright(FIX / "playwright-fail.json", check_paths(3, "2-fail.spec.ts"))
    assert (v.passed, v.failed, v.ok) == (1, 1, False)
    assert v.reason == "1 failed: step-03/2-fail.spec.ts › the heading is right"


def test_playwright_one_skip():
    v = judge_playwright(FIX / "playwright-skip.json", check_paths(4, "2-skip.spec.ts"))
    assert (v.passed, v.skipped, v.ok) == (1, 1, False)


def test_playwright_fixme_counts_as_skipped():
    v = judge_playwright(FIX / "playwright-fixme.json", check_paths(5, "2-fixme.spec.ts"))
    assert (v.passed, v.skipped, v.ok) == (1, 1, False)
    assert "is fixme" in v.reason


def test_playwright_flaky_is_not_ok():
    v = judge_playwright(FIX / "playwright-flaky.json", check_paths(6, "1-flaky.spec.ts"))
    assert (v.passed, v.failed, v.flaky, v.ok) == (1, 0, 1, False)
    assert v.reason.startswith("1 flaky") and "is flaky" in v.reason


def test_playwright_mixed_sample():
    v = judge_playwright(FIX / "playwright-mixed.json", check_paths(2, "2-mixed.spec.ts"))
    assert (v.passed, v.failed, v.skipped, v.ok) == (1, 1, 2, False)


def test_playwright_report_listing_fewer_files_than_the_step_folder():
    v = judge_playwright(FIX / "playwright-pass.json", check_paths(1, "2-title.spec.ts", "3-other.spec.ts"))
    assert v.ok is False and v.reason == "not in the report: tests/phoenix/step-01/3-other.spec.ts"


def test_playwright_missing_report(tmp_path):
    assert judge_playwright(tmp_path / "playwright.json").reason == "no report"
    (tmp_path / "p.json").write_text(json.dumps({"suites": []}))
    assert judge_playwright(tmp_path / "p.json").reason == "no report"


def test_playwright_top_level_error_is_a_failure(tmp_path):
    data = json.loads((FIX / "playwright-pass.json").read_text())
    data["errors"] = [{"message": "\x1b[31mError: Timed out waiting 180000ms from config.webServer.\x1b[39m\nmore"}]
    (tmp_path / "p.json").write_text(json.dumps(data))
    v = judge_playwright(tmp_path / "p.json", check_paths(1, "2-title.spec.ts"))
    assert v.ok is False and v.failed == 1
    assert v.reason == "1 failed: error: Error: Timed out waiting 180000ms from config.webServer."


def test_combine():
    good = verify.Verdict(passed=2, ok=True, reason="all 2 passed")
    bad = verify.Verdict(passed=1, failed=1, reason="1 failed: x")
    assert verify.combine([good, good]).ok is True
    both = verify.combine([good, bad])
    assert (both.passed, both.failed, both.ok, both.reason) == (3, 1, False, "1 failed: x")
    assert verify.combine([]).ok is False


# ------------------------------------------------------------- fast suite
def test_fast_suite_from_every_step_text(tmp_path):
    text = "Keep it fast. After each change run `pnpm install` and then `pnpm test:unit --run`."
    assert verify.fast_suite_command(text, tmp_path) == "pnpm test:unit --run"


def test_fast_suite_default_is_pnpm_test_when_package_json_has_one(tmp_path):
    assert verify.fast_suite_command("", tmp_path) is None
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"dev": "next dev"}}))
    assert verify.fast_suite_command("Use British English.", tmp_path) is None
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}))
    assert verify.fast_suite_command("Use British English.", tmp_path) == "pnpm test"
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": verify.NPM_DEFAULT_TEST}}))
    assert verify.fast_suite_command("", tmp_path) is None


def test_first_failing_test_from_real_outputs():
    vitest_out = (FIX / "vitest-fail-output.txt").read_text()
    assert verify.first_failing_test(vitest_out) == "tests/phoenix/step-03/1-fail.test.ts > the sum is right"
    pw_out = (FIX / "playwright-fail-output.txt").read_text()
    assert verify.first_failing_test(pw_out) == "[chromium] › tests/phoenix/step-03/2-fail.spec.ts:4:5 › the heading is right"
    assert verify.first_failing_test("  ● Cart › adds an item\n") == "Cart › adds an item"
    assert verify.first_failing_test("all good\n") == ""


def fake_tools(tmp_path, pnpm_test_rc):
    """A folder with fake pnpm and npx commands, and the command with /out and the configs moved to tmp_path."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "pnpm").write_text(f'#!/bin/sh\n[ "$1" = test ] && {{ echo " FAIL  a.test.ts > breaks"; exit {pnpm_test_rc}; }}\nexit 1\n')
    (bin_dir / "npx").write_text("#!/bin/sh\nexit 1\n")
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    for d in ("out", "cfg", "work"):
        (tmp_path / d).mkdir()
    (tmp_path / "cfg" / "vitest.config.mjs").write_text("export default {}\n")
    (tmp_path / "work" / "package.json").write_text("{}")
    return {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}


@pytest.mark.parametrize("test_rc, want", [(0, 0), (1, verify.FAST_SUITE_FAILED_RC)])
def test_verify_command_exit_code_is_the_fast_suite_only(tmp_path, test_rc, want):
    env = fake_tools(tmp_path, test_rc)
    cmd = verify.verify_command(1, "pnpm test", True)
    cmd = cmd.replace(checks.OUT_MOUNT + "/", f"{tmp_path}/out/").replace(checks.TESTCONFIG_MOUNT, f"{tmp_path}/cfg")
    p = subprocess.run(["bash", "-c", cmd], cwd=tmp_path / "work", env=env, capture_output=True, text=True)
    assert p.returncode == want                       # the failing checks (npx exit 1) do not change it
    assert "breaks" in (tmp_path / "out" / verify.FAST_SUITE_FILE).read_text()


def test_verify_command_without_fast_suite():
    cmd = verify.verify_command(2, None, False)
    assert "fast suite" not in cmd
    assert cmd.startswith("[ -f package.json ] && pnpm install --frozen-lockfile; ")
    assert "npx vitest run tests/phoenix/step-02" in cmd and "playwright" not in cmd


# ------------------------------------------------------------- verify_step with a fake container
def with_name(fixture, old, new):
    """A fixture report with one file name swapped, as text."""
    return (FIX / fixture).read_text().replace(old, new)


PASS_VITEST = with_name("vitest-pass.json", "step-01/1-adds.test.ts", "step-01/1-pnpm-build-finishes.test.ts")
PASS_PW = with_name("playwright-pass.json", "step-01/2-title.spec.ts", "step-01/2-home-page-shows-coming-soon.spec.ts")
ZERO_VITEST = json.dumps({"numTotalTests": 0, "numPassedTests": 0, "numFailedTests": 0, "success": True,
                          "testResults": [{"name": "/workspace/tests/phoenix/step-01/1-pnpm-build-finishes.test.ts",
                                           "status": "passed", "message": "", "assertionResults": []}]})
ZERO_PW = json.dumps({"stats": {"expected": 0, "unexpected": 0, "skipped": 0, "flaky": 0}, "errors": [],
                      "suites": [{"file": "step-01/2-home-page-shows-coming-soon.spec.ts", "specs": []}]})


def container(vitest=PASS_VITEST, playwright=PASS_PW, rc=0, fast_output=None, also=None):
    """A fake verify container: writes the given report texts into /out and a log, returns rc."""
    calls = []

    def fake(run_id, step_no, try_no, checkout, command, env_file, domains, timeout, *, role, mounts, **kw):
        calls.append({"command": command, "role": role, "mounts": mounts, "try": try_no, "timeout": timeout})
        out = next(Path(m.src) for m in mounts if m.dst == "/out")
        if vitest is not None:
            (out / "vitest.json").write_text(vitest)
        if playwright is not None:
            (out / "playwright.json").write_text(playwright)
        if fast_output is not None:
            (out / verify.FAST_SUITE_FILE).write_text(fast_output)
        if also:
            also(Path(checkout), out)
        log_path = runs.run_dir(run_id) / "logs" / f"{step_no}-{try_no}-{role}.txt"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("installing\nrunning checks\n")
        return rc, log_path

    fake.calls = calls
    return fake


def head_sha():
    """The sha of the run branch head (the locked checks)."""
    return pgit.head(pgit.clone_dir(REPO))


def test_verify_step_exit_0_with_a_0_passed_report_is_not_ok(run):
    locked_run(run)
    v = verify.verify_step(run, step(1), head_sha(), container=container(vitest=ZERO_VITEST, playwright=ZERO_PW))
    assert (v.ok, v.passed, v.reason) == (False, 0, "no checks passed (0 passed)")


def test_verify_step_exit_0_with_only_skipped_tests_is_not_ok(run):
    locked_run(run)
    skipped = with_name("vitest-allskip.json", "step-07/1-allskip.test.ts", "step-01/1-pnpm-build-finishes.test.ts")
    v = verify.verify_step(run, step(1), head_sha(), container=container(vitest=skipped))
    assert v.ok is False and v.passed == 2 and v.skipped == 2   # the Playwright half passed two


def test_verify_step_all_pass(run):
    locked_run(run)
    fake = container()
    v = verify.verify_step(run, step(1), head_sha(), try_no=2, container=fake)
    assert (v.ok, v.passed, v.reason) == (True, 3, "all 3 passed")   # 1 Vitest + 2 Playwright
    call = fake.calls[0]
    assert call["role"] == "verify" and call["try"] == 2 and call["timeout"] == 20
    assert any(m.dst == "/workspace/tests/phoenix" and m.ro for m in call["mounts"])
    out = runs.run_dir(RUN) / "3-product" / "reports" / "1-2"
    assert (out / "vitest.json").exists() and (out / "playwright.json").exists()
    assert "verify try 2 passed" in (runs.run_dir(RUN) / "logs" / "phoenix.log").read_text()
    assert not list((pgit.work_root()).glob("check-*"))     # the checkout is gone


def test_verify_step_missing_playwright_report(run):
    locked_run(run)
    v = verify.verify_step(run, step(1), head_sha(), container=container(playwright=None))
    assert (v.ok, v.reason) == (False, "no report")


def test_verify_step_fast_suite_failure(run, monkeypatch):
    locked_run(run)
    monkeypatch.setattr(verify, "fast_suite_command", lambda text, checkout: "pnpm test")
    fake = container(rc=verify.FAST_SUITE_FAILED_RC, fast_output=(FIX / "vitest-fail-output.txt").read_text())
    v = verify.verify_step(run, step(1), head_sha(), container=fake)
    assert v.ok is False
    assert v.reason == "fast suite: tests/phoenix/step-03/1-fail.test.ts > the sum is right"
    assert "( pnpm test )" in fake.calls[0]["command"]


def test_verify_step_timeout(run):
    locked_run(run)
    v = verify.verify_step(run, step(1), head_sha(), container=container(rc=124))
    assert (v.ok, v.reason) == (False, "timed out after 20 minutes")


def test_verify_step_odd_exit_code_never_passes(run):
    locked_run(run)
    v = verify.verify_step(run, step(1), head_sha(), container=container(rc=137))
    assert v.ok is False and v.reason == "the check container ended with exit 137"


def test_verify_step_check_changed_during_the_run(run):
    locked_run(run)

    def tamper(checkout, out):
        (checkout / next(iter(GOOD_FILES))).write_text("// gone\n")

    v = verify.verify_step(run, step(1), head_sha(), container=container(also=tamper))
    assert v.ok is False and v.reason.startswith("during verify: Locked check tests/phoenix/step-01/")


def test_verify_step_without_checks(run):
    fake = container()
    v = verify.verify_step(run, step(1), head_sha(), container=fake)
    assert (v.ok, v.reason) == (False, "no checks")
    assert fake.calls == []


def test_verify_step_keeps_project_screenshots_and_redacts_reports(run):
    locked_run(run)
    env = config.paths().config / "projects" / "bakery-site.env"
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text("STRIPE_SECRET_KEY=sk_test_abcdefghijkl\n")

    def leave_files(checkout, out):
        shot = checkout / "test-results" / "home" / "test-failed-1.png"
        shot.parent.mkdir(parents=True)
        shot.write_bytes(b"\x89PNG")
        (checkout / "test-results" / "link").symlink_to("/etc/passwd")
        (out / "error-context.md").write_text("key sk_test_abcdefghijkl here\n")

    verify.verify_step(run, step(1), head_sha(), container=container(also=leave_files))
    out = runs.run_dir(RUN) / "3-product" / "reports" / "1-1"
    assert (out / "fast-suite" / "test-results" / "home" / "test-failed-1.png").read_bytes() == b"\x89PNG"
    assert not (out / "fast-suite" / "test-results" / "link").exists()
    assert (out / "error-context.md").read_text() == "key [redacted] here\n"


# ------------------------------------------------------------- feedback
def test_feedback_is_the_reason_and_the_last_80_lines_redacted(tmp_path):
    secret = "sk_test_abcdefghijkl"
    env = tmp_path / "p.env"
    env.write_text(f"STRIPE_SECRET_KEY={secret}\n")
    b64 = base64.b64encode(secret.encode()).decode().rstrip("=")
    log_path = tmp_path / "log.txt"
    log_path.write_text("\n".join(f"line {i}" for i in range(1, 101)) + f"\nkey {secret} b64 {b64}\n")
    text = verify.feedback(verify.Verdict(failed=1, reason="1 failed: x > y"), log_path, env)
    assert text.startswith("The checks did not pass: 1 failed: x > y\n")
    assert "line 21\n" not in text and "line 22\n" in text      # 100 + 1 lines, the last 80 kept
    assert secret not in text and b64 not in text
    assert "key [redacted] b64 [redacted]" in text


def test_feedback_without_a_log(tmp_path):
    assert "(no output was saved)" in verify.feedback(verify.Verdict(reason="no report"), tmp_path / "x")
