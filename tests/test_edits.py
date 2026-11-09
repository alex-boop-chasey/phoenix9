"""Tests for quick edits: start, refusals, list, heartbeat, abandon, events (real git in temp repos)."""
import json
import os
import subprocess
import time

import pytest

from phoenix9 import atomic, edits, events, paths, state
from phoenix9.__main__ import main


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True)


@pytest.fixture
def proj(phoenix_env):
    """A project with a one-commit code/ repo on main."""
    code = phoenix_env["projects"] / "demo" / "code"
    code.mkdir(parents=True)
    _git(code, "init", "-q", "-b", "main")
    (code / "a.txt").write_text("a\n")
    _git(code, "add", "-A")
    _git(code, "commit", "-q", "-m", "first")
    return code


def _branches(code):
    return subprocess.run(["git", "branch", "--list", "edit/*"], cwd=code, capture_output=True, text=True).stdout


def test_start_makes_worktree_and_record(proj, capsys):
    assert main(["edit", "start", "demo", "--title", "Fix the typo"]) == 0
    folder = capsys.readouterr().out.strip()
    rec = json.loads(next((paths.home() / "edits").glob("*.json")).read_text())
    assert folder == rec["folder"] == str(paths.home() / "edits" / rec["id"])
    assert (os.path.exists(os.path.join(folder, "a.txt")))
    assert rec["branch"] == "edit/" + rec["id"] and rec["id"].endswith("-fix-the-typo")
    assert rec["status"] == "open" and rec["project"] == "demo" and rec["who"] == "cli"
    assert rec["branch"] in _branches(proj)
    assert any(e["type"] == "edit.started" for e in events.read(paths.events()))


def test_refuses_second_open_edit_and_running_build(proj):
    edits.start("demo", "one")
    with pytest.raises(edits.EditError, match="open quick edit"):
        edits.start("demo", "two")


def test_refuses_while_build_runs(proj):
    run = paths.runs("demo") / "20260101-000000-x"
    run.mkdir(parents=True)
    atomic.write_json(run / "state.json", state.new_state(run.name, "demo"))
    state.set_status(run, "running")
    with pytest.raises(edits.EditError, match="build is running"):
        edits.start("demo", "one")
    state.set_status(run, "done")
    edits.start("demo", "one")


def test_list_heartbeat_and_file_activity(proj, capsys):
    rec = edits.start("demo", "one")
    old = "2020-01-01T00:00:00+00:00"
    atomic.write_json(edits.record_file(rec["id"]), dict(rec, last_activity=old))
    assert edits.list_edits("demo")[0]["last_activity"] > old       # worktree files are newer
    assert main(["edit", "heartbeat", rec["id"]]) == 0
    assert json.loads(edits.record_file(rec["id"]).read_text())["last_activity"] > old
    time.sleep(1.1)
    (open(os.path.join(rec["folder"], "b.txt"), "w")).write("b")
    assert edits.list_edits("demo")[0]["last_activity"] >= edits.load(rec["id"])["last_activity"]
    capsys.readouterr()
    assert main(["edit", "list", "--project", "demo", "--json"]) == 0
    assert [e["id"] for e in json.loads(capsys.readouterr().out)["edits"]] == [rec["id"]]
    assert main(["edit", "list", "--project", "other", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["edits"] == []
    assert main(["edit", "heartbeat", "nope"]) == 1


def test_abandon_needs_yes_and_removes_everything(proj):
    rec = edits.start("demo", "one")
    assert main(["edit", "abandon", rec["id"]]) == 1
    assert os.path.isdir(rec["folder"])
    assert main(["edit", "abandon", rec["id"], "--yes"]) == 0
    assert not os.path.exists(rec["folder"]) and rec["branch"] not in _branches(proj)
    assert edits.load(rec["id"])["status"] == "abandoned"
    assert "edit.abandoned" in [e["type"] for e in events.read(paths.events())]
    edits.start("demo", "again")       # the project is free again


def test_finish_event_and_unknown_project(proj, capsys):
    rec = edits.start("demo", "one")
    edits.finish(rec["id"])
    assert "edit.finished" in [e["type"] for e in events.read(paths.events())]
    edits.start("demo", "next")        # a finished edit no longer blocks
    assert main(["edit", "start", "nope", "--title", "x"]) == 1
