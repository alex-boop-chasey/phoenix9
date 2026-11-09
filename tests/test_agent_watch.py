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


def memory():
    return json.loads(agentwatch.memory_path().read_text())


def test_bad_count_resets_after_a_restart(ad):
    sick(ad.host)
    run(ad, 2)
    assert len(restarts(ad.host)) == 1 and memory()["bad"] == 0


def stopped_on_purpose(host):
    sick(host)
    host.script(["systemctl", "show"], 0, "ActiveState=inactive\nResult=success\n")


def test_unit_stopped_on_purpose_is_left_alone(ad):
    """`systemctl stop` leaves the unit inactive with Result=success: the watchdog records it and never restarts."""
    stopped_on_purpose(ad.host)
    results = [agentwatch.check_once(ad) for _ in range(5)]
    assert results == ["stopped"] * 5 and not restarts(ad.host) and not ad.notify.messages
    assert memory()["stopped"] is True and memory()["bad"] == 0
    healthy(ad.host)
    assert agentwatch.check_once(ad) == "ok" and memory()["stopped"] is False


@pytest.mark.parametrize("show", ["ActiveState=failed\nResult=exit-code\n", "ActiveState=inactive\nResult=signal\n"])
def test_unit_that_failed_is_restarted(ad, show):
    sick(ad.host)
    ad.host.script(["systemctl", "show"], 0, show)
    run(ad, 2)
    assert len(restarts(ad.host)) == 1


def test_doctor_says_the_agent_was_stopped_by_someone(ad):
    from phoenix9 import doctor
    stopped_on_purpose(ad.host)
    agentwatch.check_once(ad)
    ok, detail, fix = doctor.check_agent_unit(types.SimpleNamespace(ad=ad))
    assert not ok and "stopped by someone" in detail and "systemctl start" in fix


def pending(tmp_path):
    (tmp_path / "home" / "agent-rules-pending").write_text("agent rules updated; restart when idle\n")


def test_pending_rules_restart_once_when_idle(ad, tmp_path):
    from phoenix9 import agentsync, events, paths
    healthy(ad.host)
    pending(tmp_path)
    assert agentwatch.check_once(ad) == "restarted-rules"
    assert len(restarts(ad.host)) == 1 and not agentsync.pending_restart()
    assert "agent.restarted_for_rules" in [e["type"] for e in events.read(paths.events())]
    run(ad, 3)
    assert len(restarts(ad.host)) == 1


def test_pending_rules_wait_while_the_agent_works(ad, tmp_path):
    from phoenix9 import agentsync
    healthy(ad.host)
    ad.host.files[CH + "/sessions/1.json"] = ad.host.files[CH + "/sessions/1.json"].replace('"idle"', '"busy"')
    pending(tmp_path)
    assert agentwatch.check_once(ad) == "ok"
    assert not restarts(ad.host) and agentsync.pending_restart()
    healthy(ad.host)
    assert agentwatch.check_once(ad) == "restarted-rules" and not agentsync.pending_restart()
