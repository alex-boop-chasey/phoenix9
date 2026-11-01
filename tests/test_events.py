"""Tests for the event stream."""
import json

import pytest

from phoenix9 import events, paths


def test_emit_writes_both_files_in_format(phoenix_env):
    events.emit("task.started", project="p", run="r1", task=2, step="builder", why="x")
    for f in (paths.events(), paths.runs("p") / "r1" / "events.jsonl"):
        (line,) = f.read_text().splitlines()
        e = json.loads(line)
        assert list(e) == ["ts", "type", "project", "run", "task", "step", "data"]
        assert (e["type"], e["project"], e["run"], e["task"], e["step"]) == ("task.started", "p", "r1", 2, "builder")
        assert e["data"] == {"why": "x"}


def test_emit_without_run_only_global():
    events.emit("command", project="p", command="x")
    assert len(events.read(paths.events())) == 1
    assert not paths.runs().exists()


def test_unknown_type_refused():
    with pytest.raises(ValueError):
        events.emit("nope", project="p")
    assert not paths.events().exists()


def test_read_after_line_and_tail():
    for i in range(5):
        events.emit("command", project="p", i=i)
    assert [e["data"]["i"] for e in events.read(paths.events(), after_line=3)] == [3, 4]
    assert [e["data"]["i"] for e in events.tail(paths.events(), 2)] == [3, 4]
    assert events.read(paths.home() / "missing.jsonl") == []
