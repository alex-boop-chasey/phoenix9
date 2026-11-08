"""Tests for the worktree repair steps (redo, keep hand fix, reset, rebuild), with real git and undo for each."""
import shutil

import pytest
from helpers.repair_runs import make_run, sh

from phoenix9 import state
from phoenix9.repair import apply, notes, snapshot, steps


def setup_run(tmp_path):
    """A failed run with two commits for task 1 and 2, task 2 failed, and attempt folders for both."""
    r = make_run(tmp_path)
    work, rd = r["work"], r["run_dir"]
    base1 = sh(work, "rev-parse", "HEAD").strip()
    (work / "one.txt").write_text("one\n")
    sh(work, "add", "-A")
    sh(work, "commit", "-qm", "task 1")
    base2 = sh(work, "rev-parse", "HEAD").strip()
    (work / "two.txt").write_text("two\n")
    sh(work, "add", "-A")
    sh(work, "commit", "-qm", "task 2")

    def change(s):
        s["tasks"] = {"1": dict(state.new_task("One"), status="passed", tries=1, attempt_base=base1),
                      "2": dict(state.new_task("Two"), status="failed", tries=2, attempt_base=base2,
                                failures=["bad"], flagged="x")}
        s["steps"] = [{"task": 1, "step": "build", "status": "passed"}, {"task": 2, "step": "build", "status": "failed"}]
        s["current"] = {"group": None, "task": 2, "step": None, "attempt": None, "gate": None}
    state.update(rd, change)
    for k in (1, 2):
        (rd / f"tasks/2/attempt-{k}").mkdir(parents=True, exist_ok=True)
        (rd / f"tasks/2/attempt-{k}/result.json").write_text('{"passed": false}')
    r.update(base1=base1, base2=base2)
    return r


def write_note(tmp_path, r, *step_lines):
    """Write a repair note for the run with these steps, forced so the check does not decide."""
    path = tmp_path / "note.md"
    body = "\n".join(f"- {s}" for s in step_lines)
    path.write_text(f"# Repair {r['run']}\n\nWhy: test\n\n## Steps\n\n{body}\n- force\n")
    return path


def do_apply(tmp_path, r, *step_lines):
    """Apply a note with these steps."""
    return apply.apply(write_note(tmp_path, r, *step_lines), "test")


def head(r):
    return sh(r["work"], "rev-parse", "HEAD").strip()


def test_redo_resets_tasks_worktree_and_attempts(tmp_path):
    r = setup_run(tmp_path)
    info = do_apply(tmp_path, r, "redo task 2 from scratch")
    assert not info["rolled_back"], info
    st = state.load(r["run_dir"])
    t2 = st["tasks"]["2"]
    assert (t2["status"], t2["tries"], t2["failures"], t2["flagged"]) == ("pending", 0, [], "")
    assert t2["attempt_base"] == r["base2"]
    assert st["tasks"]["1"]["status"] == "passed"
    assert [x["task"] for x in st["steps"]] == [1]
    assert head(r) == r["base2"] and not (r["work"] / "two.txt").exists()
    assert not list((r["run_dir"] / "tasks/2").glob("attempt-*"))
    assert (r["run_dir"] / "repairs/1/removed/tasks/2/attempt-1/result.json").is_file()
    snapshot.undo(r["run_dir"])
    assert state.load(r["run_dir"])["tasks"]["2"]["status"] == "failed"
    assert (r["run_dir"] / "tasks/2/attempt-2/result.json").is_file()
    assert (r["work"] / "two.txt").read_text() == "two\n"


def test_redo_from_first_task_clears_later_tasks(tmp_path):
    r = setup_run(tmp_path)
    do_apply(tmp_path, r, "redo task 1 from scratch")
    tasks = state.load(r["run_dir"])["tasks"]
    assert {t["status"] for t in tasks.values()} == {"pending"}
    assert tasks["2"]["attempt_base"] is None
    assert head(r) == r["base1"]


def test_keep_hand_fix_commits_and_moves_env(tmp_path):
    r = setup_run(tmp_path)
    work = r["work"]
    (work / "two.txt").write_text("fixed by hand\n")
    (work / ".env").write_text("SECRET_THING=" + "x" * 8 + "\n")
    before = head(r)
    info = do_apply(tmp_path, r, 'keep my hand fix with message "Fix two by hand"')
    assert not info["rolled_back"], info
    assert head(r) != before
    log = sh(work, "log", "-1", "--format=%B")
    assert "Fix two by hand" in log and "Phoenix-Task: 2" in log
    assert not (work / ".env").exists()
    assert (r["run_dir"] / "tasks/2/outside-env/.env").is_file()
    assert state.load(r["run_dir"])["tasks"]["2"]["attempt_base"] == head(r)
    assert not sh(work, "status", "--porcelain").strip()
    snapshot.undo(r["run_dir"])
    assert head(r) == before
    assert (work / "two.txt").read_text() == "fixed by hand\n"
    assert state.load(r["run_dir"])["tasks"]["2"]["attempt_base"] == r["base2"]


def test_keep_hand_fix_refuses_a_secret(tmp_path):
    r = setup_run(tmp_path)
    (r["work"] / "key.txt").write_text("-----BEGIN " + "OPENSSH PRIVATE" + " KEY-----\nabc\n")
    with pytest.raises(snapshot.RepairRefused):
        do_apply(tmp_path, r, 'keep my hand fix with message "oops"')


def test_reset_worktree_names_lost_tasks_and_undo(tmp_path):
    r = setup_run(tmp_path)
    before = head(r)
    info = do_apply(tmp_path, r, f"reset the worktree to {r['base1']}")
    assert head(r) == r["base1"]
    assert "task 2 no longer has its start commit" in info["steps"][0]
    assert any("starts from commit" in p for p in info["check_after"])
    snapshot.undo(r["run_dir"])
    assert head(r) == before


def test_reset_worktree_refuses_foreign_commit(tmp_path):
    r = setup_run(tmp_path)
    sh(r["code"], "checkout", "-q", "-b", "side")
    (r["code"] / "side.txt").write_text("x\n")
    sh(r["code"], "add", "-A")
    sh(r["code"], "commit", "-qm", "side")
    stray = sh(r["code"], "rev-parse", "HEAD").strip()
    sh(r["code"], "checkout", "-q", "main")
    info = do_apply(tmp_path, r, f"reset the worktree to {stray}")
    assert info["rolled_back"] and "not a commit on" in info["refused"]
    assert head(r) != stray


def test_rebuild_drops_untracked_keeps_env_and_undo(tmp_path):
    r = setup_run(tmp_path)
    work = r["work"]
    (work / "junk.txt").write_text("junk\n")
    (work / "two.txt").write_text("dirty\n")
    (work / ".env").write_text("A=1\n")
    info = do_apply(tmp_path, r, "rebuild the worktree")
    assert not info["rolled_back"], info
    assert not (work / "junk.txt").exists() and (work / "two.txt").read_text() == "two\n"
    assert sh(work, "rev-parse", "--abbrev-ref", "HEAD").strip() == "phoenix/" + r["run"]
    assert "outside-env" in info["steps"][0]
    assert (r["run_dir"] / "tasks/2/outside-env/.env").read_text() == "A=1\n"
    snapshot.undo(r["run_dir"])
    assert (work / "junk.txt").read_text() == "junk\n" and (work / "two.txt").read_text() == "dirty\n"


def test_rebuild_after_worktree_folder_deleted(tmp_path):
    r = setup_run(tmp_path)
    tip = head(r)
    shutil.rmtree(r["work"])
    info = do_apply(tmp_path, r, "rebuild the worktree")
    assert not info["rolled_back"], info
    assert head(r) == tip
    assert sh(r["work"], "rev-parse", "--abbrev-ref", "HEAD").strip() == "phoenix/" + r["run"]
    snapshot.undo(r["run_dir"])
    assert head(r) == tip


def test_rebuild_after_git_file_corrupted(tmp_path):
    r = setup_run(tmp_path)
    tip = head(r)
    (r["work"] / ".git").write_text("gitdir: /nowhere/at/all\n")
    info = do_apply(tmp_path, r, "rebuild the worktree")
    assert not info["rolled_back"], info
    assert head(r) == tip and not [p for p in info["check_after"] if "worktree" in p.lower()]
    snapshot.undo(r["run_dir"])
    assert head(r) == tip


def test_dry_run_changes_nothing(tmp_path):
    r = setup_run(tmp_path)
    before = head(r)
    info = apply.apply(write_note(tmp_path, r, "redo task 2 from scratch", "rebuild the worktree"), "test", dry_run=True)
    assert info["dry_run"] and head(r) == before
    assert state.load(r["run_dir"])["tasks"]["2"]["status"] == "failed"


def test_steps_refuse_missing_worktree_and_base(tmp_path):
    r = setup_run(tmp_path)
    ctx = steps.Context(r["run_dir"])
    state.update(r["run_dir"], lambda s: s["tasks"]["2"].update(attempt_base=None))
    with pytest.raises(steps.StepRefused):
        steps.redo(ctx, 2)
    shutil.rmtree(r["work"])
    with pytest.raises(steps.StepRefused):
        steps.keep_hand_fix(ctx, "x")
    assert notes.parse(write_note(tmp_path, r, "rebuild the worktree").read_text()).steps[0].kind == "rebuild-worktree"
