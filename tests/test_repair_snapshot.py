"""Tests for repair snapshots: copies, numbering, worktree facts, secrets kept out, moving to removed."""
import json
import os

import pytest
from helpers.repair_runs import make_run, sh

from phoenix9.repair import snapshot


def fake_key() -> str:
    """A made-up live-looking key, built here so no key shape sits in the source."""
    return "sk_" + "live_" + "A1b2C3d4" * 3


def test_copies_and_label(tmp_path):
    r = make_run(tmp_path)
    n = snapshot.take(r["run_dir"], "before redo")
    before = r["run_dir"] / "repairs" / str(n) / "before"
    assert n == 1
    for name in ("state.json", "settings.json", "plan.json", "things.json", "spec.json", "spec.md",
                 "overrides.json", "gates/q-1.json", "tasks/1/attempt-1/result.json",
                 "tasks/1/attempt-2/result.json"):
        assert (before / name).read_bytes() == (r["run_dir"] / name).read_bytes()
    assert not (before / "tasks/1/attempt-1/log.txt").exists()
    assert (before / "label.txt").read_text().strip() == "before redo"


def test_numbering(tmp_path):
    r = make_run(tmp_path)
    assert [snapshot.take(r["run_dir"], x) for x in "abc"] == [1, 2, 3]
    assert not [p for p in (r["run_dir"] / "repairs").iterdir() if p.name.startswith(".")]


def test_worktree_clean_and_dirty(tmp_path):
    r = make_run(tmp_path)
    n = snapshot.take(r["run_dir"], "clean")
    info = json.loads((r["run_dir"] / "repairs/1/before/worktree.json").read_text())
    assert info == {"head": sh(r["work"], "rev-parse", "HEAD").strip(), "branch": "phoenix/" + r["run"],
                    "dirty": False}
    assert (r["run_dir"] / "repairs/1/before/worktree.patch").read_text() == ""
    (r["work"] / "README.md").write_text("changed\n")
    (r["work"] / "new.txt").write_text("brand new\n")
    n = snapshot.take(r["run_dir"], "dirty")
    before = r["run_dir"] / "repairs" / str(n) / "before"
    assert json.loads((before / "worktree.json").read_text())["dirty"] is True
    patch = (before / "worktree.patch").read_text()
    assert "+changed" in patch and "+brand new" in patch


def test_env_file_and_secret_never_in_snapshot(tmp_path):
    r = make_run(tmp_path)
    (r["work"] / ".env").write_text("API_TOKEN=supersecretvalue123\n")
    (r["run_dir"] / "secrets").mkdir()
    (r["run_dir"] / "secrets" / "k.txt").write_text("hidden-secret-value\n")
    (r["work"] / "ok.txt").write_text("fine\n")
    n = snapshot.take(r["run_dir"], "env")
    before = r["run_dir"] / "repairs" / str(n) / "before"
    assert "supersecretvalue123" not in (before / "worktree.patch").read_text()
    assert "ok.txt" in (before / "worktree.patch").read_text()
    assert not any(".env" in p.name or p.name == "k.txt" for p in before.rglob("*"))


def test_planted_secret_refuses_and_leaves_nothing(tmp_path):
    r = make_run(tmp_path)
    (r["work"] / "config.txt").write_text(f"key = {fake_key()}\n")
    with pytest.raises(snapshot.SnapshotError) as e:
        snapshot.take(r["run_dir"], "bad")
    assert fake_key() not in str(e.value)
    repairs = r["run_dir"] / "repairs"
    assert not repairs.exists() or not list(repairs.iterdir())


def test_missing_optional_files_tolerated(tmp_path):
    r = make_run(tmp_path)
    for name in ("plan.json", "things.json", "spec.json", "spec.md", "overrides.json"):
        (r["run_dir"] / name).unlink()
    import shutil
    shutil.rmtree(r["run_dir"] / "gates")
    shutil.rmtree(r["run_dir"] / "tasks")
    n = snapshot.take(r["run_dir"], "sparse")
    before = r["run_dir"] / "repairs" / str(n) / "before"
    assert (before / "state.json").exists() and not (before / "plan.json").exists()


def test_move_to_removed(tmp_path):
    r = make_run(tmp_path)
    n = snapshot.take(r["run_dir"], "redo")
    attempt = r["run_dir"] / "tasks/1/attempt-2"
    snapshot.move_to_removed(r["run_dir"], n, attempt)
    assert not attempt.exists()
    moved = r["run_dir"] / "repairs" / str(n) / "removed/tasks/1/attempt-2"
    assert (moved / "result.json").exists() and (moved / "log.txt").exists()
