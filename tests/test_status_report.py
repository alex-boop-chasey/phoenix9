"""Tests for the daily status report: fixture state for every section, the file, the command and the API route."""
import json
import subprocess
import time

import pytest

from phoenix9 import atomic, doctor, edits, gates, paths, state, statusreport, updater, watch
from phoenix9.__main__ import main

NOW = time.time()


def _iso(ago_s):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(NOW - ago_s, timezone.utc).isoformat(timespec="seconds")


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True)


def make_project(name="demo"):
    folder = paths.projects() / name
    code = folder / "code"
    code.mkdir(parents=True)
    (folder / "CLAUDE.md").write_text("x\n")
    _git(code, "init", "-q", "-b", "main")
    (code / "a").write_text("a\n")
    _git(code, "add", "-A")
    _git(code, "commit", "-q", "-m", "first")
    return folder


def make_run(run_id, status, project="demo", ago_s=0, flagged=""):
    run = paths.runs(project) / run_id
    run.mkdir(parents=True)
    st = state.new_state(run_id, project, {"1": state.new_task("t")})
    st.update(status=status, created=_iso(ago_s), updated=_iso(ago_s))
    st["tasks"]["1"].update(status="failed" if status == "failed" else "running", flagged=flagged)
    atomic.write_json(run / "state.json", st)
    return run


@pytest.fixture
def quiet(monkeypatch, adapters):
    """No update, a healthy doctor, no merge requests: only what a test sets up shows."""
    monkeypatch.setattr(updater, "status", lambda a: {"update_available": False})
    monkeypatch.setattr(doctor, "run_checks", lambda a, mode="full": {"ok": True, "checks": []})
    monkeypatch.setattr(statusreport, "_open_prs", lambda a: [])
    return adapters


def build(adapters):
    return statusreport.build(adapters, NOW)


def test_empty_state_says_nothing_needs_you(quiet):
    text = build(quiet)
    assert "Nothing needs you" in text and "##" not in text


def test_waiting_for_alex_with_age(quiet):
    make_project()
    run = make_run("r1", "running")
    gates.open_gate(run, kind="escalation", title="Task 2 failed", why="because")
    gate = gates.list_gates()[0]
    atomic.write_json(run / "gates" / f"{gate['id']}.json", {**gate, "created": _iso(2 * 86400)})
    text = build(quiet)
    assert "## Waiting for Alex" in text and "Task 2 failed, waiting 2 days" in text
    assert f"phoenix gate answer {gate['id']}" in text


def test_builds_running_failed_and_repeated(quiet):
    make_project()
    make_run("run-a", "running", ago_s=10)
    make_run("run-b", "failed", ago_s=86400, flagged="the tests failed")
    make_run("run-c", "failed", ago_s=2 * 86400, flagged="the tests failed")
    make_run("run-old", "failed", ago_s=9 * 86400, flagged="ancient")
    text = build(quiet)
    assert "## Builds" in text and "build run-a is running" in text
    assert "build run-b failed: the tests failed" in text and "run-old" not in text
    assert "2 builds failed with the same reason (the tests failed)" in text
    assert "phoenix repair report run-b" in text


def test_merge_requests_older_than_three_days(quiet, monkeypatch):
    rows = [{"project": "demo", "number": 4, "title": "Old one", "created": _iso(4 * 86400)},
            {"project": "demo", "number": 5, "title": "New one", "created": _iso(86400)}]
    monkeypatch.setattr(statusreport, "_open_prs", lambda a: rows)
    text = build(quiet)
    assert "## Merge requests open more than 3 days" in text and "#4" in text and "#5" not in text


def test_quick_edit_stalled(quiet):
    make_project()
    rec = edits.start("demo", "Fix typo")
    atomic.write_json(edits.record_file(rec["id"]), {**rec, "status": "stalled"})
    text = build(quiet)
    assert "## Quick edits stalled" in text and "Fix typo" in text and f"phoenix edit abandon {rec['id']}" in text


def test_phoenix_section(quiet, monkeypatch):
    monkeypatch.setattr(updater, "status", lambda a: {"update_available": True, "newest": "v9.9"})
    monkeypatch.setattr(doctor, "run_checks", lambda a, mode="full": {"ok": False, "checks": [
        {"name": "proxy-rule", "ok": False, "detail": "rule missing", "fix": "Reinstall."},
        {"name": "disk", "ok": False, "detail": "low", "fix": "x"}]})
    monkeypatch.setattr(statusreport.shutil, "disk_usage", lambda p: type("U", (), {"free": 5, "total": 100})())
    make_project()
    make_run("run-a", "running")
    from phoenix9 import heartbeat
    heartbeat.write(NOW - 3600)
    text = build(quiet)
    assert "## Phoenix" in text and "update is available (v9.9)" in text
    assert "worker is not responding" in text and "5% free" in text
    assert "Doctor: proxy-rule: rule missing" in text and "Doctor: disk" not in text


def test_projects_with_problems(quiet):
    folder = make_project()
    (folder / "phoenix.toml").write_text("this is [not valid\n")
    text = build(quiet)
    assert "## Projects with problems" in text and "phoenix.toml is not valid" in text


def test_unpushed_commits_and_empty_keys(quiet, tmp_path, monkeypatch):
    folder = make_project()
    code = folder / "code"
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    _git(code, "remote", "add", "origin", str(remote))
    _git(code, "push", "-q", "-u", "origin", "main")
    (code / "b").write_text("b\n")
    _git(code, "add", "-A")
    _git(code, "commit", "-q", "-m", "second")
    from phoenix9 import keys, project_services, services
    monkeypatch.setattr(project_services, "chosen", lambda p: ["acme"])
    monkeypatch.setattr(services, "load_library", lambda: {"acme": {"project_keys": [{"name": "ACME_KEY", "secret": True}]}})
    keys.add_empty("demo", "ACME_KEY")
    text = build(quiet)
    assert "1 commit not pushed" in text and "ACME_KEY" in text


def test_command_writes_file_and_out(quiet, tmp_path, capsys):
    make_run("run-a", "running")
    assert main(["report", "status"]) == 0
    capsys.readouterr()
    assert "run-a is running" in (paths.home() / "reports" / "status.md").read_text()
    out = tmp_path / "mine.md"
    assert main(["report", "status", "--out", str(out), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["path"] == str(out) and out.read_text() == data["text"]


def test_runner_loop_writes_every_ten_minutes(quiet):
    memory = watch.Memory()
    watch.write_status_report(quiet, memory)
    assert statusreport.report_path().exists()
    statusreport.report_path().unlink()
    watch.write_status_report(quiet, memory)
    assert not statusreport.report_path().exists()
    memory.report_written -= watch.REPORT_EVERY_S
    watch.write_status_report(quiet, memory)
    assert statusreport.report_path().exists()
