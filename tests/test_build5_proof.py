"""Proof for build 5 against seeded fake data: bell counts, no dollars, masked search, the agent's reach, report settings."""
import json
import re

import pytest
from helpers.search_seed import SECRET, seed

from phoenix9 import agentaccess, bell, controlsgen, dailyreport, gates, settings, statusreport as sr
from phoenix9.ops import search as ops_search
from test_agentaccess import HEADERS, as_agent
from test_api_server import api, dist  # noqa: F401  (fixtures)
from test_status_report import NOW, _iso, make_project, make_run

MONEY = re.compile(r"\$|\bUSD\b|dollar", re.I)
NEW_TOOLS = {"search", "bell", "daily-report", "daily-report-now"}


@pytest.fixture
def seeded(monkeypatch, adapters):
    """One open question, two failed builds, one held merge request, a service down, low allowance, a saved report."""
    adapters.host.script(["systemctl", "is-active"], 0, "active\ninactive")
    adapters.agentnext.chunks = [json.dumps({"state": "low", "used_share": 0.85}).encode()]
    monkeypatch.setattr(sr, "_open_prs", lambda a: [{"project": "demo", "number": 4, "title": "Old",
                                                     "created": _iso(4 * 86400)}])
    make_project()
    gates.open_gate(make_run("live", "running"), kind="escalation", title="Which colour? It costs $9.99", why="w")
    make_run("bad1", "failed", ago_s=3600, flagged="over budget by $12.50 (USD 3)")
    make_run("bad2", "stopped", ago_s=7200, flagged="stopped")
    dailyreport._save("2026-11-10", "Phoenix daily report\nNothing else.")
    return adapters


def test_bell_count_equals_items_and_the_seed(seeded):
    found = bell.items(seeded, NOW)
    by_kind = {k: [i for i in found if i["kind"] == k] for k in ("question", "build", "merge", "service", "allowance", "report")}
    expected = {"question": 1, "build": 2, "merge": 1, "service": 1, "allowance": 1, "report": 1}
    assert {k: len(v) for k, v in by_kind.items()} == expected
    assert bell.count(found) == len(found) == sum(expected.values())


def test_report_and_telegram_text_have_no_dollar_amount(seeded):
    text = dailyreport.build(seeded, NOW)
    assert "12.50" not in text and "9.99" not in text and not MONEY.search(text)
    assert not MONEY.search(dailyreport.telegram_text(text))
    assert not MONEY.search(json.dumps(bell.items(seeded, NOW)))
    seeded.clock.t = NOW
    dailyreport._save("2026-11-11", text)
    dailyreport.send_if_due(seeded)
    assert all(not MONEY.search(m) for m in seeded.notify.messages)


def test_search_masks_a_secret_looking_string(adapters):
    seed()
    out = json.dumps(ops_search.run("quokka"))
    assert "quokka" in out and SECRET not in out
    assert SECRET not in json.dumps(ops_search.run(SECRET))


def test_agent_reaches_the_four_reads_and_nothing_new_that_changes(api):
    entries = {e["name"]: e for e in json.loads(controlsgen.PATH.read_text())}
    for name in NEW_TOOLS:
        assert entries[name]["agent"] == "tool" and entries[name]["risk"] == "read" and entries[name]["method"] == "GET"
        assert agentaccess.route_allowed("GET", entries[name]["route"])
    assert not entries["daily-report-now"]["route"].endswith("send")
    seed()
    as_agent(api)
    for path in ("/api/search?q=zebra", "/api/bell", "/api/report/daily", "/api/report/daily/now"):
        status, body = api(path, headers=HEADERS)
        assert status == 200 and body["ok"], path
        assert not MONEY.search(json.dumps(body)), path
    for path in ("/api/search", "/api/bell", "/api/report/daily", "/api/report/daily/now"):
        assert api(path, "POST", HEADERS, {})[0] in (403, 404, 405), path
    assert api("/api/global", "POST", HEADERS, {"report": {"time": "01:00"}})[0] in (403, 404, 405)
    changers = {e["name"] for e in entries.values() if e["agent"] == "tool" and e["risk"] != "read"}
    assert not changers & NEW_TOOLS


def test_report_settings_change_only_through_settings_and_not_safety(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOENIX_HOME", str(tmp_path))
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "global.toml").write_text('suggestions = "off"\n[delete]\nkeep_days = 9\n')
    before = (settings.suggestion_mode(), settings.delete_settings())
    assert settings.save_report_settings({"time": "07:15"})["time"] == "07:15"
    assert (settings.suggestion_mode(), settings.delete_settings()) == before
    for bad in ({"keep_days": 1}, {"steps": {}}, {"safety_files": []}):
        with pytest.raises(ValueError, match="not a report setting"):
            settings.save_report_settings(bad)
    assert settings.report_settings()["time"] == "07:15"
