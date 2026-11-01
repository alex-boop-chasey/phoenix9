"""Deciding whether a step is done: run its locked checks and judge the reports.

One throwaway check container gets a clean checkout of the builder's commit.
It installs the packages, runs the project's own fast suite (when there is
one), then the step's locked checks. Phoenix decides pass or fail from the
counts in the Vitest and Playwright report files, never from an exit code
alone: Vitest says `success: true` when every test was skipped, and
Playwright exits 0 with skipped tests and counts a test that failed and then
passed on a retry ("flaky") as passed. A step passes only when at least one
check passed and nothing failed, was skipped or was flaky, and every check
file of the step shows up in a report.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from phoenix import checks, claude, config, docker
from phoenix import git as pgit
from phoenix import plan as pplan
from phoenix.log import log

ROLE = "verify"
FAST_SUITE_FAILED_RC = 3              # the check command's exit code when the fast suite failed
FAST_SUITE_FILE = "fast-suite.txt"    # the fast suite's own output, in the report folder
TAIL_LINES = 80
REPORT_TEXT_SUFFIXES = (".json", ".txt", ".md", ".html", ".log")
PROJECT_ARTIFACTS = ("test-results", "playwright-report")   # what the fast suite may leave behind
NPM_DEFAULT_TEST = 'echo "Error: no test specified" && exit 1'
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
RUNNER = re.compile(r"^(pnpm|npm|npx|yarn|bun|node)\s")
TESTY = re.compile(r"\b(test|tests|vitest|jest|playwright|mocha)\b|test:")
SKIPPED_STATES = ("skipped", "pending", "todo", "disabled")

# Lines that name a failing test in the usual test runners' plain output, most specific first.
FAILING_TEST_LINES = [
    re.compile(r"^\s*FAIL\s+(\S.*\S)\s*$"),                              # Vitest: " FAIL  file > name"
    re.compile(r"^\s*\d+\)\s+(\[[^\]]+\]\s+›\s+.*?)\s*─*\s*$"),           # Playwright: "1) [chromium] › file › name"
    re.compile(r"^\s*✘\s+\d+\s+(.+?)(?:\s+\(\d[^)]*\))?\s*$"),           # Playwright list reporter
    re.compile(r"^\s*●\s+(.+›.+?)\s*$"),                                  # Jest: "● suite › name"
    re.compile(r"^\s*not ok \d+\s*-?\s*(.+?)\s*$"),                       # TAP / node --test
    re.compile(r"^\s*[×✗✕]\s+(.+?)(?:\s+\d+(?:\.\d+)?m?s)?\s*$"),          # Vitest / Jest tick lists
]


@dataclass
class Verdict:
    """The result of judging a step's checks. `ok` is the only thing that means "passed"."""

    passed: int = 0
    failed: int = 0
    skipped: int = 0
    flaky: int = 0
    ok: bool = False
    reason: str = ""


# ------------------------------------------------------------- 1. judging report files
def _clean(text: str) -> str:
    """Remove terminal colour codes and keep the first line only."""
    lines = ANSI.sub("", str(text or "")).strip().splitlines()
    return lines[0].strip() if lines else ""


def _read_json(path: Path) -> dict | None:
    """Read a report file as a JSON object. None when it is missing or unreadable."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _in_report(expected: str, present: set[str]) -> bool:
    """True when a check file (repo path) appears in the report's file names.

    Vitest names files by absolute path (/workspace/tests/phoenix/...),
    Playwright relative to its testDir (step-01/...), so the ends are compared.
    """
    return any(p == expected or p.endswith("/" + expected) or expected.endswith("/" + p) for p in present)


def decide(v: Verdict, first_failed: str = "", first_skipped: str = "", first_flaky: str = "",
           present: set[str] = frozenset(), expected=()) -> Verdict:
    """Set `ok` and `reason` from the counts. ok needs passed >= 1 and nothing failed, skipped, flaky or missing."""
    missing = [e for e in expected if not _in_report(e, present)]
    if v.failed:
        v.reason = f"{v.failed} failed: {first_failed or 'unknown test'}"
    elif v.flaky:
        v.reason = f"{v.flaky} flaky (failed, then passed on a retry): {first_flaky or 'unknown test'}"
    elif v.skipped:
        v.reason = f"{v.skipped} skipped: {first_skipped or 'unknown test'}"
    elif missing:
        v.reason = "not in the report: " + ", ".join(missing)
    elif v.passed < 1:
        v.reason = "no checks passed (0 passed)"
    else:
        v.ok = True
        v.reason = f"all {v.passed} passed"
    return v


def judge_vitest(path: Path, expected_files=()) -> Verdict:
    """Judge a Vitest JSON report (`--reporter=json`). `expected_files` = the step's `*.test.ts` repo paths.

    Counts come from each test's own status (passed / failed / skipped,
    pending, todo); a file that could not even load counts as one failure.
    The top-level totals are cross-checked so the stricter number wins.
    """
    data = _read_json(path)
    if data is None or not isinstance(data.get("testResults"), list):
        return Verdict(reason="no report")
    v = Verdict()
    first_failed = first_skipped = ""
    present: set[str] = set()
    try:
        for result in data["testResults"]:
            name = str(result.get("name", ""))
            present.add(name)
            short = name.split("/workspace/", 1)[-1]
            tests = result.get("assertionResults") or []
            failed_here = 0
            for t in tests:
                status = t.get("status")
                title = t.get("fullName") or t.get("title") or "unnamed test"
                if status == "passed":
                    v.passed += 1
                elif status == "failed":
                    failed_here += 1
                    first_failed = first_failed or f"{short} > {title}"
                elif status in SKIPPED_STATES:
                    v.skipped += 1
                    first_skipped = first_skipped or f"{short} > {title} ({status})"
            if result.get("status") == "failed" and not failed_here:
                failed_here = 1
                first_failed = first_failed or f"{short} could not run: {_clean(result.get('message'))}"
            v.failed += failed_here
        v.passed = min(v.passed, int(data.get("numPassedTests", v.passed)))
        v.failed = max(v.failed, int(data.get("numFailedTests", 0)))
        v.skipped = max(v.skipped, int(data.get("numPendingTests", 0)) + int(data.get("numTodoTests", 0)))
    except (TypeError, ValueError, AttributeError):
        return Verdict(reason="no report")
    return decide(v, first_failed, first_skipped, "", present, expected_files)


def _walk_suites(suites, specs: list, files: set) -> None:
    """Collect every spec and file name from Playwright's nested suites."""
    for suite in suites or []:
        if suite.get("file"):
            files.add(str(suite["file"]))
        for spec in suite.get("specs") or []:
            specs.append(spec)
            if spec.get("file"):
                files.add(str(spec["file"]))
        _walk_suites(suite.get("suites"), specs, files)


def judge_playwright(path: Path, expected_files=()) -> Verdict:
    """Judge a Playwright JSON report (`--reporter=json`). `expected_files` = the step's `*.spec.ts` repo paths.

    The field names come from a real report (tests/fixtures/playwright-*.json):
    `stats.expected` (passed), `stats.unexpected` (failed), `stats.skipped`
    (also test.fixme), `stats.flaky`. Each test's own `status` (expected,
    unexpected, skipped, flaky) is counted too and the stricter number wins.
    Every top-level error (a file that does not load, a site that does not
    start) counts as one failure.
    """
    data = _read_json(path)
    if data is None or not isinstance(data.get("stats"), dict):
        return Verdict(reason="no report")
    specs: list = []
    present: set[str] = set()
    names = {"unexpected": "", "skipped": "", "flaky": ""}
    seen = {"expected": 0, "unexpected": 0, "skipped": 0, "flaky": 0}
    try:
        _walk_suites(data.get("suites"), specs, present)
        for spec in specs:
            for t in spec.get("tests") or []:
                status = t.get("status")
                if status in seen:
                    seen[status] += 1
                if status in names and not names[status]:
                    names[status] = f"{spec.get('file', '')} › {spec.get('title', 'unnamed test')}"
        stats = data["stats"]
        errors = data.get("errors") or []
        v = Verdict(passed=min(int(stats.get("expected", 0)), seen["expected"]),
                    failed=max(int(stats.get("unexpected", 0)), seen["unexpected"]) + len(errors),
                    skipped=max(int(stats.get("skipped", 0)), seen["skipped"]),
                    flaky=max(int(stats.get("flaky", 0)), seen["flaky"]))
    except (TypeError, ValueError, AttributeError):
        return Verdict(reason="no report")
    first_failed = names["unexpected"] or (f"error: {_clean(errors[0].get('message'))}" if errors else "")
    return decide(v, first_failed, names["skipped"], names["flaky"], present, expected_files)


def combine(verdicts: list[Verdict]) -> Verdict:
    """Add up several verdicts. ok only when every one is ok; the reason is the first problem."""
    total = Verdict(passed=sum(v.passed for v in verdicts), failed=sum(v.failed for v in verdicts),
                    skipped=sum(v.skipped for v in verdicts), flaky=sum(v.flaky for v in verdicts))
    bad = [v for v in verdicts if not v.ok]
    total.ok = bool(verdicts) and not bad
    total.reason = bad[0].reason if bad else (f"all {total.passed} passed" if verdicts else "no checks")
    return total


# ------------------------------------------------------------- 2. the fast suite
def fast_suite_command(every_step: str, checkout: Path) -> str | None:
    """Return the project's fast test command, or None when it has none.

    The plan's `Every step` text wins when it names one: the first `inline
    code` that starts with pnpm/npm/npx/yarn/bun/node and mentions a test
    word (test, vitest, jest, playwright, mocha). Otherwise `pnpm test` when
    package.json has a `test` script (not npm's "no test specified" stub).
    """
    for code in re.findall(r"`([^`\n]+)`", every_step or ""):
        code = code.strip()
        if RUNNER.match(code) and TESTY.search(code):
            return code
    try:
        scripts = json.loads((Path(checkout) / "package.json").read_text()).get("scripts") or {}
    except (OSError, ValueError, AttributeError):
        return None
    test = scripts.get("test") if isinstance(scripts, dict) else None
    if isinstance(test, str) and test.strip() and test.strip() != NPM_DEFAULT_TEST:
        return "pnpm test"
    return None


def first_failing_test(text: str) -> str:
    """Find the name of the first failing test in a test runner's plain output ("" when none is found)."""
    lines = ANSI.sub("", text or "").splitlines()
    for pattern in FAILING_TEST_LINES:
        for line in lines:
            if m := pattern.match(line):
                return m.group(1).strip()
    return ""


def verify_command(step: int, fast: str | None, has_spec: bool) -> str:
    """Return the whole shell command for the verify container.

    Install (its exit code is ignored: pnpm 12 exits non-zero over ignored
    build scripts even when everything is installed), the fast suite with its
    output also copied to /out/fast-suite.txt, then the step's checks. The
    command exits 3 when the fast suite failed and 0 otherwise; the checks'
    own result is read from their reports, never from an exit code.
    """
    parts = ["[ -f package.json ] && pnpm install --frozen-lockfile", "fast_rc=0"]
    if fast:
        parts += [f"echo '### Phoenix: fast suite: {fast.replace(chr(39), '')}'",
                  f"( {fast} ) 2>&1 < /dev/null | tee {checks.OUT_MOUNT}/{FAST_SUITE_FILE}",
                  "fast_rc=${PIPESTATUS[0]}",
                  "echo \"### Phoenix: fast suite exit $fast_rc\""]
    parts += ["echo '### Phoenix: step checks'", checks.check_command(step, has_spec)]
    parts.append(f"[ \"$fast_rc\" -eq 0 ] || exit {FAST_SUITE_FAILED_RC}; exit 0")
    return "; ".join(parts)


# ------------------------------------------------------------- 3. verify_step
def report_dir(run_id: str, step: int, try_no: int) -> Path:
    """The folder for one verify's reports: runs/<id>/3-product/reports/<step>-<try>/."""
    return config.paths().runs / run_id / "3-product" / "reports" / f"{step}-{try_no}"


def secret_texts(env_file: Path | None) -> list[str]:
    """Every form of every project env value that must not reach a saved file, longest first (Step 5's scan list)."""
    if not env_file or not Path(env_file).is_file():
        return []
    forms = {f.decode("utf-8", "replace") for f in pgit.secret_forms(Path(env_file))}
    forms.update(claude.secrets_from([Path(env_file)]))
    return sorted(forms, key=len, reverse=True)


def redact_reports(out_dir: Path, env_file: Path | None) -> None:
    """Redact project env values from the text files in a report folder (images and zips are left alone)."""
    secrets = secret_texts(env_file)
    if not secrets:
        return
    for p in Path(out_dir).rglob("*"):
        if p.is_file() and not p.is_symlink() and p.suffix.lower() in REPORT_TEXT_SUFFIXES:
            text = p.read_text(errors="replace")
            clean = claude.redact(text, secrets)
            if clean != text:
                p.write_text(clean)


def copy_plain_files(src: Path, dest: Path) -> None:
    """Copy the regular files under src to dest (links and anything odd are skipped: the checkout is untrusted)."""
    if not src.is_dir() or src.is_symlink():
        return
    for folder, _, names in os.walk(src, followlinks=False):
        for name in names:
            p = Path(folder) / name
            if p.is_file() and not p.is_symlink():
                target = dest / p.relative_to(src)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, target, follow_symlinks=False)


def save_project_artifacts(checkout: Path, out_dir: Path) -> None:
    """Keep the screenshots and traces the fast suite left in the checkout, under <report folder>/fast-suite/.

    The step checks already write theirs straight into the report folder
    (Playwright's outputDir is /out/test-results).
    """
    for name in PROJECT_ARTIFACTS:
        copy_plain_files(Path(checkout) / name, Path(out_dir) / "fast-suite" / name)


def judge_reports(out_dir: Path, files: list[str]) -> Verdict:
    """Judge the step's check reports in a report folder: Vitest for `*.test.ts`, Playwright for `*.spec.ts`."""
    tests = [f for f in files if f.endswith(".test.ts")]
    specs = [f for f in files if f.endswith(".spec.ts")]
    verdicts = []
    if tests:
        verdicts.append(judge_vitest(Path(out_dir) / "vitest.json", tests))
    if specs:
        verdicts.append(judge_playwright(Path(out_dir) / "playwright.json", specs))
    return combine(verdicts)


def _number(step) -> int:
    """Accept a plan.Step or a plain step number."""
    return int(step.number if isinstance(step, pplan.Step) else step)


def verify_step(run: dict, step, sha: str, *, try_no: int = 1, container=docker.run_check_container,
                settings: dict | None = None) -> Verdict:
    """Run the step's checks and the project's fast suite on commit `sha`. Return the Verdict.

    A clean checkout of the commit (Step 5) goes into one check container
    (Step 4, role `verify`, `checker_timeout_min`). The locked checks are
    mounted read-only over the checkout, and their hashes are checked before
    and after the run. Output: runs/<id>/logs/<step>-<try>-verify.txt.
    Reports, screenshots and traces: runs/<id>/3-product/reports/<step>-<try>/.
    """
    s = settings or config.load()
    run_id, repo, number = run["run_id"], run["repo"], _number(step)
    env_file = checks.project_env_file(repo)
    every_step = checks.load_plan(run).every_step if run.get("plan_path") else ""
    out_dir = report_dir(run_id, number, try_no)
    checkout = pgit.fresh_checkout(repo, sha)
    try:
        try:
            checks.verify_lock(checkout)
        except checks.LockBroken as e:
            return _done(run_id, number, try_no, Verdict(reason=str(e)))
        files = checks.step_check_files(checkout, number)
        if not files:
            return _done(run_id, number, try_no, Verdict(reason="no checks"))
        fast = fast_suite_command(every_step, checkout)
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True)
        docker.hand_to_agent(out_dir)
        command = verify_command(number, fast, any(f.endswith(".spec.ts") for f in files))
        mounts = checks.check_mounts(out_dir) + [
            docker.Mount(checkout / checks.CHECKS_ROOT, f"/workspace/{checks.CHECKS_ROOT}")]
        rc, _ = container(run_id, number, try_no, checkout, command, env_file, checks.domains_file(repo),
                          s["checker_timeout_min"], role=ROLE, mounts=mounts, settings=s)
        save_project_artifacts(checkout, out_dir)
        redact_reports(out_dir, env_file)
        verdict = judge(rc, out_dir, files, fast, s["checker_timeout_min"])
        try:
            checks.verify_lock(checkout)
        except checks.LockBroken as e:
            verdict.ok, verdict.reason = False, f"during verify: {e}"
    finally:
        pgit.remove_workspace(checkout)
    return _done(run_id, number, try_no, verdict)


def judge(rc: int, out_dir: Path, files: list[str], fast: str | None, timeout_min: float) -> Verdict:
    """Combine the container's exit code with the report files. The exit code can only fail a step, never pass it."""
    verdict = judge_reports(out_dir, files)
    if rc == docker.TIMEOUT_RC:
        verdict.ok, verdict.reason = False, f"timed out after {timeout_min:g} minutes"
    elif rc == FAST_SUITE_FAILED_RC and fast:
        try:
            output = (Path(out_dir) / FAST_SUITE_FILE).read_text(errors="replace")
        except OSError:
            output = ""
        name = first_failing_test(output) or f"`{fast}` failed (no failing test name found)"
        verdict.ok, verdict.reason = False, f"fast suite: {name}"
    elif rc != 0:
        verdict.ok = False
        verdict.reason = f"the check container ended with exit {rc}" + (
            "" if verdict.reason.startswith("all ") else f"; {verdict.reason}")
    return verdict


def _done(run_id: str, number: int, try_no: int, verdict: Verdict) -> Verdict:
    """Log the verdict in the run log and return it."""
    log(run_id, f"step {number}: verify try {try_no} {'passed' if verdict.ok else 'failed'}: {verdict.reason} "
                f"(passed {verdict.passed}, failed {verdict.failed}, skipped {verdict.skipped}, flaky {verdict.flaky})")
    return verdict


# ------------------------------------------------------------- 4. feedback for the next try
def feedback(verdict: Verdict, log_path: Path, env_file: Path | None = None) -> str:
    """Return what the builder is told after a failed verify: the reason and the last 80 lines of output.

    Values from the project env file are redacted (every form Step 5's secret
    scan looks for). Tail idea borrowed from Phoenix 0.6.0 hands/loop.py:843-847.
    """
    try:
        lines = ANSI.sub("", Path(log_path).read_text(errors="replace")).splitlines()
    except OSError:
        lines = []
    tail = "\n".join(lines[-TAIL_LINES:]) if lines else "(no output was saved)"
    text = f"The checks did not pass: {verdict.reason}\n\nLast {TAIL_LINES} lines of output:\n{tail}"
    return claude.redact(text, secret_texts(env_file))
