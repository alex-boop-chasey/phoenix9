"""Tests for the daily report text: sections, quiet day, money removed, secrets masked, Telegram length."""
import json
import re

import pytest

from phoenix9 import dailyreport, gates, statusreport as sr
from test_status_report import NOW, make_project, make_run

DOLLAR = re.compile(r"\$\s?\d|\d\s?(?:USD|dollars?)\b|\bUSD\s?\d", re.I)
TOKEN = "sk-ant-api03-" + "A1b2C3d4E5f6G7h8I9j0" * 2


@pytest.fixture
def quiet(monkeypatch, adapters):
    """Services running, no merge requests, plenty of allowance."""
    adapters.host.script(["systemctl", "is-active"], 0, "active\nactive")
    adapters.agentnext.chunks = [json.dumps({"state": "plenty", "used_share": 0.1}).encode()]
    monkeypatch.setattr(sr, "_open_prs", lambda a: [])
    return adapters


def test_quiet_day(quiet):
    text = dailyreport.build(quiet, NOW)
    assert "Nothing needs you." in text and "Finished" not in text and "Failed" not in text
    assert "plenty left this month" in text


def test_seeded_day_has_sections(quiet):
    make_project()
    make_run("ok1", "done", ago_s=3600)
    make_run("bad1", "failed", ago_s=7200, flagged="tests failed")
    make_run("old1", "done", ago_s=3 * 86400)
    gates.open_gate(make_run("live", "running"), kind="escalation", title="Task 2 failed", why="w")
    text = dailyreport.build(quiet, NOW)
    assert "Finished in the last 24 hours (1)" in text and "(done)" in text
    assert "Failed or stopped in the last 24 hours" in text and "(failed)" in text
    assert "Waiting for you" in text and "Nothing needs you." not in text
    assert "old1" not in text and len(text) <= 1200


def test_many_waiting_items_are_cut(quiet):
    make_project()
    for n in range(8):
        make_run(f"f{n}", "failed", ago_s=60 + n)
    text = dailyreport.build(quiet, NOW)
    assert "and 5 more" in text and len(text) <= 1200


def test_money_is_removed(quiet):
    make_project()
    run = make_run("live", "running")
    gates.open_gate(run, kind="escalation", title="Spent $12.50 and USD 3 and 4 dollars and 5 USD", why="w")
    text = dailyreport.build(quiet, NOW)
    assert not DOLLAR.search(text) and "12.50" not in text
    for s in ("$12.50", "USD 3", "12 dollars", "12 USD"):
        assert dailyreport.strip_money(f"cost {s} here") == "cost (amount hidden) here"
    assert not DOLLAR.search(dailyreport.telegram_text(text))


def test_token_masked(quiet):
    make_project()
    gates.open_gate(make_run("live", "running"), kind="escalation", title=f"leaked {TOKEN}", why="w")
    assert TOKEN not in dailyreport.build(quiet, NOW)
    assert TOKEN not in dailyreport.telegram_text(f"hello {TOKEN}")


def test_telegram_text_short_and_ends_well(quiet):
    make_project()
    for n in range(8):
        make_run(f"f{n}", "failed", ago_s=60 + n)
    long = dailyreport.telegram_text(dailyreport.build(quiet, NOW) + " x" * 500)
    assert len(long) <= 600 and long.endswith("More in the bell.")
    short = dailyreport.telegram_text("Hi.")
    assert short == "Hi. More in the bell."
