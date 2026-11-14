"""Tests for the new agent's watchdog: healthy, bad checks, back-off, stopped on purpose, not set up, the loop."""
import pytest

from phoenix9 import agentkitwatch, doctor, paths, watch

UNIT = "phoenix-agentkit"


@pytest.fixture
def ad(adapters, phoenix_env):
    """Fakes with [agent_next] set up and a healthy, answering service."""
    paths.config().mkdir(parents=True, exist_ok=True)
    (paths.config() / "global.toml").write_text("[agent_next]\nuid = 990\n")
    healthy(adapters)
    return adapters


def healthy(ad):
    ad.host.script(["systemctl", "is-active", UNIT], 0, "active\n")
    ad.agentnext.down = False


def not_answering(ad):
    ad.agentnext.down = True


def crashed(ad):
    ad.host.script(["systemctl", "is-active", UNIT], 3, "failed\n")
    ad.host.script(["systemctl", "show"], 0, "ActiveState=failed\nResult=exit-code\n")


def restarts(ad):
    return [c for c in ad.host.calls if c == ["systemctl", "restart", UNIT]]


def run(ad, n):
    did = []
    for _ in range(n):
        did.append(agentkitwatch.check_once(ad))
        ad.clock.sleep(60)
    return did


def test_healthy_does_nothing(ad):
    assert run(ad, 4) == ["", "", "", ""]
    assert not restarts(ad) and not ad.notify.messages
    assert agentkitwatch.memory()["bad"] == 0


def test_one_bad_check_does_nothing(ad):
    not_answering(ad)
    run(ad, 1)
    healthy(ad)
    run(ad, 1)
    not_answering(ad)
    run(ad, 1)
    assert not restarts(ad) and not ad.notify.messages


def test_two_bad_checks_restart_once_and_notify_once(ad):
    not_answering(ad)
    did = run(ad, 2)
    assert did[-1] and len(restarts(ad)) == 1
    assert ad.notify.messages == [agentkitwatch.NOTICE]
    assert agentkitwatch.memory()["last_restart"] is not None
    assert (paths.logs() / "agentkit-watch.json").is_file()


def test_a_crashed_unit_counts_as_bad(ad):
    crashed(ad)
    run(ad, 2)
    assert len(restarts(ad)) == 1 and len(ad.notify.messages) == 1


def test_back_off_holds(ad):
    not_answering(ad)
    run(ad, 2)
    run(ad, 6)            # still down, but within the back-off
    assert len(restarts(ad)) == 1 and len(ad.notify.messages) == 1
    ad.clock.sleep(agentkitwatch.BACKOFF_S)
    run(ad, 2)
    assert len(restarts(ad)) == 2 and len(ad.notify.messages) == 2


def test_stopped_on_purpose_does_nothing(ad):
    ad.host.script(["systemctl", "is-active", UNIT], 3, "inactive\n")
    ad.host.script(["systemctl", "show"], 0, "ActiveState=inactive\nResult=success\n")
    run(ad, 5)
    assert not restarts(ad) and not ad.notify.messages
    assert agentkitwatch.memory()["stopped"] is True


def test_not_set_up_does_nothing(adapters, phoenix_env):
    not_answering(adapters)
    run(adapters, 5)
    assert not adapters.host.calls and not adapters.notify.messages and not adapters.agentnext.calls


def test_odd_memory_file_is_ignored(ad):
    paths.logs().mkdir(parents=True, exist_ok=True)
    (paths.logs() / "agentkit-watch.json").write_text('["odd"]')
    assert agentkitwatch.memory() == {"bad": 0, "last_restart": None, "stopped": False}


def test_doctor_names_a_recent_restart(ad):
    not_answering(ad)
    run(ad, 2)
    healthy(ad)
    line = next(c for c in doctor.run_checks(ad, "quick")["checks"] if c["name"] == "agentkit-service")
    assert "the watchdog last restarted it at" in line["detail"]
    ad.clock.sleep(86400)
    line = next(c for c in doctor.run_checks(ad, "quick")["checks"] if c["name"] == "agentkit-service")
    assert "watchdog" not in line["detail"]


def test_watch_loop_calls_it(ad, monkeypatch):
    seen = []
    monkeypatch.setattr(agentkitwatch, "check_once", lambda a: seen.append(a) or "")
    memory = watch.Memory()
    watch.check_agentkit(ad, memory)
    watch.check_agentkit(ad, memory)     # less than a minute later: skipped
    ad.clock.sleep(watch.AGENT_CHECK_S)
    watch.check_agentkit(ad, memory)
    assert seen == [ad, ad]


def test_watch_loop_survives_an_exception(ad, monkeypatch):
    def boom(a):
        raise RuntimeError("broken")
    monkeypatch.setattr(agentkitwatch, "check_once", boom)
    watch.check_agentkit(ad, watch.Memory())


def test_watch_forever_runs_it(ad, monkeypatch):
    seen = []
    monkeypatch.setattr(agentkitwatch, "check_once", lambda a: seen.append(a) or "")
    monkeypatch.setattr(ad.clock, "sleep", lambda s: (_ for _ in ()).throw(KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        watch.watch_forever(ad, object())
    assert seen == [ad]
