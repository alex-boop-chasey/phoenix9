"""Tests for the runner's chat upkeep (fakes only): sleep, stuck waking, skips, spacing and error safety."""
import pytest

from phoenix9 import chat, events, paths, projectchat, watch

NOW = 1_000_000.0
IDLE_LIVE = NOW - 121 * 60
OLD = NOW - 4 * 86400


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
    monkeypatch.setattr(chat, "stop_unit", lambda host, p: w["calls"].append(("stop", p)))
    return w



def test_idle_live_chat_sleeps(world, adapters):
    world["states"]["alpha"] = {"state": "awake", "last_active": IDLE_LIVE}
    watch.check_chats(adapters, watch.Memory())
    assert world["calls"] == [("sleep", "alpha", "runner")]


def test_recent_live_chat_left_alone(world, adapters):
    world["states"]["alpha"] = {"state": "awake", "last_active": NOW - 60}
    watch.check_chats(adapters, watch.Memory())
    assert world["calls"] == []


def test_old_asleep_chat_is_not_switched_off(world, adapters):
    world["states"]["alpha"] = {"state": "asleep", "last_active": OLD}
    watch.check_chats(adapters, watch.Memory())
    assert world["calls"] == []


@pytest.mark.parametrize("word", ["working", "asleep", "none"])
def test_other_states_left_alone(world, adapters, word):
    world["states"]["alpha"] = {"state": word, "last_active": OLD}
    memory = watch.Memory()
    watch.check_chats(adapters, memory)
    adapters.clock.t += 600
    watch.check_chats(adapters, memory)
    assert world["calls"] == []


def test_waking_chat_stopped_after_ten_minutes(world, adapters):
    world["states"]["alpha"] = {"state": "waking", "last_active": None}
    memory = watch.Memory()
    watch.check_chats(adapters, memory)
    assert world["calls"] == []                      # first seen waking: left alone
    adapters.clock.t += 600
    watch.check_chats(adapters, memory)
    assert world["calls"] == [("stop", "alpha")]


def test_waking_then_awake_resets_the_stuck_clock(world, adapters):
    memory = watch.Memory()
    world["states"]["alpha"] = {"state": "waking", "last_active": None}
    watch.check_chats(adapters, memory)
    world["states"]["alpha"] = {"state": "awake", "last_active": NOW}
    adapters.clock.t += 600
    watch.check_chats(adapters, memory)
    world["states"]["alpha"] = {"state": "waking", "last_active": None}
    adapters.clock.t += 600
    watch.check_chats(adapters, memory)
    assert world["calls"] == []


def test_stuck_chat_records_one_command(world, adapters, monkeypatch):
    seen = []
    monkeypatch.setattr("phoenix9.ops.common.record_command", lambda *a, **k: seen.append(a))
    world["states"]["alpha"] = {"state": "waking", "last_active": None}
    memory = watch.Memory()
    watch.check_chats(adapters, memory)
    adapters.clock.t += 600
    watch.check_chats(adapters, memory)
    assert seen == [("runner", "chat stop-stuck alpha", "alpha")]


def test_missing_last_active_is_never_idle(world, adapters):
    world["states"]["alpha"] = {"state": "awake", "last_active": None}
    watch.check_chats(adapters, watch.Memory())
    assert world["calls"] == []


@pytest.mark.parametrize("status", ["queued", "running", "waiting", "paused-limit"])
def test_project_with_active_run_skipped(world, adapters, status):
    world["states"]["alpha"] = {"state": "awake", "last_active": IDLE_LIVE}
    world["runs"] = [{"project": "alpha", "status": status}]
    watch.check_chats(adapters, watch.Memory())
    assert world["calls"] == []


def test_ended_run_does_not_block(world, adapters):
    world["states"]["alpha"] = {"state": "awake", "last_active": IDLE_LIVE}
    world["runs"] = [{"project": "alpha", "status": "done"}]
    watch.check_chats(adapters, watch.Memory())
    assert world["calls"] == [("sleep", "alpha", "runner")]


@pytest.mark.parametrize("name", ["home", "phoenix9"])
def test_own_chats_skipped(world, adapters, name):
    world["names"] = [name]
    world["states"][name] = {"state": "awake", "last_active": IDLE_LIVE}
    watch.check_chats(adapters, watch.Memory())
    assert world["calls"] == []


def test_ten_minute_spacing(world, adapters):
    world["states"]["alpha"] = {"state": "awake", "last_active": IDLE_LIVE}
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
    world["states"]["beta"] = {"state": "awake", "last_active": IDLE_LIVE}
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
    world["states"]["alpha"] = {"state": "awake", "last_active": IDLE_LIVE}
    watch.check_chats(adapters, watch.Memory())
    assert seen == [("runner", "chat sleep alpha", "alpha")]
