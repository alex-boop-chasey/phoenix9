"""Tests for undoing a repair: exact restore, older snapshots, refusal while walking, undo of an undo, CLI."""
import json
import time

import pytest
from helpers.repair_runs import make_run, sh

from phoenix9 import __main__ as cli_main, heartbeat, paths, state
from phoenix9.repair import snapshot


def tree(run_dir, sub="tasks"):
    """Every file under a run sub-folder with its bytes."""
    base = run_dir / sub
    return {p.relative_to(run_dir).as_posix(): p.read_bytes() for p in sorted(base.rglob("*")) if p.is_file()}


def run_files(run_dir):
    """Run files a snapshot owns, with bytes."""
    out = {}
    for name in ("state.json", "settings.json", "plan.json", "things.json", "spec.json", "spec.md", "overrides.json"):
        out[name] = (run_dir / name).read_bytes() if (run_dir / name).exists() else None
    out.update(tree(run_dir, "gates"))
    out.update(tree(run_dir, "tasks"))
    return out


def worktree_facts(r):
    """HEAD and the dirty content of the worktree."""
    work = r["work"]
    return (sh(work, "rev-parse", "HEAD"), sh(work, "status", "--porcelain", "--untracked-files=all"),
            {p: (work / p).read_text() for p in ("README.md", "new.txt") if (work / p).exists()})


def change_everything(r):
    """Change run files, gates, attempts and the worktree (a commit plus dirty files)."""
    rd, work = r["run_dir"], r["work"]
    (rd / "state.json").write_text(json.dumps({"run_id": r["run"], "project": r["project"], "status": "failed",
                                               "tasks": {"1": {"status": "passed"}}}))
    (rd / "plan.json").unlink()
    (rd / "spec.md").write_text("# Changed\n")
    (rd / "gates/q-1.json").write_text("{}")
    (rd / "gates/q-2.json").write_text("{}")
    (rd / "tasks/1/attempt-1/result.json").write_text('{"passed": false}')
    (rd / "tasks/1/attempt-3").mkdir()
    (rd / "tasks/1/attempt-3/result.json").write_text("{}")
    (work / "README.md").write_text("committed change\n")
    sh(work, "commit", "-aqm", "later")
    (work / "README.md").write_text("dirty again\n")
    (work / "new.txt").write_text("fresh\n")


def dirty_start(r):
    """Give the worktree uncommitted changes before the first snapshot."""
    (r["work"] / "README.md").write_text("dirty before\n")
    (r["work"] / "new.txt").write_text("new before\n")


def test_round_trip(tmp_path):
    r = make_run(tmp_path)
    dirty_start(r)
    files, facts = run_files(r["run_dir"]), worktree_facts(r)
    snapshot.take(r["run_dir"], "fix")
    change_everything(r)
    out = snapshot.undo(r["run_dir"])
    assert out["restored"] == 1 and out["snapshot"] == 2
    assert run_files(r["run_dir"]) == files
    assert worktree_facts(r) == facts
    assert sh(r["work"], "rev-parse", "--abbrev-ref", "HEAD").strip() == "phoenix/" + r["run"]
    assert snapshot.label_of(r["run_dir"], 2) == "undo to 1"


def test_writes_event_log_and_changelog(tmp_path):
    r = make_run(tmp_path)
    (paths.projects() / r["project"]).mkdir()
    snapshot.take(r["run_dir"], "fix")
    snapshot.undo(r["run_dir"], who="alex")
    events = [json.loads(x) for x in (r["run_dir"] / "events.jsonl").read_text().splitlines()]
    applied = [e for e in events if e["type"] == "repair.applied"]
    assert len(applied) == 1
    assert applied[0]["data"]["who"] == "alex" and applied[0]["data"]["snapshot"] == 2
    assert applied[0]["data"]["rolled_back"] is False and applied[0]["data"]["forced"] is False
    assert "alex" in (paths.logs() / "commands.jsonl").read_text()
    assert "undid back to snapshot 1" in (paths.projects() / r["project"] / "notes/changelog.md").read_text()


def test_to_older_snapshot(tmp_path):
    r = make_run(tmp_path)
    first = run_files(r["run_dir"]), worktree_facts(r)
    snapshot.take(r["run_dir"], "one")
    (r["run_dir"] / "spec.md").write_text("# Two\n")
    (r["work"] / "new.txt").write_text("two\n")
    snapshot.take(r["run_dir"], "two")
    change_everything(r)
    snapshot.undo(r["run_dir"], to=1)
    assert (run_files(r["run_dir"]), worktree_facts(r)) == first


def test_default_is_newest(tmp_path):
    r = make_run(tmp_path)
    snapshot.take(r["run_dir"], "one")
    (r["run_dir"] / "spec.md").write_text("# Two\n")
    snapshot.take(r["run_dir"], "two")
    (r["run_dir"] / "spec.md").write_text("# Three\n")
    snapshot.undo(r["run_dir"])
    assert (r["run_dir"] / "spec.md").read_text() == "# Two\n"


def test_unknown_snapshot_and_none_refused(tmp_path):
    r = make_run(tmp_path)
    with pytest.raises(snapshot.RepairRefused):
        snapshot.undo(r["run_dir"])
    snapshot.take(r["run_dir"], "one")
    with pytest.raises(snapshot.RepairRefused):
        snapshot.undo(r["run_dir"], to=7)
    assert snapshot.next_number(r["run_dir"]) == 2


def test_refused_while_walking(tmp_path):
    r = make_run(tmp_path, status="running")
    snapshot.take(r["run_dir"], "one")
    (r["run_dir"] / "spec.md").write_text("# Changed\n")
    heartbeat.write(time.time())
    with pytest.raises(snapshot.RepairRefused) as e:
        snapshot.undo(r["run_dir"])
    assert "Stop it first or wait for a question" in str(e.value)
    assert (r["run_dir"] / "spec.md").read_text() == "# Changed\n"
    assert snapshot.next_number(r["run_dir"]) == 2


def test_refused_while_lock_busy(tmp_path):
    r = make_run(tmp_path)
    snapshot.take(r["run_dir"], "one")
    with state.Lock(r["run_dir"] / "run.lock"):
        with pytest.raises(snapshot.RepairRefused):
            snapshot.undo(r["run_dir"])


def test_stale_heartbeat_may_be_undone(tmp_path):
    r = make_run(tmp_path, status="running")
    snapshot.take(r["run_dir"], "one")
    (r["run_dir"] / "spec.md").write_text("# Changed\n")
    heartbeat.write(time.time() - heartbeat.STALE_S - 60)
    snapshot.undo(r["run_dir"])
    assert (r["run_dir"] / "spec.md").read_text() == "# Demo\n"


def test_undo_of_an_undo(tmp_path):
    r = make_run(tmp_path)
    dirty_start(r)
    snapshot.take(r["run_dir"], "fix")
    change_everything(r)
    changed = run_files(r["run_dir"]), worktree_facts(r)
    snapshot.undo(r["run_dir"], to=1)
    snapshot.undo(r["run_dir"])
    assert (run_files(r["run_dir"]), worktree_facts(r)) == changed


def test_removed_attempt_folder_round_trip(tmp_path):
    r = make_run(tmp_path)
    rd = r["run_dir"]
    before = tree(rd)
    n = snapshot.take(rd, "redo")
    snapshot.move_to_removed(rd, n, "tasks/1/attempt-2")
    gone = tree(rd)
    assert gone != before
    snapshot.undo(rd, to=n)
    assert tree(rd) == before
    snapshot.undo(rd)
    assert tree(rd) == gone


def test_new_attempt_folder_round_trip(tmp_path):
    r = make_run(tmp_path)
    rd = r["run_dir"]
    before = tree(rd)
    snapshot.take(rd, "fix")
    (rd / "tasks/1/attempt-3").mkdir()
    (rd / "tasks/1/attempt-3/log.txt").write_text("new log\n")
    (rd / "tasks/1/attempt-3/prompt.md").write_text("prompt\n")
    after = tree(rd)
    snapshot.undo(rd, to=1)
    assert tree(rd) == before
    snapshot.undo(rd)
    assert tree(rd) == after


def test_attempt_with_result_created_later_round_trip(tmp_path):
    r = make_run(tmp_path)
    rd = r["run_dir"]
    before = tree(rd)
    snapshot.take(rd, "fix")
    (rd / "tasks/1/attempt-3").mkdir()
    (rd / "tasks/1/attempt-3/log.txt").write_text("new log\n")
    (rd / "tasks/1/attempt-3/result.json").write_text("{}")
    after = tree(rd)
    snapshot.undo(rd, to=1)
    assert tree(rd) == before
    snapshot.undo(rd)
    assert tree(rd) == after


def test_cli_plain_and_json(tmp_path, capsys):
    r = make_run(tmp_path)
    snapshot.take(r["run_dir"], "fix")
    (r["run_dir"] / "spec.md").write_text("# Changed\n")
    assert cli_main.main(["repair", "undo", r["run"]]) == 1          # needs --yes
    assert (r["run_dir"] / "spec.md").read_text() == "# Changed\n"
    capsys.readouterr()
    assert cli_main.main(["repair", "undo", r["run"], "--yes"]) == 0
    assert "Undone" in capsys.readouterr().out
    assert (r["run_dir"] / "spec.md").read_text() == "# Demo\n"
    (r["run_dir"] / "spec.md").write_text("# Changed again\n")
    assert cli_main.main(["repair", "undo", r["run"], "--to", "1", "--yes", "--json", "--who", "agent",
                          "--project", r["project"]]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True and data["restored"] == 1 and data["snapshot"] == 3
    assert (r["run_dir"] / "spec.md").read_text() == "# Demo\n"


def test_cli_refusals(tmp_path, capsys):
    r = make_run(tmp_path, status="running")
    snapshot.take(r["run_dir"], "fix")
    heartbeat.write(time.time())
    assert cli_main.main(["repair", "undo", r["run"], "--yes"]) == 1
    assert "Stop it first" in capsys.readouterr().err
    assert cli_main.main(["repair", "undo", "no-such-run", "--yes", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
