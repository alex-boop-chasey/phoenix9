"""Tests for the runner sending the daily report and the allowance warnings."""
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from phoenix9 import statusreport as sr, watch

TZ = ZoneInfo("Australia/Melbourne")
DOLLAR = re.compile(r"\$|\bUSD\b|dollar", re.I)


def at(d, h, mi):
    return datetime(2026, 11, d, h, mi, tzinfo=TZ).timestamp()


@pytest.fixture
def quiet(monkeypatch, adapters):
    adapters.host.script(["systemctl", "is-active"], 0, "active\nactive")
    monkeypatch.setattr(sr, "_open_prs", lambda a: [])
    return adapters


def allowance(adapters, state, share):
    adapters.agentnext.chunks = [json.dumps({"state": state, "used_share": share}).encode()]


def test_loop_sends_daily_report_once(quiet):
    allowance(quiet, "plenty", 0.1)
    memory = watch.Memory()
    quiet.clock.t = at(11, 7, 59)
    watch.check_daily_report(quiet, memory)
    assert quiet.notify.messages == []
    for t in (at(11, 8, 0), at(11, 8, 1), at(11, 9, 0)):
        quiet.clock.t = t
        watch.check_daily_report(quiet, memory)
    assert len(quiet.notify.messages) == 1


def test_low_sent_once_and_restart_does_not_resend(quiet):
    allowance(quiet, "low", 0.82)
    quiet.clock.t = at(11, 10, 0)
    memory = watch.Memory()
    watch.check_allowance(quiet, memory)
    quiet.clock.t += 400
    watch.check_allowance(quiet, memory)
    watch.check_allowance(quiet, watch.Memory())      # a restart
    assert len(quiet.notify.messages) == 1
    assert "82%" in quiet.notify.messages[0] and not DOLLAR.search(quiet.notify.messages[0])


def test_used_up_sent_once_after_low(quiet):
    quiet.clock.t = at(11, 10, 0)
    memory = watch.Memory()
    allowance(quiet, "low", 0.85)
    watch.check_allowance(quiet, memory)
    quiet.clock.t += 400
    allowance(quiet, "used_up", 1.0)
    watch.check_allowance(quiet, memory)
    quiet.clock.t += 400
    watch.check_allowance(quiet, memory)
    assert len(quiet.notify.messages) == 2
    assert "used up" in quiet.notify.messages[1] and not DOLLAR.search(quiet.notify.messages[1])


def test_new_month_resets(quiet):
    allowance(quiet, "low", 0.9)
    quiet.clock.t = at(11, 10, 0)
    watch.check_allowance(quiet, watch.Memory())
    quiet.clock.t = datetime(2026, 12, 2, 10, 0, tzinfo=TZ).timestamp()
    watch.check_allowance(quiet, watch.Memory())
    assert len(quiet.notify.messages) == 2


def test_plenty_sends_nothing_and_unreachable_does_not_stop(quiet):
    quiet.clock.t = at(11, 10, 0)
    allowance(quiet, "plenty", 0.1)
    watch.check_allowance(quiet, watch.Memory())
    quiet.agentnext.down = True
    quiet.clock.t += 400
    watch.check_allowance(quiet, watch.Memory())
    assert quiet.notify.messages == []


def test_errors_are_swallowed(quiet, monkeypatch):
    from phoenix9 import allowance as al, dailyreport

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(al, "read", boom)
    monkeypatch.setattr(dailyreport, "send_if_due", boom)
    watch.check_allowance(quiet, watch.Memory())
    watch.check_daily_report(quiet, watch.Memory())
