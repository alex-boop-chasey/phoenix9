"""Tests for when the daily report is due, and saving and sending it."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from phoenix9 import dailyreport, settings, statusreport as sr

TZ = "Australia/Melbourne"
CFG = {"enabled": True, "time": "08:00", "timezone": TZ}


def at(y, mo, d, h, mi, tz=TZ):
    return datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(tz)).timestamp()


@pytest.fixture
def quiet(monkeypatch, adapters):
    adapters.host.script(["systemctl", "is-active"], 0, "active\nactive")
    adapters.agentnext.chunks = [json.dumps({"state": "plenty", "used_share": 0.1}).encode()]
    monkeypatch.setattr(sr, "_open_prs", lambda a: [])
    return adapters


def test_not_due_before_time():
    assert not dailyreport.due(at(2026, 11, 11, 7, 59), CFG, None)


def test_due_at_time_and_after():
    assert dailyreport.due(at(2026, 11, 11, 8, 0), CFG, None)
    assert dailyreport.due(at(2026, 11, 11, 9, 30), CFG, "2026-11-10")


def test_once_per_day():
    assert not dailyreport.due(at(2026, 11, 11, 9, 30), CFG, "2026-11-11")


def test_changed_time_and_timezone():
    assert not dailyreport.due(at(2026, 11, 11, 8, 30), {**CFG, "time": "09:00"}, None)
    assert dailyreport.due(at(2026, 11, 11, 9, 0), {**CFG, "time": "09:00"}, None)
    now = at(2026, 11, 11, 8, 0)
    assert dailyreport.due(at(2026, 11, 11, 8, 0, "Europe/London"), {**CFG, "timezone": "Europe/London"}, None)
    assert not dailyreport.due(at(2026, 11, 11, 7, 59, "Europe/London"), {**CFG, "timezone": "Europe/London"}, None)


def test_dst_change_day():
    # Melbourne clocks went forward on 2026-10-04: 02:00 became 03:00
    cfg = {**CFG, "time": "02:30"}
    assert not dailyreport.due(at(2026, 10, 4, 1, 59), cfg, None)
    assert dailyreport.due(at(2026, 10, 4, 3, 0), cfg, None)
    assert dailyreport.due(at(2026, 10, 4, 8, 0), CFG, "2026-10-03")


def test_disabled():
    assert not dailyreport.due(at(2026, 11, 11, 9, 0), {**CFG, "enabled": False}, None)


def test_send_if_due_sends_once_and_saves(quiet):
    quiet.clock.t = at(2026, 11, 11, 9, 30)
    assert dailyreport.send_if_due(quiet) is True
    assert dailyreport.send_if_due(quiet) is False
    assert len(quiet.notify.messages) == 1 and len(quiet.notify.messages[0]) <= 600
    assert dailyreport.latest()["date"] == "2026-11-11"
    assert "Phoenix daily report" in dailyreport.latest()["text"]
    quiet.clock.t = at(2026, 11, 12, 8, 0)
    assert dailyreport.send_if_due(quiet) is True
    assert len(quiet.notify.messages) == 2


def test_nothing_before_time_or_disabled(quiet):
    quiet.clock.t = at(2026, 11, 11, 7, 59)
    assert dailyreport.send_if_due(quiet) is False
    quiet.clock.t = at(2026, 11, 11, 9, 0)
    settings.save_report_settings({"enabled": False})
    assert dailyreport.send_if_due(quiet) is False
    assert quiet.notify.messages == [] and dailyreport.latest() is None


def test_failed_send_keeps_file_and_retries(quiet):
    quiet.clock.t = at(2026, 11, 11, 9, 0)
    real = quiet.notify.send

    def boom(text):
        raise OSError("no")
    quiet.notify.send = boom
    assert dailyreport.send_if_due(quiet) is False
    assert dailyreport.latest()["date"] == "2026-11-11"
    quiet.notify.send = real
    assert dailyreport.send_if_due(quiet) is True
    assert len(quiet.notify.messages) == 1


def test_keeps_newest_30(quiet):
    for day in range(1, 29):
        quiet.clock.t = at(2026, 10, day, 9, 0)
        dailyreport.send_if_due(quiet)
    for day in range(1, 8):
        quiet.clock.t = at(2026, 11, day, 9, 0)
        dailyreport.send_if_due(quiet)
    assert len(list(dailyreport._dir().glob("*.md"))) == 30
    assert dailyreport.latest()["date"] == "2026-11-07"
