"""The report readers: vitest, playwright, pytest-junit, exit-code, combine and judge."""
import shutil
from pathlib import Path

import pytest

from phoenix9 import reports, settings

DATA = Path(__file__).parent / "data" / "reports"


def folder(tmp_path, **files):
    """A report folder holding copies of sample files: name-in-folder=sample-name."""
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    for dest, sample in files.items():
        shutil.copy(DATA / sample, out / dest)
    return out


def test_vitest_reader_pass_fail_skip(tmp_path):
    ok = reports.READERS["vitest-json"](folder(tmp_path, **{"vitest.json": "vitest-pass.json"}), [])
    assert ok.ok and ok.passed == 2
    bad = reports.READERS["vitest-json"](folder(tmp_path, **{"vitest.json": "vitest-mixed.json"}), [])
    assert not bad.ok and (bad.passed, bad.failed, bad.skipped) == (1, 1, 2)
    assert bad.first_failed == "tests/phoenix/task-1/a.test.ts > fails"


def test_playwright_reader_flaky_and_failed(tmp_path):
    flaky = reports.READERS["playwright-json"](folder(tmp_path, **{"playwright.json": "playwright-flaky.json"}), [])
    assert not flaky.ok and flaky.flaky == 1 and "flaky" in flaky.reason
    failed = reports.READERS["playwright-json"](folder(tmp_path, **{"playwright.json": "playwright-failed.json"}), [])
    assert not failed.ok and failed.failed == 1 and "submits" in failed.first_failed


def test_pytest_junit_reader_failure_error_skip(tmp_path):
    r = reports.READERS["pytest-junit"](folder(tmp_path, **{"pytest.xml": "pytest-mixed.xml"}), [])
    assert (r.passed, r.failed, r.skipped) == (1, 2, 1) and not r.ok
    assert r.first_failed.endswith("::test_bad")
    ok = reports.READERS["pytest-junit"](folder(tmp_path, **{"pytest.xml": "pytest-pass.xml"}),
                                         ["tests/phoenix/task-1/test_1.py"])
    assert ok.ok and ok.missing_files == []


def test_pytest_expected_file_missing_from_report(tmp_path):
    r = reports.READERS["pytest-junit"](folder(tmp_path, **{"pytest.xml": "pytest-pass.xml"}), ["tests/other.py"])
    assert not r.ok and r.missing_files == ["tests/other.py"]


def test_exit_code_reader(tmp_path):
    out = tmp_path / "o"
    out.mkdir()
    (out / "exit-code.txt").write_text("0\n")
    assert reports.READERS["exit-code"](out, []).ok
    (out / "exit-code.txt").write_text("2\n")
    r = reports.READERS["exit-code"](out, [])
    assert not r.ok and r.failed == 1


def test_missing_report_fails_with_reason(tmp_path):
    r = reports.judge(0, tmp_path, ["vitest-json"], [], False)
    assert not r.ok and r.reason == "the test run produced no vitest-json report"


def test_nonzero_exit_with_green_report_fails(tmp_path):
    out = folder(tmp_path, **{"pytest.xml": "pytest-pass.xml"})
    assert reports.judge(0, out, ["pytest-junit"], [], False).ok
    r = reports.judge(1, out, ["pytest-junit"], [], False)
    assert not r.ok and "exit 1" in r.reason
    assert not reports.judge(124, out, ["pytest-junit"], [], True).ok


def test_combine_any_failed(tmp_path):
    good = reports.Report(ok=True, passed=2, reader="a", notes=["all 2 passed"])
    bad = reports.Report(failed=1, first_failed="x", reader="b", notes=["1 failed: x"])
    c = reports.combine([good, bad])
    assert not c.ok and c.passed == 2 and c.failed == 1 and c.reason == "1 failed: x"
    assert reports.combine([good, good]).ok
    assert not reports.combine([]).ok


def test_unknown_reader_is_a_settings_error(tmp_path):
    with pytest.raises(settings.SettingsError):
        reports.judge(0, tmp_path, ["nope"], [], False)


def test_readers_match_profile_names():
    assert sorted(reports.READERS) == sorted(settings.PROFILE_REPORTS)


def test_feedback_is_scrubbed(tmp_path):
    log = tmp_path / "log.txt"
    log.write_text("line\nFAILED x\n")
    text = reports.feedback(reports.Report(notes=["1 failed: x"]), log)
    assert "1 failed: x" in text and "FAILED x" in text
