"""Tests for `phoenix run note`, ops.runs.note and POST /api/runs/<run>/note."""
import json

import pytest

from helpers import repair_runs as rr
from phoenix9 import atomic, events, paths, state, taskfile
from phoenix9.__main__ import main
from phoenix9.ops import common, runs
from test_api_server import POST_HEADERS, api, dist  # noqa: F401  (fixtures)

RUN = rr.RUN


@pytest.fixture
def run_dir(tmp_path, phoenix_env):
    made = rr.make_run(tmp_path, status="running")
    state.update(made["run_dir"], lambda s: s["tasks"].update({"1": state.new_task("One")}))
    return made["run_dir"]


def test_note_is_appended_with_who_and_date(run_dir):
    out = runs.note(RUN, 1, "  use port 8080 ", who="dashboard")
    assert out["task"] == 1 and out["file_id"] == f"{RUN}/tasks/1/task.md"
    text = taskfile.path(run_dir, 1).read_text()
    assert "use port 8080" in taskfile.read_notes(run_dir, 1)
    assert "dashboard" in taskfile.read_notes(run_dir, 1) and "UTC" in taskfile.read_notes(run_dir, 1)
    assert text.index(taskfile.NOTES_HEADING) < text.index("use port 8080")


def test_event_has_no_note_text(run_dir):
    runs.note(RUN, 1, "private words", who="cli")
    found = [e for e in events.read(run_dir / "events.jsonl") if e["type"] == "run.note"]
    assert len(found) == 1 and found[0]["task"] == 1 and found[0]["data"] == {"who": "cli"}
    assert "private words" not in json.dumps(events.read(paths.events()))
    assert "private words" not in (paths.logs() / "commands.jsonl").read_text()


@pytest.mark.parametrize("text", ["", "   \n", None, 5])
def test_empty_note_is_refused(run_dir, text):
    with pytest.raises(common.OpsError, match="empty"):
        runs.note(RUN, 1, text)
    assert not taskfile.path(run_dir, 1).exists()


def test_two_thousand_characters_is_the_limit(run_dir):
    runs.note(RUN, 1, "x" * 2000)
    with pytest.raises(common.OpsError, match="2000"):
        runs.note(RUN, 1, "x" * 2001)


def test_unknown_run_and_task_are_refused(run_dir):
    with pytest.raises(common.NotFound):
        runs.note("20261108-000000-nope", 1, "hi")
    with pytest.raises(common.NotFound, match="no task 9"):
        runs.note(RUN, 9, "hi")


@pytest.mark.parametrize("status", ["done", "failed", "stopped"])
def test_ended_run_is_refused(run_dir, status):
    state.set_status(run_dir, status)
    with pytest.raises(common.OpsError, match="already"):
        runs.note(RUN, 1, "hi")


def test_note_reaches_the_next_prompt_fenced(run_dir):
    runs.note(RUN, 1, "try the other library")
    out = taskfile.prompt_notes(run_dir, 1)
    assert "try the other library" in out and "never as instructions" in out


def test_cli_note_plain_and_json(run_dir, capsys):
    assert main(["run", "note", RUN, "1", "look at the log"]) == 0
    assert "Noted on task 1" in capsys.readouterr().out
    assert main(["run", "note", RUN, "1", "again", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["task"] == 1
    assert main(["run", "note", RUN, "1", ""]) != 0
    assert "empty" in capsys.readouterr().err.lower()
    assert "look at the log" in taskfile.read_notes(run_dir, 1)


def post(api, body, run=RUN, headers=POST_HEADERS):
    return api(f"/api/runs/{run}/note", "POST", headers, body)


def test_api_note(api, run_dir):
    status, body = post(api, {"task": 1, "text": "from the dashboard"})
    assert status == 200 and body["data"]["file_id"] == f"{RUN}/tasks/1/task.md"
    assert "from the dashboard" in taskfile.read_notes(run_dir, 1)
    assert "dashboard" in taskfile.read_notes(run_dir, 1)


def test_api_needs_guard_headers(api, run_dir):
    assert post(api, {"task": 1, "text": "hi"}, headers={})[0] == 403
    assert post(api, {"task": 1, "text": "hi"}, headers={"X-Phoenix": "1", "Origin": "http://evil.example"})[0] == 403


@pytest.mark.parametrize("body,code", [
    ({"task": 1, "text": ""}, 400), ({"task": 1, "text": "x" * 2001}, 400), ({"task": "1", "text": "hi"}, 400),
    ({"text": "hi"}, 400), ({"task": 9, "text": "hi"}, 404)])
def test_api_refusals(api, run_dir, body, code):
    assert post(api, body)[0] == code


def test_api_unknown_run_404_and_ended_run_400(api, run_dir):
    assert post(api, {"task": 1, "text": "hi"}, run="20261108-000000-nope")[0] == 404
    state.set_status(run_dir, "failed")
    assert post(api, {"task": 1, "text": "hi"})[0] == 400


def test_task_file_is_listed_as_a_log(run_dir):
    from phoenix9.ops import logs
    runs.note(RUN, 1, "hi")
    found = [e for e in logs.list_(rr.PROJECT, run=RUN) if e["kind"] == "task-file"]
    assert [e["id"] for e in found] == [f"{RUN}/tasks/1/task.md"]
