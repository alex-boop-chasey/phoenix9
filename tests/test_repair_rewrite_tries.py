"""Tests for a checks rewrite and the old tries: the lock kept in snapshots, old attempts set aside, undo and the check."""
import os

from test_repair_steps_rerun import checks_run, note, task_state

from phoenix9 import failmodes, state
from phoenix9.repair import apply as apply_mod, check, report, snapshot, steps


def tree(folder):
    """Every file under a folder with its bytes, by relative path."""
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def task_files(r):
    """The files of task 1 in the run folder (checks lock and attempt folders)."""
    return tree(r["run_dir"] / "tasks" / "1")


def rewrite(tmp_path, r, **kw):
    """Apply 'rewrite the checks of task 1' as Alex (forced: the fixture run is failed with a pending task after it)."""
    path = note(tmp_path, r, "rewrite the checks of task 1 because the bullet is impossible", "force")
    return apply_mod.apply(path, "cli", approve_unlock=True, **kw)


def test_rewrite_sets_old_tries_aside_and_check_finds_nothing(tmp_path):
    r = checks_run(tmp_path)
    out = rewrite(tmp_path, r)
    assert out["ok"] and not out["rolled_back"], out
    base = r["run_dir"] / "tasks" / "1"
    assert not list(base.glob("attempt-*")) and not (base / "checks.lock.json").exists()
    removed = r["run_dir"] / "repairs" / str(out["snapshot"]) / "removed" / "tasks" / "1"
    assert sorted(p.name for p in removed.iterdir()) == ["attempt-1", "attempt-2"]
    assert not [f for f in check.run_checks(r["run_dir"]) if f.code in ("tries-mismatch", "old-tries-left")]
    assert not failmodes.attempt_dir(r["run_dir"], 1, 1).exists()      # the next try writes attempt-1 fresh


def test_rewrite_result_says_older_tries_kept(tmp_path):
    r = checks_run(tmp_path)
    text = steps.rewrite_checks(steps.Context(r["run_dir"], approve_unlock=True), 1, "the bullet is impossible")
    assert "older tries kept with the repair" in text


def test_rewrite_then_undo_restores_lock_and_attempts_exactly(tmp_path):
    r = checks_run(tmp_path)
    before = task_files(r)
    assert "checks.lock.json" in before and "attempt-2/log.txt" in before
    rewrite(tmp_path, r)
    snapshot.undo(r["run_dir"], to=1)
    assert task_files(r) == before
    assert task_state(r)["tries"] == 3
    assert not [f for f in check.run_checks(r["run_dir"]) if f.code == "tries-mismatch"]


def test_undo_sets_a_fresh_attempt_aside_and_brings_the_old_one_back(tmp_path):
    r = checks_run(tmp_path)
    before = task_files(r)
    rewrite(tmp_path, r)
    fresh = failmodes.attempt_dir(r["run_dir"], 1, 1)
    fresh.mkdir(parents=True)
    (fresh / "result.json").write_text('{"attempt": 1, "status": "failed"}\n')
    out = snapshot.undo(r["run_dir"], to=1)
    assert task_files(r) == before
    aside = r["run_dir"] / "repairs" / str(out["snapshot"]) / "removed" / "tasks" / "1" / "attempt-1" / "result.json"
    assert aside.read_text() == '{"attempt": 1, "status": "failed"}\n'


def test_dry_run_changes_nothing(tmp_path):
    r = checks_run(tmp_path)
    before, st = task_files(r), state.load(r["run_dir"])
    out = rewrite(tmp_path, r, dry_run=True)
    assert out["dry_run"]
    assert task_files(r) == before and state.load(r["run_dir"]) == st and r["file"].exists()
    assert not (r["run_dir"] / "repairs").exists() or not list((r["run_dir"] / "repairs").glob("*/removed"))


def old_run(tmp_path):
    """A run from before the fix: checks rewritten (lock gone, tries 0, objection) but attempts 1 and 2 left in place."""
    r = checks_run(tmp_path)
    (r["run_dir"] / "tasks" / "1" / "checks.lock.json").unlink()
    state.update(r["run_dir"], lambda s: s["tasks"]["1"].update(status="pending", tries=0, check_objection="bad"))
    return r


def test_old_run_shape_gets_the_plain_finding(tmp_path):
    r = old_run(tmp_path)
    found = [f for f in check.run_checks(r["run_dir"]) if f.fix.get("kind") in ("tries", "set-aside-old-tries")]
    assert [(f.code, f.text, f.fix) for f in found] == [
        ("old-tries-left", "Task 1's checks were rewritten; its old tries are still in place.",
         {"kind": "set-aside-old-tries", "task": 1})]
    assert "- set aside the old tries of task 1" in report.build(r["run_dir"])


def test_old_run_fix_clears_the_finding_and_undo_brings_tries_back(tmp_path):
    r = old_run(tmp_path)
    before = task_files(r)
    out = apply_mod.apply(note(tmp_path, r, "set aside the old tries of task 1"), "cli")
    assert out["ok"] and not out["rolled_back"], out
    assert not [f for f in check.run_checks(r["run_dir"]) if f.code in ("tries-mismatch", "old-tries-left")]
    assert not list((r["run_dir"] / "tasks" / "1").glob("attempt-*"))
    snapshot.undo(r["run_dir"], to=out["snapshot"])
    assert task_files(r) == before


def test_old_run_fix_dry_run_changes_nothing(tmp_path):
    r = old_run(tmp_path)
    before = task_files(r)
    out = apply_mod.apply(note(tmp_path, r, "set aside the old tries of task 1"), "cli", dry_run=True)
    assert out["ok"] and task_files(r) == before


def test_set_aside_refused_when_tries_are_not_left_from_a_rewrite(tmp_path):
    r = checks_run(tmp_path)
    out = apply_mod.apply(note(tmp_path, r, "set aside the old tries of task 1"), "cli")
    assert out["rolled_back"]
    assert sorted(p.name for p in (r["run_dir"] / "tasks" / "1").glob("attempt-*")) == ["attempt-1", "attempt-2"]


def test_tries_zero_with_folders_but_no_rewrite_keeps_the_old_finding(tmp_path):
    r = checks_run(tmp_path)
    (r["run_dir"] / "tasks" / "1" / "checks.lock.json").unlink()
    state.update(r["run_dir"], lambda s: s["tasks"]["1"].update(tries=0))
    assert [f.code for f in check.run_checks(r["run_dir"]) if f.task == 1] == ["tries-mismatch"]


def test_snapshot_keeps_the_lock_and_undo_removes_a_later_one(tmp_path):
    r = checks_run(tmp_path)
    lock = r["run_dir"] / "tasks" / "1" / "checks.lock.json"
    kept = lock.read_bytes()
    n = snapshot.take(r["run_dir"], "test")
    assert (r["run_dir"] / "repairs" / str(n) / "before" / "tasks" / "1" / "checks.lock.json").read_bytes() == kept
    lock.write_text("{}\n")
    later = r["run_dir"] / "tasks" / "2" / "checks.lock.json"
    later.parent.mkdir(parents=True)
    later.write_text("{}\n")
    snapshot.undo(r["run_dir"], to=n)
    assert lock.read_bytes() == kept and not later.exists()


def test_snapshot_does_not_follow_a_symlinked_lock(tmp_path):
    r = checks_run(tmp_path)
    lock = r["run_dir"] / "tasks" / "1" / "checks.lock.json"
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n")
    lock.unlink()
    os.symlink(outside, lock)
    n = snapshot.take(r["run_dir"], "test")
    assert not (r["run_dir"] / "repairs" / str(n) / "before" / "tasks" / "1" / "checks.lock.json").exists()
    snapshot.undo(r["run_dir"], to=n)
    assert lock.is_symlink() and outside.read_text() == "{}\n"
