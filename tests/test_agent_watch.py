"""Tests for the agent watchdog: healthy, bad checks, back-off, watchdog off, runs untouched."""
import json
import types

import pytest

from fakes import FakeClock, FakeHost, FakeNotify
from phoenix9 import agentlink, agentwatch

FOLDER = "/srv/projects/home"
CH = "/root/.claude"


@pytest.fixture
def ad(tmp_path, monkeypatch):
    """Adapters with a fake host, clock and notify, and a private Phoenix home."""
    monkeypatch.setenv("PHOENIX_HOME", str(tmp_path / "home"))
    (tmp_path / "home" / "logs").mkdir(parents=True)
    return types.SimpleNamespace(host=FakeHost(), clock=FakeClock(), notify=FakeNotify())


def healthy(host):
    host.files[CH + "/sessions/1.json"] = json.dumps({"pid": 1, "cwd": FOLDER, "name": "Phoenix agent",
        "status": "idle", "messagingSocketPath": "/tmp/cc-socks-0/s.sock", "sessionId": "s"})
    host.files["/tmp/cc-socks-0/s.sock"] = ""
    host.pids.add(1)
    host.script(["systemctl", "is-active"], 0, "active\n")


def sick(host):
    host.files.clear()
    host.pids.clear()
    host.script(["systemctl", "is-active"], 3, "inactive\n")


def restarts(host):
    return [c for c in host.calls if c[:2] == ["systemctl", "restart"]]


def run(ad, n):
    for _ in range(n):
        agentwatch.check_once(ad)
        ad.clock.sleep(60)


def test_healthy(ad):
    healthy(ad.host)
    run(ad, 4)
    assert not restarts(ad.host) and not ad.notify.messages


def test_one_bad_check(ad):
    sick(ad.host)
    run(ad, 1)
    healthy(ad.host)
    run(ad, 1)
    sick(ad.host)
    run(ad, 1)
    assert not restarts(ad.host)


def test_two_bad_checks_and_backoff(ad):
    sick(ad.host)
    run(ad, 2)
    assert len(restarts(ad.host)) == 1
    assert len(ad.notify.messages) == 1 and ad.notify.messages[0].startswith("Phoenix agent restarted: ")
    run(ad, 6)
    assert len(restarts(ad.host)) == 1
    ad.clock.sleep(600)
    run(ad, 2)
    assert len(restarts(ad.host)) == 2 and len(ad.notify.messages) == 2


def test_watchdog_off(ad, tmp_path):
    (tmp_path / "home" / "config").mkdir()
    (tmp_path / "home" / "config" / "global.toml").write_text("[agent]\nwatchdog = false\n")
    sick(ad.host)
    run(ad, 4)
    assert not ad.host.calls and not ad.notify.messages


def test_no_run_state_touched(ad, tmp_path):
    sick(ad.host)
    run(ad, 3)
    assert not (tmp_path / "home" / "runs").exists()
    assert agentwatch.memory_path().name == "agent-watch.json"
