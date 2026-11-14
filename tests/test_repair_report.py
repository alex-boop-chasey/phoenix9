"""Tests for the run report: healthy run, a fix line per finding, rewritten on change, the 5-line tail, no secrets."""
import json

from test_repair_check import G1, RUN, build, line, run_line, task

from phoenix9 import __main__ as cli_main, atomic, state
from phoenix9.repair import check, report


def failed_run(tmp_path):
    """A failed run whose task 1 failed with a reason and checks output."""
    run_dir = build(tmp_path, "failed", {"1": {**task("failed", 1), "flagged": "tests did not pass"}},
                    attempts={1: ["failed"]})
    return run_dir


def test_healthy_run(tmp_path):
    run_dir = failed_run(tmp_path)
    text = report.write(run_dir)
    assert (run_dir / "repairs" / "report.md").read_text() == text
    assert "Status: failed" in text and "Task 1 (T): failed, try 1" in text
    assert "tests did not pass" in text
    assert "No problems found." not in text and "Repair note lines" not in text
    assert "Nothing is inconsistent, but the run failed" in text and "## Failed steps" not in text
    assert "Branch: phoenix/" + RUN in text and "Env files found: none" in text
    assert "No question is open." in text


def test_every_finding_has_a_fix_line(tmp_path):
    run_dir = build(tmp_path, "failed", {"1": task("running", 1)}, [line("build", "running")],
                    current={"gate": G1}, gate_files=[(1, "closed")], attempts={1: [None]})
    found = check.run_checks(run_dir)
    assert found
    text = report.write(run_dir)
    for f in found:
        assert report.fix_line(f) in text
        assert not report.fix_line(f).startswith("- (no ready fix")
    assert "- set task 1 to failed" in text


def test_env_file_finding_line(tmp_path):
    run_dir = failed_run(tmp_path)
    from phoenix9.repair.snapshot import worktree_of
    (worktree_of(run_dir) / ".env").write_text("API_TOKEN=supersecretvalue123\n")
    text = report.write(run_dir)
    assert "- delete env file .env" in text and "Env files found: .env" in text
    assert "supersecretvalue123" not in text


def test_open_question_shown(tmp_path):
    run_dir = build(tmp_path, "waiting", {"1": task("waiting", 1, gate=G1)}, current={"gate": G1},
                    gate_files=[(1, None)], attempts={1: [None]})
    text = report.write(run_dir)
    assert f"- {G1}: t" in text and "actions:" in text


def test_rewritten_when_state_changes(tmp_path):
    run_dir = failed_run(tmp_path)
    assert "tests did not pass" in report.write(run_dir)
    state.update(run_dir, lambda s: s["tasks"]["1"].update(flagged="a new reason"))
    text = report.write(run_dir)
    assert "a new reason" in text and "tests did not pass" not in text


def test_five_line_tail_scrubbed(tmp_path):
    run_dir = failed_run(tmp_path)
    lines = [f"line {i}" for i in range(1, 9)] + ["API_TOKEN=supersecretvalue123"]
    atomic.write_text(run_dir / "tasks/1/attempt-1/checks.txt", "\n".join(lines) + "\n")
    text = report.write(run_dir)
    assert "line 5" in text and "line 4" not in text and "line 8" in text
    assert "supersecretvalue123" not in text


def test_cli_report(tmp_path, capsys):
    run_dir = failed_run(tmp_path)
    assert cli_main.main(["repair", "report", RUN]) == 0
    assert "# Run report" in capsys.readouterr().out
    assert (run_dir / "repairs" / "report.md").is_file()
    assert cli_main.main(["repair", "report", RUN, "--json"]) == 0
    assert '"path"' in capsys.readouterr().out


def failed_suite_run(tmp_path):
    """A failed run whose tasks all passed but whose full suite failed."""
    note = "The checks did not pass:\n2 tests failed\nAPI_TOKEN=supersecretvalue123"
    return build(tmp_path, "failed", {"1": task("passed", 1)}, [run_line("full-suite", "failed", note=note)],
                 attempts={1: ["passed"]})


def test_failed_steps_shown_and_never_no_problems(tmp_path):
    text = report.write(failed_suite_run(tmp_path))
    assert "## Failed steps" in text and "- Full suite: failed" in text and "      2 tests failed" in text
    assert "Nothing is inconsistent, but these steps failed:" in text
    assert "No problems found." not in text and "supersecretvalue123" not in text


def test_done_run_with_no_findings_says_no_problems(tmp_path):
    run_dir = build(tmp_path, "done", {"1": task("passed", 1)}, attempts={1: ["passed"]})
    assert "No problems found." in report.write(run_dir)


def test_cli_report_json_lists_failed_steps(tmp_path, capsys):
    failed_suite_run(tmp_path)
    assert cli_main.main(["repair", "report", RUN, "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [f["title"] for f in out["failed_steps"]] == ["Full suite"]
    assert out["failed_steps"][0]["reasons"][0] == "2 tests failed"
    assert "supersecretvalue123" not in json.dumps(out)
