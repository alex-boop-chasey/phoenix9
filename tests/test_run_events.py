"""Tests that one run's events can be read on their own: ops, API route, CLI and registry entry."""
import json

from phoenix9 import events, keys
from phoenix9.__main__ import main
from phoenix9.ops import controls, runs
from tests.helpers import repair_runs as rr

SECRET = "fake-secret-value-12345"


def _seed(tmp_path, count=5):
    """A run with `count` events, plus one event of another run in the global log."""
    rr.make_run(tmp_path)
    for n in range(count):
        events.emit("run.note", project=rr.PROJECT, run=rr.RUN, task=n)
    events.emit("run.note", project=rr.PROJECT, run="other-run", task=99)


def test_only_this_runs_events_oldest_first(phoenix_env, tmp_path):
    _seed(tmp_path)
    got = runs.events(rr.PROJECT, rr.RUN, limit=100)
    assert all(e["run"] == rr.RUN for e in got["events"])
    notes = [e["task"] for e in got["events"] if e["type"] == "run.note"]
    assert notes == [0, 1, 2, 3, 4]
    ids = [e["id"] for e in got["events"]]
    assert ids == sorted(ids)


def test_after_and_limit(phoenix_env, tmp_path):
    _seed(tmp_path)
    everything = runs.events(rr.PROJECT, rr.RUN)["events"]
    first = runs.events(rr.PROJECT, rr.RUN, limit=2)
    assert first["events"] == everything[:2]
    rest = runs.events(rr.PROJECT, rr.RUN, after=first["next"])
    assert rest["events"] == everything[2:]


def test_events_are_scrubbed(phoenix_env, tmp_path):
    rr.make_run(tmp_path)
    keys.set_key(rr.PROJECT, "TOKEN", SECRET, secret=True)
    path = runs._run_folder(rr.RUN) / "events.jsonl"
    path.write_text(json.dumps({"ts": "t", "type": "run.note", "run": rr.RUN, "data": {"x": SECRET}}) + "\n")
    assert SECRET not in json.dumps(runs.events(rr.PROJECT, rr.RUN))


def test_unknown_run_is_not_found(phoenix_env, tmp_path):
    rr.make_run(tmp_path)
    try:
        runs.events(rr.PROJECT, "nope")
    except Exception as err:
        assert "no run" in str(err).lower()
    else:
        raise AssertionError("expected an error")


def test_cli_prints_plain_and_json(phoenix_env, tmp_path, capsys):
    _seed(tmp_path, 2)
    assert main(["run", "events", rr.PROJECT, rr.RUN]) == 0
    assert "run.note" in capsys.readouterr().out
    assert main(["run", "events", rr.PROJECT, rr.RUN, "--json", "--limit", "1"]) == 0
    assert len(json.loads(capsys.readouterr().out)["events"]) == 1


def test_registry_entry():
    c = {c.name: c for c in controls.CONTROLS}["run-events"]
    assert (c.risk, c.agent, c.card, c.ops) == ("read", "tool", "events_card", "runs.events")
