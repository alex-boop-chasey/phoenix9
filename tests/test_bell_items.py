"""Tests for the bell items: each kind, the count, things going away, a failing source and the allowance states."""
import json
import time

import pytest

from phoenix9 import allowance, atomic, bell, gates, routes, statusreport as sr
from test_status_report import NOW, _iso, make_project, make_run


@pytest.fixture
def quiet(monkeypatch, adapters):
    """Services running, no merge requests, plenty of allowance: only what a test sets up shows."""
    adapters.host.script(["systemctl", "is-active"], 0, "active\nactive")
    adapters.agentnext.chunks = [json.dumps({"state": "plenty", "used_share": 0.1}).encode()]
    monkeypatch.setattr(sr, "_open_prs", lambda a: [])
    return adapters


def kinds(adapters):
    return [i["kind"] for i in bell.items(adapters, NOW)]


def test_nothing_needs_alex(quiet):
    assert bell.items(quiet, NOW) == [] and bell.count([]) == 0


def test_each_kind_appears_and_count_matches(quiet, monkeypatch):
    make_project()
    run = make_run("r1", "running")
    gates.open_gate(run, kind="escalation", title="Task 2 failed", why="because")
    make_run("r2", "failed", ago_s=3600, flagged="tests failed")
    monkeypatch.setattr(sr, "_open_prs", lambda a: [{"project": "demo", "number": 4, "title": "Old", "created": _iso(4 * 86400)}])
    quiet.host.script(["systemctl", "is-active"], 0, "active\ninactive")
    quiet.agentnext.chunks = [json.dumps({"state": "low", "used_share": 0.85}).encode()]
    found = bell.items(quiet, NOW)
    assert sorted(i["kind"] for i in found) == ["allowance", "build", "merge", "question", "service"]
    assert bell.count(found) == len(found) == 5
    ids = [i["id"] for i in found]
    assert len(set(ids)) == 5 and "service:phoenix:phoenix-runner" in ids and "build:demo:r2" in ids
    for i in found:
        assert set(i) == {"id", "kind", "title", "detail", "project", "page", "since"}
        routes.resolve(i["page"]["to"], i["page"]["params"])


def test_resolved_question_disappears(quiet):
    make_project()
    run = make_run("r1", "running")
    gates.open_gate(run, kind="escalation", title="Q", why="w")
    assert kinds(quiet) == ["question"]
    gates.close_questions(run, "answered elsewhere")
    assert "question" not in kinds(quiet)


def test_old_or_redone_builds_do_not_show(quiet):
    make_project()
    make_run("old", "failed", ago_s=9 * 86400)
    make_run("stopped", "stopped", ago_s=3600)
    assert kinds(quiet) == ["build"]
    atomic.write_json(sr.runs.run_dir("demo", "stopped") / "state.json", {**atomic.read_json(sr.runs.run_dir("demo", "stopped") / "state.json"), "status": "done"})
    assert kinds(quiet) == []


def test_a_failing_source_is_skipped(quiet, monkeypatch):
    make_project()
    make_run("r2", "failed", ago_s=3600)
    monkeypatch.setattr(gates, "list_gates", lambda *a, **k: 1 / 0)
    assert kinds(quiet) == ["build"]


@pytest.mark.parametrize("state,share,shows", [("plenty", 0.1, False), ("low", 0.8, True), ("used_up", 1.0, True)])
def test_allowance_item_only_when_low_or_used_up(quiet, state, share, shows):
    quiet.agentnext.chunks = [json.dumps({"state": state, "used_share": share}).encode()]
    found = bell.items(quiet, NOW)
    assert [i["kind"] for i in found] == (["allowance"] if shows else [])
    if shows:
        assert found[0]["detail"] == allowance.words_for(state, share)


def test_unknown_allowance_is_not_an_item(quiet):
    quiet.agentnext.down = True
    assert kinds(quiet) == []


def test_no_money_and_no_secret(quiet):
    make_project()
    make_run("r2", "failed", ago_s=3600, flagged="spent $12.50 and 3 USD on token sk-ant-api03-abcdefghijklmnopqrstuvwxyz")
    text = json.dumps(bell.items(quiet, NOW))
    assert "$" not in text and "USD" not in text and "abcdefghijkl" not in text
    assert bell.strip_money("cost $1,200.5 or 7 dollars") == "cost an amount or an amount"
