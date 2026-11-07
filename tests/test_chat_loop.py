"""Tests for the runner's chat upkeep (fakes only): sleep, off, skips, spacing and error safety."""
import pytest

from phoenix9 import events, paths, projectchat, watch

NOW = 1_000_000.0
IDLE_LIVE = NOW - 121 * 60
OLD_SLEEP = NOW - 4 * 86400


@pytest.fixture
def world(adapters, monkeypatch):
    """Patch the project list, chat docs, states and actions; return the call log and state table."""
    adapters.clock.t = NOW
    w = {"names": ["alpha"], "states": {}, "calls": [], "runs": [], "docs": None}
    monkeypatch.setattr("phoenix9.project.project_names", lambda: list(w["names"]))
    monkeypatch.setattr(projectchat, "read_chat_doc", lambda p: ({"x": 1}, None))
    monkeypatch.setattr(watch, "all_states", lambda: list(w["runs"]))

    def state(p, a):
        s = w["states"][p]
        if isinstance(s, Exception):
            raise s
        return s
    monkeypatch.setattr(projectchat, "state", state)
    monkeypatch.setattr(projectchat, "sleep", lambda p, a, who="cli", wrap_up=True: w["calls"].append(("sleep", p, who)))
    monkeypatch.setattr(projectchat, "off", lambda p, a, who="cli": w["calls"].append(("off", p, who)))
    return w



def test_idle_live_chat_sleeps(world, adapters):
    world["states"]["alpha"] = {"state": "live", "last_active": IDLE_LIVE}
    watch.check_chats(adapters, watch.Memory())
    assert world["calls"] == [("sleep", "alpha", "runner")]


def test_recent_live_chat_left_alone(world, adapters):
    world["states"]["alpha"] = {"state": "live", "last_active": NOW - 60}
    watch.check_chats(adapters, watch.Memory())
    assert world["calls"] == []


def test_old_sleeping_chat_goes_off(world, adapters):
    world["states"]["alpha"] = {"state": "sleeping", "last_active": OLD_SLEEP}
    watch.check_chats(adapters, watch.Memory())
    assert world["calls"] == [("off", "alpha", "runner")]


@pytest.mark.parametrize("word", ["working", "starting", "off"])
def test_other_states_left_alone(world, adapters, word):
    world["states"]["alpha"] = {"state": word, "last_active": OLD_SLEEP}
    watch.check_chats(adapters, watch.Memory())
    assert world["calls"] == []


def test_missing_last_active_is_never_idle(world, adapters):
    world["states"]["alpha"] = {"state": "live", "last_active": None}
    watch.check_chats(adapters, watch.Memory())
    assert world["calls"] == []


@pytest.mark.parametrize("status", ["queued", "running", "waiting", "paused-limit"])
def test_project_with_active_run_skipped(world, adapters, status):
    world["states"]["alpha"] = {"state": "live", "last_active": IDLE_LIVE}
    world["runs"] = [{"project": "alpha", "status": status}]
    watch.check_chats(adapters, watch.Memory())
    assert world["calls"] == []


def test_ended_run_does_not_block(world, adapters):
    world["states"]["alpha"] = {"state": "live", "last_active": IDLE_LIVE}
    world["runs"] = [{"project": "alpha", "status": "done"}]
    watch.check_chats(adapters, watch.Memory())
    assert world["calls"] == [("sleep", "alpha", "runner")]


def test_home_skipped(world, adapters):
    world["names"] = ["home"]
    world["states"]["home"] = {"state": "live", "last_active": IDLE_LIVE}
    watch.check_chats(adapters, watch.Memory())
    assert world["calls"] == []


def test_ten_minute_spacing(world, adapters):
    world["states"]["alpha"] = {"state": "live", "last_active": IDLE_LIVE}
    memory = watch.Memory()
    watch.check_chats(adapters, memory)
    watch.check_chats(adapters, memory)
    assert len(world["calls"]) == 1
    adapters.clock.t += 599
    watch.check_chats(adapters, memory)
    assert len(world["calls"]) == 1
    adapters.clock.t += 1
    watch.check_chats(adapters, memory)
    assert len(world["calls"]) == 2


def test_error_in_one_project_does_not_stop_others(world, adapters):
    world["names"] = ["alpha", "beta"]
    world["states"]["alpha"] = RuntimeError("boom")
    world["states"]["beta"] = {"state": "live", "last_active": IDLE_LIVE}
    watch.check_chats(adapters, watch.Memory())
    assert world["calls"] == [("sleep", "beta", "runner")]


def test_error_inside_check_chats_does_not_raise(world, adapters, monkeypatch):
    def boom():
        raise RuntimeError("boom")
    monkeypatch.setattr("phoenix9.project.project_names", boom)
    watch.check_chats(adapters, watch.Memory())


def test_action_records_runner_command_event(world, adapters, monkeypatch):
    seen = []
    monkeypatch.setattr("phoenix9.ops.common.record_command", lambda *a, **k: seen.append(a))
    world["states"]["alpha"] = {"state": "live", "last_active": IDLE_LIVE}
    watch.check_chats(adapters, watch.Memory())
    assert seen == [("runner", "chat sleep alpha", "alpha")]
