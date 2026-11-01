"""Tests for run ids, creation, listing and lookup."""
import os
import stat
from datetime import datetime, timezone

from phoenix9 import events, paths, runs, state

SPEC = """# Spec: Add Login Page!

## Task 1: First
Goal: do it.
Done when:
- it works fine
"""


def write_spec(tmp_path, text=SPEC):
    p = tmp_path / "spec.md"
    p.write_text(text)
    return p


def test_id_format_and_slug():
    now = datetime(2026, 11, 1, 9, 8, 7, tzinfo=timezone.utc)
    assert runs.new_run_id("Add Login Page!", now) == "20261101-090807-add-login-page"
    long = runs.new_run_id("A" * 80 + " tail", now)
    assert len(long.split("-", 2)[2]) <= 30
    assert runs.new_run_id("!!!", now).endswith("-run")


def test_create_run_writes_files(tmp_path):
    d = runs.create_run("proj", write_spec(tmp_path))
    assert d.parent == paths.runs("proj")
    assert stat.S_IMODE(os.stat(d / "spec.md").st_mode) == 0o444
    assert (d / "spec.md").read_text() == SPEC
    s = state.load(d)
    assert s["status"] == "queued" and s["run_id"] == d.name and s["project"] == "proj"
    assert s["tasks"]["1"]["status"] == "pending"
    (e,) = events.read(d / "events.jsonl")
    assert e["type"] == "run.queued" and e["run"] == d.name
    assert runs.run_dir("proj", d.name) == d


def test_same_second_runs_do_not_clash(tmp_path):
    spec = write_spec(tmp_path)
    ids = {runs.create_run("proj", spec).name for _ in range(3)}
    assert len(ids) == 3


def test_list_order_and_find(tmp_path):
    spec = write_spec(tmp_path)
    a = runs.create_run("one", spec)
    b = runs.create_run("two", spec)
    state.update(a, lambda s: s.__setitem__("created", "2020-01-01T00:00:00+00:00"))
    listed = runs.list_runs()
    assert [r["run_id"] for r in listed] == [b.name, a.name]
    assert [r["run_id"] for r in runs.list_runs("one")] == [a.name]
    assert runs.find_run(b.name) == b
    assert runs.find_run("nope") is None
    assert runs.list_runs("missing") == []
