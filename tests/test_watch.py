"""Tests for the runner service loop (phoenix9/watch.py), with a fake clock and a fake runner."""
from datetime import datetime, timezone

from fakes import fake_adapters
from phoenix9 import atomic, claude, state, watch
from phoenix9.stepctx import UsageLimit


def make_run(run_id, status="queued", created="2026-11-01T10:00:00+00:00"):
    """Write a state.json for a run in project p and return its folder."""
    folder = watch.paths.runs("p") / run_id
    s = state.new_state(run_id, "p")
    s["status"], s["created"] = status, created
    atomic.write_json(folder / "state.json", s)
    return folder


class FakeRunner:
    """Records drive calls; each call does the next scripted action (a status, or an exception to raise)."""

    def __init__(self, *script):
        self.script = list(script)
        self.driven = []

    def drive(self, run_dir):
        self.driven.append(run_dir.name)
        action = self.script.pop(0) if self.script else "done"
        if isinstance(action, Exception):
            raise action
        state.set_status(run_dir, action)
        return action


def test_next_run_picks_oldest_queued():
    a = {"run_id": "a", "status": "queued", "created": "2026-11-01T11:00:00+00:00"}
    b = {"run_id": "b", "status": "queued", "created": "2026-11-01T10:00:00+00:00"}
    assert watch.next_run([a, b])["run_id"] == "b"
    assert watch.next_run([]) is None


def test_nothing_starts_while_one_waits_or_is_paused():
    queued = {"run_id": "q", "status": "queued", "created": "1"}
    for busy in ("waiting", "paused-limit"):
        assert watch.next_run([{"run_id": "w", "status": busy, "created": "0"}, queued]) is None


def test_running_is_resumed_first():
    queued = {"run_id": "q", "status": "queued", "created": "0"}
    running = {"run_id": "r", "status": "running", "created": "9"}
    assert watch.next_run([queued, running])["run_id"] == "r"


def test_watch_once_drives_the_oldest_queued(tmp_path):
    make_run("new", created="2026-11-01T12:00:00+00:00")
    make_run("old")
    runner = FakeRunner("done")
    assert watch.watch_once(fake_adapters(tmp_path), runner) == "old"
    assert runner.driven == ["old"]


def test_watch_once_idle_when_a_run_waits(tmp_path):
    make_run("w", "waiting")
    make_run("q")
    runner = FakeRunner()
    assert watch.watch_once(fake_adapters(tmp_path), runner) is None
    assert runner.driven == []


def test_three_crashes_fail_the_run_and_notify(tmp_path):
    folder = make_run("r1")
    ad, memory = fake_adapters(tmp_path), watch.Memory()
    runner = FakeRunner(*[RuntimeError("boom")] * 3)
    for _ in range(3):
        watch.watch_once(ad, runner, memory)
    s = state.load(folder)
    assert s["status"] == "failed" and "boom" in s["error"]
    assert len(ad.notify.messages) == 1 and "r1" in ad.notify.messages[0]


def test_a_success_resets_the_crash_count(tmp_path):
    make_run("r1")
    ad, memory = fake_adapters(tmp_path), watch.Memory()
    runner = FakeRunner(RuntimeError("x"), "running", RuntimeError("x"), "running", RuntimeError("x"))
    for _ in range(5):
        watch.watch_once(ad, runner, memory)
    assert state.load(watch.paths.runs("p") / "r1")["status"] == "running"
    assert ad.notify.messages == []


def limit_result(hours):
    resets = datetime.fromtimestamp(1000.0 + hours * 3600, timezone.utc)
    return claude.Result(kind="rate_limited", resets_at=resets)


def test_usage_limit_pauses_notifies_once_and_resumes(tmp_path):
    folder = make_run("r1")
    ad = fake_adapters(tmp_path)
    runner = FakeRunner(UsageLimit(limit_result(3)), "done")
    seen = []
    real_wait = claude.wait_for_limit

    def spy(*a, **k):
        seen.append(state.load(folder)["status"])
        return real_wait(*a, **k)
    claude_wait, claude.wait_for_limit = claude.wait_for_limit, spy
    try:
        watch.watch_once(ad, runner)
    finally:
        claude.wait_for_limit = claude_wait
    assert seen == ["paused-limit"]
    assert len(ad.notify.messages) == 1 and "usage limit" in ad.notify.messages[0]
    assert state.load(folder)["status"] == "running"
    watch.watch_once(ad, runner)
    assert state.load(folder)["status"] == "done"


def test_short_limit_wait_does_not_notify(tmp_path):
    make_run("r1")
    ad = fake_adapters(tmp_path)
    watch.watch_once(ad, FakeRunner(UsageLimit(limit_result(0.2))))
    assert ad.notify.messages == []


def test_limit_uses_probe_when_reset_unknown(tmp_path):
    make_run("r1")
    ad = fake_adapters(tmp_path)
    ad.claude.probes = ["rate_limited", "ok"]
    watch.watch_once(ad, FakeRunner(UsageLimit(claude.Result(kind="rate_limited"))))
    assert ad.claude.probes == []
    assert state.load(watch.paths.runs("p") / "r1")["status"] == "running"


def test_a_stop_landing_after_the_paused_check_is_never_overwritten(tmp_path, monkeypatch):
    """The stop lands between the 'still paused?' look and the pause write: the run stays stopped."""
    folder = make_run("r1", "running")
    ad = fake_adapters(tmp_path)
    real, looks = watch._still_paused, []

    def stop_lands_after_the_look(run_dir):
        answer = real(run_dir)
        if not looks:
            state.set_status(run_dir, "stopped")     # someone stopped it right after the first look
        looks.append(answer)
        return answer
    seen = []
    monkeypatch.setattr(claude, "wait_for_limit", lambda *a, **k: seen.append(state.load(folder)["status"]) or True)
    monkeypatch.setattr(watch, "_still_paused", stop_lands_after_the_look)
    assert watch.wait_out_limit(ad, state.load(folder), limit_result(0.1)) is False
    assert state.load(folder)["status"] == "stopped" and seen == []    # never paused, never waited


def test_a_stop_during_the_limit_wait_is_never_resumed(tmp_path, monkeypatch):
    folder = make_run("r1", "running")
    ad = fake_adapters(tmp_path)

    def wait_then_stopped(*a, **k):
        state.set_status(folder, "stopped")
        return True
    monkeypatch.setattr(claude, "wait_for_limit", wait_then_stopped)
    assert watch.wait_out_limit(ad, state.load(folder), limit_result(0.1)) is False
    assert state.load(folder)["status"] == "stopped"


def test_waiting_run_is_redriven_only_with_an_answer(tmp_path):
    folder = make_run("w", "waiting")
    atomic.write_json(folder / "gates" / "w.0.answer.json", {"action": "approve"})   # an old gate's answer
    state.update(folder, lambda s: s["current"].__setitem__("gate", "w.1"))
    runner = FakeRunner("waiting")
    assert watch.watch_once(fake_adapters(tmp_path), runner) is None
    atomic.write_json(folder / "gates" / "w.1.answer.json", {"action": "approve"})
    assert watch.watch_once(fake_adapters(tmp_path), runner) == "w"
    assert runner.driven == ["w"]


def test_watch_forever_cleans_orphans_first(tmp_path, monkeypatch):
    ad = fake_adapters(tmp_path)
    ad.docker.orphans = ["c1"]

    def stop(*a):
        raise KeyboardInterrupt
    monkeypatch.setattr(ad.clock, "sleep", stop)
    try:
        watch.watch_forever(ad, FakeRunner())
    except KeyboardInterrupt:
        pass
    assert ad.docker.removed == ["c1"]


def test_watch_once_writes_the_heartbeat(tmp_path):
    from phoenix9 import heartbeat
    ad = fake_adapters(tmp_path)
    ad.clock.t = 4242.0
    watch.watch_once(ad, FakeRunner())
    assert heartbeat.read()["at"] == 4242.0


def test_heartbeat_keeps_beating_while_a_long_step_runs(tmp_path):
    """The loop is blocked inside drive() for a long step; a side thread keeps the heartbeat fresh."""
    import threading
    from phoenix9 import heartbeat
    ad = fake_adapters(tmp_path)
    stop = threading.Event()
    heartbeat.reset_progress()
    heartbeat.mark_progress()           # the loop moved just now (a step started)
    beats = heartbeat.start_ticker(ad.clock, interval_s=0.01, stop=stop)
    try:
        for _ in range(200):
            if heartbeat.read():
                break
            stop.wait(0.01)
    finally:
        stop.set()
        beats.join(1)
    assert heartbeat.read()["at"] == ad.clock.t
