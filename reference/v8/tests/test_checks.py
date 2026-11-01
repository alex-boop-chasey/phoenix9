"""Tests for phoenix/checks.py. A local bare repo stands in for GitHub; containers are fakes."""
import json
import subprocess
from pathlib import Path

import pytest

from phoenix import checks, claude, runs
from phoenix import git as pgit
from phoenix import plan as pplan

DATA = Path(__file__).parent / "data"
PLAN_FILE = DATA / "sample-plan.md"
REPO = "alex-boop-chasey/bakery-site"
RUN = "20261030-1405-abcd"


def sh(cwd, *args):
    """Run a plain git command in a test folder and return its output."""
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout


@pytest.fixture
def run(tmp_path, monkeypatch):
    """A run of the sample plan on a started branch. Returns the run.json record."""
    base = tmp_path / "remotes"
    seed = tmp_path / "seed"
    seed.mkdir()
    sh(seed, "init", "-q", "-b", "main")
    (seed / "package.json").write_text(json.dumps({"name": "bakery", "scripts": {"dev": "next dev"}}))
    (seed / "app").mkdir()
    (seed / "app" / "page.tsx").write_text("export default function Page() { return null }\n")
    sh(seed, "add", "-A")
    sh(seed, "commit", "-q", "-m", "init")
    base.mkdir()
    sh(tmp_path, "clone", "-q", "--bare", str(seed), str(base / "bakery-site.git"))
    monkeypatch.setenv("PHOENIX_GIT_BASE", str(base))
    pgit.start_branch(REPO, RUN)
    pgit.commit_plan(REPO, RUN, PLAN_FILE)
    record = runs.load_run(RUN)
    record.update(repo=REPO, plan_path=str(PLAN_FILE), status="running")
    runs.save_run(record)
    return record


def step(n=1):
    """Return step n of the sample plan."""
    return next(s for s in pplan.parse(PLAN_FILE.read_text()).steps if s.number == n)


GOOD_FILES = {
    "tests/phoenix/step-01/1-pnpm-build-finishes.test.ts": "import { test } from 'vitest'\n",
    "tests/phoenix/step-01/2-home-page-shows-coming-soon.spec.ts": "import { test } from '@playwright/test'\n",
}


def writer(*file_sets, last_line="CHECKS WRITTEN: 2", kind="ok"):
    """A fake check-writer container. Each call writes the next set of files into the workspace."""
    calls = []

    def fake(run_id, step_no, try_no, role, workspace, prompt_file, env_files, domains, timeout, **kw):
        calls.append({"try": try_no, "role": role, "prompt": Path(prompt_file).read_text(), **kw})
        for rel, text in file_sets[min(len(calls), len(file_sets)) - 1].items():
            p = Path(workspace) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        return claude.Result(kind=kind, text=f"I wrote the checks.\n{last_line}")

    fake.calls = calls
    return fake


def log_lines():
    """Return the commit subjects of the run branch, newest first."""
    return sh(pgit.clone_dir(REPO), "log", "--format=%s").splitlines()


# ------------------------------------------------------------- lock / verify_lock
def locked_run(run):
    """Write and lock step 1's checks with a fake writer. Return the clone."""
    paths = checks.write_checks(run, step(1), container=writer(GOOD_FILES))
    checks.lock(REPO, 1, paths)
    return pgit.clone_dir(REPO)


def test_lock_then_untouched_set_passes(run):
    clone = locked_run(run)
    manifest = json.loads((clone / "tests/phoenix/manifest.json").read_text())
    assert sorted(manifest["files"]) == sorted(GOOD_FILES)
    assert log_lines()[:2] == ["Step 1: lock checks", "Step 1: checks"]
    checks.verify_lock(clone)                                    # does not raise


def test_changed_file_breaks_the_lock_and_names_it(run):
    clone = locked_run(run)
    target = "tests/phoenix/step-01/2-home-page-shows-coming-soon.spec.ts"
    (clone / target).write_text("test.skip('nothing')\n")
    with pytest.raises(checks.LockBroken) as e:
        checks.verify_lock(clone)
    assert e.value.path == target and target in str(e.value)


def test_missing_file_breaks_the_lock(run):
    clone = locked_run(run)
    target = "tests/phoenix/step-01/1-pnpm-build-finishes.test.ts"
    (clone / target).unlink()
    with pytest.raises(checks.LockBroken, match="1-pnpm-build-finishes.test.ts"):
        checks.verify_lock(clone)


def test_lock_refuses_paths_outside_tests_phoenix(run):
    with pytest.raises(ValueError):
        checks.lock(REPO, 1, ["app/page.tsx"])


def test_snapshot_rejects_a_builder_that_edits_a_locked_check(run):
    locked_run(run)
    ws = pgit.fresh_workspace(REPO, RUN, 1, 1)
    (ws / "app" / "page.tsx").write_text("export default function Page() { return 'Coming soon' }\n")
    (ws / "tests/phoenix/step-01/1-pnpm-build-finishes.test.ts").write_text("// gone\n")
    with pytest.raises(pgit.Rejected) as e:
        pgit.snapshot(ws, REPO)
    assert "1-pnpm-build-finishes.test.ts" in " ".join(e.value.reasons)
    assert sh(pgit.clone_dir(REPO), "status", "--porcelain") == ""


def test_snapshot_rejects_a_builder_that_rewrites_the_manifest(run):
    locked_run(run)
    ws = pgit.fresh_workspace(REPO, RUN, 1, 1)
    target = ws / "tests/phoenix/step-01/1-pnpm-build-finishes.test.ts"
    target.write_text("// gone\n")
    manifest = json.loads((ws / "tests/phoenix/manifest.json").read_text())
    manifest["files"]["tests/phoenix/step-01/1-pnpm-build-finishes.test.ts"] = checks.file_sha256(target)
    (ws / "tests/phoenix/manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(pgit.Rejected) as e:
        pgit.snapshot(ws, REPO)
    reasons = " ".join(e.value.reasons)
    assert "manifest.json" in reasons and "1-pnpm-build-finishes.test.ts" in reasons


def test_snapshot_accepts_app_changes_with_the_lock_intact(run):
    locked_run(run)
    ws = pgit.fresh_workspace(REPO, RUN, 1, 1)
    (ws / "app" / "page.tsx").write_text("export default function Page() { return 'Coming soon' }\n")
    changes = pgit.snapshot(ws, REPO)
    assert [(c.status, c.path) for c in changes] == [("M", "app/page.tsx")]


# ------------------------------------------------------------- write_checks
def test_write_checks_commits_the_step_folder(run):
    fake = writer(GOOD_FILES)
    paths = checks.write_checks(run, step(1), container=fake)
    assert sorted(map(str, paths)) == sorted(GOOD_FILES)
    assert log_lines()[0] == "Step 1: checks"
    assert sh(pgit.clone_dir(REPO), "status", "--porcelain") == ""
    assert "Phoenix-Step" not in sh(pgit.clone_dir(REPO), "log", "-1", "--format=%B")
    call = fake.calls[0]
    assert call["role"] == "checker" and call["max_turns"] == 60
    assert "1. `pnpm build` finishes without errors" in call["prompt"]
    assert "tests/phoenix/step-01/" in call["prompt"] and "app/page.tsx" in call["prompt"]
    assert "{{" not in call["prompt"]
    assert not list(pgit.work_root().glob(f"{RUN}-*"))           # workspaces removed


def test_write_checks_rejects_a_file_outside_tests_phoenix(run):
    head_before = pgit.head(pgit.clone_dir(REPO))
    bad = {**GOOD_FILES, "app/page.tsx": "export default function Page() { return 'Coming soon' }\n"}
    fake = writer(bad)
    with pytest.raises(checks.CheckWriterFailed, match="app/page.tsx"):
        checks.write_checks(run, step(1), container=fake)
    assert len(fake.calls) == 2                                   # rejected, retried once, rejected again
    assert pgit.head(pgit.clone_dir(REPO)) == head_before         # nothing committed
    assert sh(pgit.clone_dir(REPO), "status", "--porcelain", "--untracked-files=all") == ""


def test_write_checks_retries_once_after_a_rejection(run):
    stray = {**GOOD_FILES, "tests/phoenix/helpers.ts": "export const x = 1\n"}
    fake = writer(stray, GOOD_FILES)
    paths = checks.write_checks(run, step(1), container=fake)
    assert [c["try"] for c in fake.calls] == [1, 2]
    assert sorted(map(str, paths)) == sorted(GOOD_FILES)
    assert not (pgit.clone_dir(REPO) / "tests/phoenix/helpers.ts").exists()


def test_write_checks_records_the_cost_of_every_session(run):
    stray = {**GOOD_FILES, "tests/phoenix/helpers.ts": "export const x = 1\n"}
    checks.write_checks(run, step(1), container=writer(stray, GOOD_FILES))
    lines = [json.loads(l) for l in (runs.run_dir(RUN) / "usage.jsonl").read_text().splitlines()]
    assert [(l["role"], l["step"], l["try_no"]) for l in lines] == [("checker", 1, 1), ("checker", 1, 2)]


def test_write_checks_needs_one_file_per_bullet(run):
    one = dict(list(GOOD_FILES.items())[:1])
    with pytest.raises(checks.CheckWriterFailed, match="bullets"):
        checks.write_checks(run, step(1), container=writer(one))


def test_write_checks_cannot_check_stops_at_once(run):
    fake = writer({}, last_line="CANNOT CHECK: The home page shows the text - no page yet")
    with pytest.raises(checks.CannotCheck, match="no page yet"):
        checks.write_checks(run, step(1), container=fake)
    assert len(fake.calls) == 1


def test_write_checks_failed_session_is_retried(run):
    fake = writer(GOOD_FILES, kind="crashed")
    with pytest.raises(checks.CheckWriterFailed, match="crashed"):
        checks.write_checks(run, step(1), container=fake)
    assert len(fake.calls) == 2


# ------------------------------------------------------------- red_check
def reporter(vitest=None, playwright=None, rc=1):
    """A fake check container that writes the given reports into the /out mount."""
    calls = []

    def fake(run_id, step_no, try_no, checkout, command, env_file, domains, timeout, *, role, mounts, **kw):
        calls.append({"command": command, "role": role, "mounts": mounts})
        out = next(Path(m.src) for m in mounts if m.dst == "/out")
        if vitest is not None:
            (out / "vitest.json").write_text(json.dumps(vitest))
        if playwright is not None:
            (out / "playwright.json").write_text(json.dumps(playwright))
        return rc, out / "log.txt"

    fake.calls = calls
    return fake


ALL_PASS_VITEST = {"success": True, "numTotalTests": 1, "numPassedTests": 1, "numFailedTests": 0,
                   "numPendingTests": 0, "numTodoTests": 0, "numFailedTestSuites": 0}
ALL_PASS_PW = {"stats": {"expected": 1, "unexpected": 0, "flaky": 0, "skipped": 0}, "errors": []}


def red_step(run):
    """Return step 1's entry in run.json."""
    return next(e for e in runs.load_run(RUN)["steps"] if e["number"] == 1)


def test_red_check_all_pass_logs_vacuous_checks(run):
    locked_run(run)
    fake = reporter(ALL_PASS_VITEST, ALL_PASS_PW, rc=0)
    assert checks.red_check(run, step(1), container=fake) is True
    assert red_step(run)["red_check"] == "vacuous checks"
    assert "vacuous checks" in (runs.run_dir(RUN) / "logs" / "phoenix.log").read_text()
    call = fake.calls[0]
    assert call["role"] == "red"
    assert "npx vitest run tests/phoenix/step-01" in call["command"]
    assert "npx playwright test tests/phoenix/step-01" in call["command"]
    assert any(m.dst == "/phoenix/testconfig" and m.ro for m in call["mounts"])


def test_red_check_with_a_failure_is_failing(run):
    locked_run(run)
    failing = {**ALL_PASS_PW, "stats": {**ALL_PASS_PW["stats"], "expected": 0, "unexpected": 1}}
    assert checks.red_check(run, step(1), container=reporter(ALL_PASS_VITEST, failing)) is True
    assert red_step(run)["red_check"] == "failing"


def test_red_check_missing_report_is_failing(run):
    locked_run(run)
    assert checks.red_check(run, step(1), container=reporter(ALL_PASS_VITEST, None)) is True
    assert red_step(run)["red_check"] == "failing"


def test_red_check_without_check_files_says_so(run):
    assert checks.red_check(run, step(1), container=reporter()) is False
    assert red_step(run)["red_check"] == "no checks"


# ------------------------------------------------------------- small parts
def test_check_command_skips_playwright_without_specs():
    with_spec = checks.check_command(3, has_spec=True)
    assert with_spec == (
        'vc=$(mktemp -d) && cp /phoenix/testconfig/vitest.config.mjs "$vc/" && '
        'npx vitest run tests/phoenix/step-03 --config "$vc/vitest.config.mjs" '
        "--reporter=json --outputFile=/out/vitest.json; "
        "npx playwright test tests/phoenix/step-03 --config /phoenix/testconfig/playwright.config.mjs "
        "--reporter=json > /out/playwright.json")
    assert "playwright" not in checks.check_command(3, has_spec=False)
    assert (checks.TESTCONFIG_DIR / "vitest.config.mjs").is_file()
    assert (checks.TESTCONFIG_DIR / "playwright.config.mjs").is_file()


def test_finish_line():
    assert checks.finish_line("done\nCHECKS WRITTEN: 3") == ("written", "3")
    assert checks.finish_line("`CHECKS WRITTEN: 3`\n") == ("written", "3")
    assert checks.finish_line("CANNOT CHECK: x - y") == ("cannot", "x - y")
    assert checks.finish_line("CHECKS WRITTEN: 3\nmore talk") == ("", "")
