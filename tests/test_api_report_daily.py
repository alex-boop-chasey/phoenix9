"""Tests for the daily report as a route, command and control, and as the bell's report item."""
import json
import re

from phoenix9 import bell, controlsgen, dailyreport, paths
from phoenix9.__main__ import main
from phoenix9.ops import controls, report as ops_report
from test_api_server import api, dist  # noqa: F401  (fixtures)
from test_bell_items import quiet  # noqa: F401  (fixture)
from test_agentaccess import HEADERS, as_agent
from test_status_report import NOW

DOLLAR = re.compile(r"\$|\bUSD\b|dollar", re.I)


def save(date, text):
    dailyreport._save(date, text)


def test_latest_says_no_report_yet(api):
    status, body = api("/api/report/daily")
    assert status == 200 and body["data"]["text"] == "No report yet."


def test_latest_and_now_answer(api):
    save("2026-11-10", "Phoenix daily report\nNothing needs you.")
    data = api("/api/report/daily")[1]["data"]
    assert data["date"] == "2026-11-10" and "Nothing needs you." in data["text"]
    now = api("/api/report/daily/now")[1]["data"]
    assert now["text"].startswith("Phoenix daily report") and not DOLLAR.search(now["text"])


def test_agent_may_read_only(api):
    as_agent(api)
    assert api("/api/report/daily", headers=HEADERS)[0] == 200
    assert api("/api/report/daily", "POST", HEADERS, {})[0] in (403, 404, 405)


def test_now_sends_and_records_nothing(api):
    api("/api/report/daily/now")
    assert dailyreport.latest() is None
    assert not (paths.home() / "reports" / "daily-state.json").exists()
    assert not (paths.home() / "reports" / "daily").exists() or not list((paths.home() / "reports" / "daily").iterdir())


def test_cli_latest_and_now(phoenix_env, capsys):
    assert main(["report", "daily"]) == 0
    assert "No report yet." in capsys.readouterr().out
    save("2026-11-10", "Phoenix daily report\nNothing needs you.")
    assert main(["report", "daily", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["date"] == "2026-11-10"
    assert main(["report", "daily", "--now"]) == 0
    assert "Phoenix daily report" in capsys.readouterr().out
    assert dailyreport.latest()["date"] == "2026-11-10"


def test_latest_hides_money(phoenix_env):
    save("2026-11-10", "Spent $4.20 today")
    assert not DOLLAR.search(ops_report.daily_latest()["text"])


def test_bell_shows_newest_report_only(quiet):
    assert "report" not in [i["kind"] for i in bell.items(quiet, NOW)]
    save("2026-11-09", "Old report")
    save("2026-11-10", "New report")
    found = [i for i in bell.items(quiet, NOW) if i["kind"] == "report"]
    assert len(found) == 1 and found[0]["id"] == "report:phoenix:2026-11-10" and "New report" in found[0]["detail"]
    assert not DOLLAR.search(found[0]["detail"])


def test_registry_entries():
    by = {c.name: c for c in controls.CONTROLS}
    for name, op in (("daily-report", "report.daily_latest"), ("daily-report-now", "report.daily_now")):
        c = by[name]
        assert (c.risk, c.agent, c.card, c.ops) == ("read", "tool", "report_card", op)
        assert name in [e["name"] for e in controlsgen.describe()]
