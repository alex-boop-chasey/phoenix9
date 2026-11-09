"""Tests for suggestions: report ids, the store, the commands, the API handlers, the setting and the agent rule."""
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from phoenix9 import atomic, doctor, gates, paths, settings, statusreport, suggest, updater
from phoenix9.__main__ import main
from phoenix9.api import server

RULES = Path(__file__).resolve().parent.parent / "deploy" / "agent" / "agent-rules.md"


@pytest.fixture
def quiet(monkeypatch, adapters):
    """A calm server; tests add what they need."""
    monkeypatch.setattr(updater, "status", lambda a: {"update_available": False})
    monkeypatch.setattr(doctor, "run_checks", lambda a, mode="full": {"ok": True, "checks": []})
    monkeypatch.setattr(statusreport, "_open_prs", lambda a: [])
    from phoenix9.ops import common
    monkeypatch.setattr(common, "make_adapters", lambda: adapters)
    return adapters


def with_lines(monkeypatch, *lines):
    """Make the report hold exactly these (section, key) lines."""
    body = ""
    for section in dict.fromkeys(s for s, _ in lines):
        body += f"\n## {section}\n" + "".join(f"- text of {k} <!-- id: {k} -->\n" for s, k in lines if s == section)
    monkeypatch.setattr(statusreport, "build", lambda a, now=None: "# Phoenix status\n" + body)


def run_cmd(capsys, *argv):
    assert main([*argv, "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def test_report_lines_carry_ids(quiet, monkeypatch):
    monkeypatch.setattr(statusreport, "_open_prs", lambda a: [
        {"project": "demo", "number": 4, "title": "Old", "created": "2020-01-01T00:00:00+00:00"}])
    text = statusreport.build(quiet, time.time())
    assert "<!-- id: mr-old:demo:4 -->" in text
    assert [r["key"] for r in suggest.parse(text)] == ["mr-old:demo:4"]



def test_gate_key_includes_gate_id(quiet):
    run = paths.runs("demo") / "r1"
    run.mkdir(parents=True)
    from phoenix9 import state
    atomic.write_json(run / "state.json", state.new_state("r1", "demo", {"1": state.new_task("t")}))
    gates.open_gate(run, kind="escalation", title="Task 1 failed", why="x")
    gate = gates.list_gates()[0]
    assert f"<!-- id: escalation-waiting:demo:{gate['id']} -->" in statusreport.build(quiet, time.time())


def test_pick_orders_attention_first_and_caps_at_three(monkeypatch):
    with_lines(monkeypatch, ("Phoenix", "update-available:v9.9"), ("Builds", "build-running:a:r1"),
               ("Waiting for Alex", "merge-waiting:phoenix9:g1"), ("Builds", "build-failed:a:r2"), ("Phoenix", "disk-low"))
    # attention lines (a waiting question, a failed build, a full disk) come first, in report order
    text = statusreport.build(None)
    keys = [r["key"] for r in suggest.pick(text, {}, 0)]
    assert sorted(keys) == sorted(["merge-waiting:phoenix9:g1", "build-failed:a:r2", "disk-low"])


def test_store_dismiss_snooze_shown():
    now = 1000.0
    text = "## Phoenix\n- a <!-- id: k1 -->\n- b <!-- id: k2 -->\n- c <!-- id: k3 -->\n"
    suggest.mark("k1", "dismissed")
    suggest.mark("k2", "snoozed", hours=1, now=now)
    suggest.mark("k3", "shown", now=now)
    assert [r["key"] for r in suggest.pick(text, now=now + 10)] == ["k3"]
    assert suggest.pick(text, now=now + 10)[0]["shown"] is True
    assert [r["key"] for r in suggest.pick(text, now=now + 3700)] == ["k2", "k3"]
    data = atomic.read_json(suggest.store_path())
    assert set(data["k1"]) == {"shown", "snoozed_until", "dismissed"}
    assert suggest.store_path() == paths.home() / "cache" / "suggestions.json"


def test_bad_key_refused():
    with pytest.raises(ValueError):
        suggest.mark("bad key; rm", "shown")


def test_commands(quiet, monkeypatch, capsys):
    with_lines(monkeypatch, ("Phoenix", "k1"), ("Phoenix", "k2"))
    assert [r["key"] for r in run_cmd(capsys, "suggest", "list")["suggestions"]] == ["k1", "k2"]
    assert run_cmd(capsys, "suggest", "dismiss", "k1")["dismissed"] is True
    assert run_cmd(capsys, "suggest", "snooze", "k2", "--hours", "2")["snoozed_until"] > time.time()
    assert run_cmd(capsys, "suggest", "list")["suggestions"] == []
    assert run_cmd(capsys, "suggest", "shown", "k9")["shown"]
    assert main(["suggest", "list"]) == 0 and "Nothing to suggest" in capsys.readouterr().out
    assert main(["suggest", "shown", "no good!"]) == 1


def test_setting_modes(quiet, monkeypatch, capsys):
    with_lines(monkeypatch, ("Phoenix", "k1"))
    assert settings.suggestion_mode() == "on"
    conf = paths.config() / "global.toml"
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text('suggestions = "strip-only"\n')
    assert run_cmd(capsys, "suggest", "list")["suggestions"] == []
    assert len(run_cmd(capsys, "suggest", "list", "--strip")["suggestions"]) == 1
    conf.write_text('suggestions = "off"\n')
    assert run_cmd(capsys, "suggest", "list", "--strip")["suggestions"] == []
    conf.write_text('suggestions = "junk"\n')
    assert settings.suggestion_mode() == "on"


def test_api_handlers(quiet, monkeypatch):
    with_lines(monkeypatch, ("Phoenix", "k1"))
    lock = SimpleNamespace(write_lock=__import__("threading").RLock())
    req = lambda body=None: SimpleNamespace(server=lock, body=body or {}, query={})
    assert [r["key"] for r in server.get_suggest(req())["suggestions"]] == ["k1"]
    method, pattern, handler = next(r for r in server.COMPILED if r[1].match("/api/suggest/k1/snooze"))
    assert method == "POST"
    m = pattern.match("/api/suggest/k1/snooze")
    assert handler(req({"hours": 2}), **m.groupdict())["snoozed_until"] > time.time()
    assert server.get_suggest(req())["suggestions"] == []
    with pytest.raises(server.BadRequest):
        server.post_suggest(req({"hours": "x"}), "k1", "snoozed")
    assert any(r[1].match("/api/suggest/k1/dismiss") for r in server.COMPILED)
    assert any(r[1].match("/api/suggest/k1/shown") for r in server.COMPILED)


def test_agent_rule():
    text = RULES.read_text()
    section = text.split("## Suggestions", 1)[1].split("\n## ", 1)[0]
    for needle in ["new suggestions: <n>", "phoenix report status", "at most ONE", "choice or confirm block",
                   "phoenix suggest shown <key>", "Never repeat a key", "ask-first action as already done"]:
        assert needle in section, needle
