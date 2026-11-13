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
    assert len(set(ids)) == 5 and f"service:phoenix:phoenix-runner:{_iso(0)}" in ids and "build:demo:r2" in ids
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


# ---- dismissing, dates and order ----

def ids_of(adapters, now=NOW):
    return [i["id"] for i in bell.items(adapters, now)]


def test_dismiss_hides_and_count_drops(quiet):
    make_project()
    make_run("r1", "failed", ago_s=3600)
    make_run("r2", "failed", ago_s=7200)
    found = bell.items(quiet, NOW)
    assert bell.count(found) == 2
    bell.dismiss("build:demo:r1")
    found = bell.items(quiet, NOW)
    assert [i["id"] for i in found] == ["build:demo:r2"] and bell.count(found) == 1
    assert list(bell.dismissed()) == [bell.fingerprint("build:demo:r1")]


def test_dismiss_all_and_unknown_ids(quiet):
    make_project()
    make_run("r1", "failed", ago_s=3600)
    bell.dismiss("no:such:item")
    bell.dismiss_all(ids_of(quiet))
    assert ids_of(quiet) == []


def test_a_new_event_shows_again(quiet):
    make_project()
    make_run("r1", "failed", ago_s=7200)
    bell.dismiss("build:demo:r1")
    make_run("r2", "failed", ago_s=3600)
    assert ids_of(quiet) == ["build:demo:r2"]


def test_service_down_again_later_is_a_new_item(quiet):
    quiet.host.script(["systemctl", "is-active"], 0, "active\ninactive")
    first = ids_of(quiet, NOW - 600)
    assert first == ids_of(quiet, NOW)  # still the same outage
    bell.dismiss(first[0])
    assert ids_of(quiet) == []
    quiet.host.script(["systemctl", "is-active"], 0, "active\nactive")
    assert ids_of(quiet) == []
    quiet.host.script(["systemctl", "is-active"], 0, "active\nfailed")
    again = ids_of(quiet, NOW + 60)
    assert len(again) == 1 and again != first


def test_allowance_new_state_or_new_time_is_a_new_item(quiet):
    quiet.agentnext.chunks = [json.dumps({"state": "low", "used_share": 0.85}).encode()]
    low = ids_of(quiet)
    bell.dismiss(low[0])
    quiet.agentnext.chunks = [json.dumps({"state": "used_up", "used_share": 1.0}).encode()]
    used = ids_of(quiet, NOW + 60)
    assert len(used) == 1 and used[0].startswith("allowance:phoenix:used_up:")


@pytest.mark.parametrize("odd", ["x" * 5000, "a:b+c/d e", "question:demo:r1.1 + more/than: that"], ids=["long", "marks", "spaces"])
def test_long_and_odd_ids_work(quiet, odd):
    bell.dismiss(odd)
    key = bell.fingerprint(odd)
    assert len(key) == 24 and key in bell.dismissed()
    assert json.loads((bell.store_path()).read_text())  # stored under the short name only
    assert odd not in bell.store_path().read_text()


def test_bad_ids_are_refused(quiet):
    for bad in ("", "  ", None, 3):
        with pytest.raises(ValueError):
            bell.dismiss(bad)


def test_stale_entries_are_pruned_and_file_written_only_on_change(quiet, monkeypatch):
    make_project()
    make_run("r1", "failed", ago_s=3600)
    bell.dismiss_all(["build:demo:r1", "gone:one", "gone:two"])
    bell.items(quiet, NOW)
    assert list(bell.dismissed()) == [bell.fingerprint("build:demo:r1")]
    writes = []
    real = atomic.write_json
    monkeypatch.setattr(atomic, "write_json", lambda path, data, *a, **k: (writes.append(path), real(path, data, *a, **k)))
    bell.items(quiet, NOW)
    assert bell.store_path() not in writes


def test_a_failing_source_keeps_its_dismissals(quiet, monkeypatch):
    make_project()
    run = make_run("r1", "running")
    gate = gates.open_gate(run, kind="escalation", title="Q", why="w")
    bell.dismiss(f"question:demo:{gate['id']}")
    monkeypatch.setattr(gates, "list_gates", lambda *a, **k: 1 / 0)
    bell.items(quiet, NOW)
    assert bell.fingerprint(f"question:demo:{gate['id']}") in bell.dismissed()


def test_every_source_has_since_and_newest_first(quiet, monkeypatch):
    from phoenix9 import dailyreport
    make_project()
    run = make_run("r1", "running")
    gates.open_gate(run, kind="escalation", title="Task 2 failed", why="because")
    make_run("r2", "failed", ago_s=3600)
    monkeypatch.setattr(sr, "_open_prs", lambda a: [{"project": "demo", "number": 4, "title": "Old", "created": _iso(4 * 86400)}])
    quiet.host.script(["systemctl", "is-active"], 0, "active\ninactive")
    quiet.agentnext.chunks = [json.dumps({"state": "low", "used_share": 0.85}).encode()]
    folder = dailyreport._dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "2026-01-01.md").write_text("All quiet.")
    found = bell.items(quiet, NOW)
    assert sorted(i["kind"] for i in found) == ["allowance", "build", "merge", "question", "report", "service"]
    stamps = [sr._epoch(i["since"]) for i in found]
    assert all(stamps), [i["since"] for i in found]
    assert stamps == sorted(stamps, reverse=True)
