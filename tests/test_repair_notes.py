"""Tests for applying repair notes: the task steps, rollback, force, refusals, dry run and the four records."""
import json
import time

import pytest
from helpers.repair_runs import make_run, sh

from phoenix9 import __main__ as cli_main, atomic, heartbeat, paths, state
from phoenix9.repair import apply as apply_mod, check, snapshot


def tasks():
    """Three tasks: 1 failed, 2 depends on 1 (skipped), 3 independent and pending."""
    t = state.new_task
    one = {**t("One"), "status": "failed", "tries": 2, "flagged": "it broke", "failures": ["a", "b"]}
    two = {**t("Two", [1]), "status": "skipped", "note": "depends on task 1, which failed"}
    three = {**t("Three", [1]), "status": "pending"}
    four = {**t("Four", [3]), "status": "pending"}
    return {"1": one, "2": two, "3": three, "4": four}


def make(tmp_path, status="failed"):
    """A fixture run with tasks in its state."""
    r = make_run(tmp_path, status=status)
    st = state.load(r["run_dir"])
    st["tasks"] = tasks()
    atomic.write_json(r["run_dir"] / "state.json", st)
    return r


def note(tmp_path, r, *steps, why="Fix the thing"):
    """Write a repair note file for the run."""
    body = "\n".join(f"- {s}" for s in steps)
    f = tmp_path / "note.md"
    f.write_text(f"# Repair {r['run']}\n\nWhy: {why}\n\n## Steps\n\n{body}\n")
    return f


def task(r, n):
    """One task entry from the run's state."""
    return state.load(r["run_dir"])["tasks"][str(n)]


def snapshot_of_files(r):
    """Every file of the run folder and the worktree facts, to compare before and after."""
    files = {p.relative_to(r["run_dir"]).as_posix(): p.read_bytes() for p in sorted(r["run_dir"].rglob("*"))
             if p.is_file()}
    return files, sh(r["work"], "rev-parse", "HEAD"), sh(r["work"], "status", "--porcelain")


def test_mark_done(tmp_path):
    r = make(tmp_path)
    out = apply_mod.apply(note(tmp_path, r, "mark task 1 done because I fixed it by hand"), "agent")
    assert out["ok"] and not out["rolled_back"]
    t = task(r, 1)
    assert t["status"] == "passed" and t["note"] == "I fixed it by hand" and t["flagged"] == ""
    assert t["failures"] == ["a", "b"]


def test_mark_skipped_skips_dependents(tmp_path):
    r = make(tmp_path)
    apply_mod.apply(note(tmp_path, r, "mark task 3 skipped because not needed"), "agent")
    assert task(r, 3)["status"] == "skipped" and task(r, 3)["note"] == "not needed"
    assert task(r, 4)["status"] == "skipped" and "task 3" in task(r, 4)["note"]
    assert task(r, 1)["status"] == "failed"


def test_retry_keeps_failures(tmp_path):
    r = make(tmp_path)
    apply_mod.apply(note(tmp_path, r, "retry task 1", "force"), "agent")
    t = task(r, 1)
    assert t["status"] == "pending" and t["rerun"] is True and t["failures"] == ["a", "b"]


def test_clear_failures_and_add_note(tmp_path):
    r = make(tmp_path)
    apply_mod.apply(note(tmp_path, r, "clear failures of task 1", "add a note to task 1: use the new helper"), "agent")
    assert task(r, 1)["failures"] == ["Note from the repair: use the new helper"]


def test_new_problem_without_resume_is_rolled_back(tmp_path):
    r = make(tmp_path)                      # a failed run with a pending task is a problem until it resumes
    out = apply_mod.apply(note(tmp_path, r, "retry task 1"), "agent")
    assert out["rolled_back"] and task(r, 1)["status"] == "failed"
    assert "task 1 is still pending" in " ".join(out["check_after"])


def break_check(monkeypatch):
    """Make the check find a new problem after the steps."""
    real = check.run_checks
    calls = []

    def fake(run_dir, as_run=None):
        calls.append(1)
        found = real(run_dir, as_run)
        return found + ([check.Finding("bad", "Something is broken now.")] if len(calls) > 1 else [])
    monkeypatch.setattr(check, "run_checks", fake)


def test_failing_check_rolls_back(tmp_path, monkeypatch):
    r = make(tmp_path)
    before = snapshot_of_files(r)[0]["state.json"]
    break_check(monkeypatch)
    out = apply_mod.apply(note(tmp_path, r, "retry task 1"), "agent")
    assert not out["ok"] and out["rolled_back"] and out["check_after"][-1] == "Something is broken now."
    assert (r["run_dir"] / "state.json").read_bytes() == before
    assert "Rolled back" in (tmp_path / "note.md").read_text()


def test_force_keeps_it(tmp_path, monkeypatch):
    r = make(tmp_path)
    break_check(monkeypatch)
    out = apply_mod.apply(note(tmp_path, r, "retry task 1", "force"), "agent")
    assert out["ok"] and out["forced"] and not out["rolled_back"]
    assert task(r, 1)["status"] == "pending"


def test_refused_step_rolls_back_earlier_steps(tmp_path):
    r = make(tmp_path)
    before = (r["run_dir"] / "state.json").read_bytes()
    out = apply_mod.apply(note(tmp_path, r, "retry task 1", "retry task 99"), "agent")
    assert not out["ok"] and out["rolled_back"] and "task 99" in out["refused"]
    assert (r["run_dir"] / "state.json").read_bytes() == before


def test_step_not_built_yet_is_refused(tmp_path):
    r = make(tmp_path)
    out = apply_mod.apply(note(tmp_path, r, "rebuild the worktree"), "agent")
    assert out["rolled_back"] and "not supported yet" in out["refused"]


def test_dry_run_changes_nothing(tmp_path):
    r = make(tmp_path)
    f = note(tmp_path, r, "retry task 1", "mark task 3 skipped because no", "force")
    before = snapshot_of_files(r)
    out = apply_mod.apply(f, "agent", dry_run=True)
    assert out["dry_run"] and out["ok"] and len(out["steps"]) == 2 and out["forced"]
    assert snapshot_of_files(r) == before
    assert not (r["run_dir"] / "repairs").exists()
    assert "Dry run" in f.read_text() and "## Result" in f.read_text()


def test_four_records_written(tmp_path):
    r = make(tmp_path)
    (paths.projects() / r["project"]).mkdir()
    out = apply_mod.apply(note(tmp_path, r, "mark task 1 done because fine"), "alex")
    copy = r["run_dir"] / "repairs" / "notes" / "1-fix-the-thing.md"
    assert copy.is_file() and out["snapshot"] == 1 and (r["run_dir"] / "repairs/1/before").is_dir()
    events = [json.loads(l) for l in (r["run_dir"] / "events.jsonl").read_text().splitlines()]
    ev = next(e for e in events if e["type"] == "repair.applied")["data"]
    assert ev["who"] == "alex" and ev["note"] == copy.name and ev["steps"] == ["mark task 1 done because fine"]
    assert ev["snapshot"] == 1 and ev["rolled_back"] is False and ev["forced"] is False
    assert ev["check_before"] == ev["check_after"] and ev["title"] == "Fix the thing"
    cmds = (paths.logs() / "commands.jsonl").read_text()
    assert '"who": "alex"' in cmds
    assert "Fix the thing" in (paths.projects() / r["project"] / "notes" / "changelog.md").read_text()
    for text in (copy.read_text(), (tmp_path / "note.md").read_text()):
        assert "## Result" in text and "Snapshot: 1" in text and "Step 1:" in text and "Check after" in text


def test_refused_on_walked_run(tmp_path):
    r = make(tmp_path, status="running")
    heartbeat.write(time.time())
    before = snapshot_of_files(r)
    with pytest.raises(snapshot.RepairRefused, match="Stop it first or wait for a question"):
        apply_mod.apply(note(tmp_path, r, "retry task 1"), "agent")
    assert snapshot_of_files(r) == before


def test_unknown_run_refused(tmp_path):
    r = make(tmp_path)
    f = note(tmp_path, r, "retry task 1")
    f.write_text(f.read_text().replace(r["run"], "no-such-run"))
    with pytest.raises(snapshot.RepairRefused, match="no run"):
        apply_mod.apply(f, "agent")


def test_stale_running_run_dry_matches_real(tmp_path):
    r = make(tmp_path, status="running")
    heartbeat.write(time.time() - 10_000)
    f = note(tmp_path, r, "add a note to task 3: hi")
    dry = apply_mod.apply(f, "agent", dry_run=True)
    real = apply_mod.apply(f, "agent")
    assert dry["check_before"] == real["check_before"]
    assert dry["check_after"] == real["check_after"]
    assert dry["ok"] == real["ok"]
    assert not any("Another run" in p for p in dry["check_after"])


def test_cli_apply(tmp_path, capsys):
    r = make(tmp_path)
    f = note(tmp_path, r, "retry task 1", "force")
    assert cli_main.main(["repair", "apply", str(f)]) == 1                  # needs --yes or --dry-run
    assert cli_main.main(["repair", "apply", str(f), "--dry-run", "--json"]) == 0
    assert task(r, 1)["status"] == "failed"
    assert cli_main.main(["repair", "apply", str(f), "--yes", "--who", "agent"]) == 0
    assert task(r, 1)["status"] == "pending"
    assert cli_main.main(["repair", "apply", str(tmp_path / "nope.md"), "--yes"]) == 1


def test_apply_files_in_safety_list():
    text = open("deploy/self-project.toml").read()
    assert '"phoenix9/repair/*.py"' in text and "repairs can change run state and unlock checks" in text
