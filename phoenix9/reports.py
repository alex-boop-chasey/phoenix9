"""Test report readers: turn a test runner's report file into one Report that says passed or failed."""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

from phoenix9 import scrub, settings

TAIL_LINES = 80
SKIPPED_STATES = ("skipped", "pending", "todo", "disabled")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
REPORT_FILES = {"vitest-json": "vitest.json", "playwright-json": "playwright.json",
                "pytest-junit": "pytest.xml", "exit-code": "exit-code.txt"}
REPORT_TEXT_SUFFIXES = (".json", ".txt", ".md", ".html", ".log", ".xml")


@dataclass
class Report:
    """What a test run showed. `ok` is the only thing that means "passed"."""

    ok: bool = False
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    flaky: int = 0
    first_failed: str = ""
    missing_files: list = field(default_factory=list)
    reader: str = ""
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """The report as plain data (the test-report.json shape)."""
        return asdict(self)

    @property
    def reason(self) -> str:
        """The first note: why the run is not ok, or the all-passed line."""
        return self.notes[0] if self.notes else ""


# ------------------------------------------------------------- helpers
def _clean(text) -> str:
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


def _in_report(expected: str, present: set) -> bool:
    """True when a check file (repo path) appears in the report's file names (compared by their ends)."""
    return any(p == expected or p.endswith("/" + expected) or expected.endswith("/" + p) for p in present)


def _no_report(reader: str) -> Report:
    """The Report for a missing or unreadable report file."""
    return Report(reader=reader, notes=[f"the test run produced no {reader} report"])


def decide(r: Report, first_skipped: str = "", first_flaky: str = "", present: set = frozenset(),
           expected=()) -> Report:
    """Set `ok` and the first note from the counts. ok needs passed >= 1 and nothing failed, skipped, flaky or missing."""
    r.missing_files = [e for e in expected if not _in_report(e, present)]
    if r.failed:
        reason = f"{r.failed} failed: {r.first_failed or 'unknown test'}"
    elif r.flaky:
        reason = f"{r.flaky} flaky (failed, then passed on a retry): {first_flaky or 'unknown test'}"
    elif r.skipped:
        reason = f"{r.skipped} skipped: {first_skipped or 'unknown test'}"
    elif r.missing_files:
        reason = "not in the report: " + ", ".join(r.missing_files)
    elif r.passed < 1:
        reason = "no checks passed (0 passed)"
    else:
        r.ok = True
        reason = f"all {r.passed} passed"
    r.notes.insert(0, reason)
    return r


# ------------------------------------------------------------- readers
def read_vitest(out_dir, expected_files=()) -> Report:
    """Read vitest.json: counts come from each test's own status; a file that could not load counts as a failure."""
    # ported from reference/v8/phoenix/verify.py:judge_vitest
    data = _read_json(Path(out_dir) / REPORT_FILES["vitest-json"])
    if data is None or not isinstance(data.get("testResults"), list):
        return _no_report("vitest-json")
    r = Report(reader="vitest-json")
    first_skipped = ""
    present: set = set()
    try:
        for result in data["testResults"]:
            name = str(result.get("name", ""))
            present.add(name)
            short = name.split("/workspace/", 1)[-1]
            failed_here = 0
            for t in result.get("assertionResults") or []:
                status = t.get("status")
                title = t.get("fullName") or t.get("title") or "unnamed test"
                if status == "passed":
                    r.passed += 1
                elif status == "failed":
                    failed_here += 1
                    r.first_failed = r.first_failed or f"{short} > {title}"
                elif status in SKIPPED_STATES:
                    r.skipped += 1
                    first_skipped = first_skipped or f"{short} > {title} ({status})"
            if result.get("status") == "failed" and not failed_here:
                failed_here = 1
                r.first_failed = r.first_failed or f"{short} could not run: {_clean(result.get('message'))}"
            r.failed += failed_here
        r.passed = min(r.passed, int(data.get("numPassedTests", r.passed)))
        r.failed = max(r.failed, int(data.get("numFailedTests", 0)))
        r.skipped = max(r.skipped, int(data.get("numPendingTests", 0)) + int(data.get("numTodoTests", 0)))
    except (TypeError, ValueError, AttributeError):
        return _no_report("vitest-json")
    return decide(r, first_skipped, "", present, expected_files)


def _walk_suites(suites, specs: list, files: set) -> None:
    """Collect every spec and file name from Playwright's nested suites."""
    # ported from reference/v8/phoenix/verify.py:_walk_suites
    for suite in suites or []:
        if suite.get("file"):
            files.add(str(suite["file"]))
        for spec in suite.get("specs") or []:
            specs.append(spec)
            if spec.get("file"):
                files.add(str(spec["file"]))
        _walk_suites(suite.get("suites"), specs, files)


def read_playwright(out_dir, expected_files=()) -> Report:
    """Read playwright.json: expected/unexpected/skipped/flaky counts (the stricter number wins); top-level errors fail."""
    # ported from reference/v8/phoenix/verify.py:judge_playwright
    data = _read_json(Path(out_dir) / REPORT_FILES["playwright-json"])
    if data is None or not isinstance(data.get("stats"), dict):
        return _no_report("playwright-json")
    specs: list = []
    present: set = set()
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
        r = Report(reader="playwright-json", passed=min(int(stats.get("expected", 0)), seen["expected"]),
                   failed=max(int(stats.get("unexpected", 0)), seen["unexpected"]) + len(errors),
                   skipped=max(int(stats.get("skipped", 0)), seen["skipped"]),
                   flaky=max(int(stats.get("flaky", 0)), seen["flaky"]))
    except (TypeError, ValueError, AttributeError):
        return _no_report("playwright-json")
    r.first_failed = names["unexpected"] or (f"error: {_clean(errors[0].get('message'))}" if errors else "")
    return decide(r, names["skipped"], names["flaky"], present, expected_files)


def read_pytest(out_dir, expected_files=()) -> Report:
    """Read pytest.xml (JUnit): a failure or error is failed, a skipped testcase is skipped."""
    path = Path(out_dir) / REPORT_FILES["pytest-junit"]
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return _no_report("pytest-junit")
    r = Report(reader="pytest-junit")
    first_skipped = ""
    present: set = set()
    for case in root.iter("testcase"):
        classname, name = case.get("classname", ""), case.get("name", "unnamed test")
        file = case.get("file") or classname.replace(".", "/")
        if not case.get("file") and file:
            file += ".py"
        if file:
            present.add(file)
        label = f"{classname}::{name}" if classname else name
        if case.find("failure") is not None or case.find("error") is not None:
            r.failed += 1
            r.first_failed = r.first_failed or label
        elif case.find("skipped") is not None:
            r.skipped += 1
            first_skipped = first_skipped or label
        else:
            r.passed += 1
    return decide(r, first_skipped, "", present, expected_files)


def read_exit_code(out_dir, expected_files=()) -> Report:
    """Read exit-code.txt (written by the step): ok when the number in it is 0."""
    try:
        rc = int((Path(out_dir) / REPORT_FILES["exit-code"]).read_text().strip().split()[0])
    except (OSError, ValueError, IndexError):
        return _no_report("exit-code")
    if rc == 0:
        return Report(ok=True, passed=1, reader="exit-code", notes=["the command exited 0"])
    return Report(failed=1, first_failed=f"the command exited {rc}", reader="exit-code",
                  notes=[f"the command exited {rc}"])


READERS = {"vitest-json": read_vitest, "playwright-json": read_playwright,
           "pytest-junit": read_pytest, "exit-code": read_exit_code}
# which check files each reader is responsible for (None = all of them)
_SUFFIXES = {"vitest-json": (".test.ts", ".test.tsx", ".test.js"), "playwright-json": (".spec.ts", ".spec.js"),
             "pytest-junit": (".py",), "exit-code": None}


def check_names(names) -> None:
    """Raise a settings error when a reader name is not one of settings.PROFILE_REPORTS."""
    for n in names:
        if n not in settings.PROFILE_REPORTS or n not in READERS:
            raise settings.SettingsError(f"unknown report reader '{n}' (use {', '.join(settings.PROFILE_REPORTS)})")


def combine(reports: list) -> Report:
    """Add up several reports. ok only when every one is ok; the first note is the first problem."""
    # ported from reference/v8/phoenix/verify.py:combine
    total = Report(passed=sum(r.passed for r in reports), failed=sum(r.failed for r in reports),
                   skipped=sum(r.skipped for r in reports), flaky=sum(r.flaky for r in reports),
                   reader="+".join(r.reader for r in reports))
    bad = [r for r in reports if not r.ok]
    total.ok = bool(reports) and not bad
    total.first_failed = next((r.first_failed for r in reports if r.first_failed), "")
    total.missing_files = [m for r in reports for m in r.missing_files]
    if not reports:
        total.notes = ["no checks"]
    elif bad:
        total.notes = [r.reason for r in bad]
    else:
        total.notes = [f"all {total.passed} passed"]
    return total


def _files_for(reader: str, expected_files) -> list:
    """The expected check files this reader is responsible for."""
    suffixes = _SUFFIXES[reader]
    return list(expected_files) if suffixes is None else [f for f in expected_files if f.endswith(suffixes)]


def judge(rc: int, out_dir, reader_names, expected_files=(), timed_out: bool = False) -> Report:
    """Read the named reports and combine them with the exit code; the exit code can only fail a run, never pass it."""
    # ported from reference/v8/phoenix/verify.py:judge
    names = list(reader_names)
    check_names(names)
    expected = list(expected_files)
    wanted = [n for n in names if not expected or _SUFFIXES[n] is None or _files_for(n, expected)] or names
    report = combine([READERS[n](out_dir, _files_for(n, expected)) for n in wanted])
    if timed_out:
        report.ok = False
        report.notes.insert(0, "the test run timed out")
    elif rc != 0 and report.ok:
        report.ok = False
        report.notes.insert(0, f"the test run ended with exit {rc} although its report is green")
    return report


# ------------------------------------------------------------- redaction and feedback
def redact_reports(out_dir, secrets=None) -> None:
    """Scrub known secret values out of the text files in a report folder (images and zips are left alone)."""
    # ported from reference/v8/phoenix/verify.py:redact_reports
    scrubber = scrub.Scrubber(list(secrets or []) + scrub.known_secrets())
    for p in Path(out_dir).rglob("*"):
        if p.is_file() and not p.is_symlink() and p.suffix.lower() in REPORT_TEXT_SUFFIXES:
            text = p.read_text(errors="replace")
            clean = scrubber.text(text)
            if clean != text:
                p.write_text(clean)


def feedback(report: Report, log_path) -> str:
    """What the Builder is told after a failed verify: the reason and the last 80 lines of output, scrubbed."""
    # ported from reference/v8/phoenix/verify.py:feedback
    try:
        lines = ANSI.sub("", Path(log_path).read_text(errors="replace")).splitlines()
    except OSError:
        lines = []
    tail = "\n".join(lines[-TAIL_LINES:]) if lines else "(no output was saved)"
    return scrub.scrub(f"The checks did not pass: {report.reason}\n\nLast {TAIL_LINES} lines of output:\n{tail}")


# ------------------------------------------------------------- fallback when Verify is off
def fallback_report(ctx) -> dict:
    """A test report built from Acceptance's results, for runs where Verify is off."""
    codes = ctx.things.get("exit-codes")
    r = Report(reader="exit-codes-only")
    if isinstance(codes, list) and codes:
        for item in codes:
            if item.get("exit_code") == 0:
                r.passed += 1
            else:
                r.failed += 1
                r.first_failed = r.first_failed or str(item.get("command", ""))
    else:
        n = ctx.task["number"] if ctx.task else 0
        path = ctx.run.folder / "tasks" / str(n) / f"attempt-{ctx.attempt}" / "checks.txt"
        text = path.read_text(errors="replace") if path.exists() else ""
        last = ""
        for line in text.splitlines():
            if line.startswith("$ "):
                last = line[2:]
            elif m := re.match(r"exit (-?\d+) in ", line):
                if m.group(1) == "0":
                    r.passed += 1
                else:
                    r.failed += 1
                    r.first_failed = r.first_failed or last
    r.ok = r.passed > 0 and r.failed == 0
    r.notes = ["from Acceptance's exit codes only (Verify is off)"] if (r.passed or r.failed) else [
        "no check results to report"]
    return r.to_dict()


FALLBACK_VALUES = {"test-report": fallback_report}
