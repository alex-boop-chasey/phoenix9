"""The runner service loop: picks the next run, drives it, counts crashes and waits out usage limits."""
# ported from reference/v8/phoenix/watch.py (crash counting, limit_notice, drive_safely)
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from phoenix9 import atomic, docker as docker_mod, gates, heartbeat, hold, paths, runend, state
from phoenix9 import claude as claude_mod
from phoenix9.stepctx import UsageLimit

MAX_CRASHES = 3          # a run that crashes the loop this many times in a row is failed
LIMIT_NOTICE_S = 3600    # tell Alex when a usage-limit wait is longer than this
INTERVAL_S = 10


@dataclass
class Memory:
    """What the loop remembers between rounds: crashes in a row per run."""

    crashes: dict = field(default_factory=dict)


def all_states() -> list[dict]:
    """The state.json of every run on the server."""
    root = paths.runs()
    found = []
    if root.is_dir():
        for project in sorted(root.iterdir()):
            for d in sorted(project.iterdir()) if project.is_dir() else []:
                s = atomic.read_json(d / "state.json") if d.is_dir() else None
                if s:
                    found.append(s)
    return found


def next_run(all_states_: list[dict]) -> dict | None:
    """The run to drive now: a running one first, else the oldest queued one if the server is free."""
    for s in all_states_:
        if s["status"] == "running":
            return s
    if any(s["status"] in ("waiting", "paused-limit") for s in all_states_):
        return None
    queued = [s for s in all_states_ if s["status"] == "queued"]
    return min(queued, key=lambda s: (s["created"], s["run_id"])) if queued else None


def _run_dir(s: dict) -> Path:
    return paths.runs(s["project"]) / s["run_id"]


def _has_answer(run_dir: Path) -> bool:
    """True when the gate this run waits on now (state current.gate) has been answered."""
    return gates.current_answer(run_dir) is not None


def _fail(adapters, s: dict, reason: str) -> str:
    """End a run failed through the one end function (runend.end_run) under the run lock, and tell Alex."""
    run_dir = _run_dir(s)
    try:
        with runend.lock(run_dir):
            status = runend.end_run(run_dir, "failed", reason=reason, adapters=adapters)["status"]
    except TimeoutError:
        return state.load(run_dir)["status"]    # someone else is ending it right now
    if status == "failed":
        adapters.notify.send(f"Phoenix run {s['run_id']} failed: {reason}")
    return status


def _now(adapters) -> datetime:
    return datetime.fromtimestamp(adapters.clock.now(), timezone.utc)


class _Ended(Exception):
    """The paused run was stopped (or ended) from outside while it waited for the usage limit."""


def _still_paused(run_dir: Path) -> bool:
    st = state.load(run_dir) or {}
    return st.get("status") not in runend.ENDED and runend.stop_requested(run_dir) is None


def _move_if_live(run_dir: Path, status: str, only_from: str | None = None) -> bool:
    """One locked state update: set `status` only while the run has not ended, has no stop request and
    (with only_from) is still in that status. True when it moved. A stop that lands after an earlier
    look is therefore never overwritten."""
    moved = []

    def change(st):
        if st["status"] in runend.ENDED or (only_from and st["status"] != only_from):
            return
        if runend.stop_requested(run_dir) is not None:
            return
        st["status"] = status
        moved.append(True)
    state.update(run_dir, change)
    return bool(moved)


def wait_out_limit(adapters, s: dict, result) -> bool:
    """Pause the run, wait for Claude to answer again (telling Alex once if over an hour); True = resume.
    A run stopped during the wait is left stopped (never set back to running); a stop request ends it."""
    run_dir = _run_dir(s)
    if not _still_paused(run_dir) or not _move_if_live(run_dir, "paused-limit"):
        return _end_paused(adapters, s)
    waited, told = [0.0], [False]

    def sleep(seconds):
        waited[0] += seconds
        if waited[0] > LIMIT_NOTICE_S and not told[0]:
            told[0] = True
            when = result.resets_at.isoformat() if result.resets_at else "unknown"
            adapters.notify.send(f"Phoenix run {s['run_id']} is waiting more than an hour for Claude's "
                                 f"usage limit (resets at {when}).")
        adapters.clock.sleep(seconds)
        heartbeat.mark_progress()                 # waiting out a limit is the loop doing its job
        if not _still_paused(run_dir):
            raise _Ended

    try:
        ok = claude_mod.wait_for_limit(result, adapters.claude.probe, lambda: _now(adapters), sleep)
    except _Ended:
        return _end_paused(adapters, s)
    if not ok:
        _fail(adapters, s, "Claude's usage limit did not clear in time.")
        return False

    if _move_if_live(run_dir, "running", only_from="paused-limit"):
        return True
    return _end_paused(adapters, s)


def _end_paused(adapters, s: dict) -> bool:
    """A paused run with a stop request is stopped the one clean way; one that already ended is left alone."""
    run_dir = _run_dir(s)
    asked = runend.stop_requested(run_dir)
    if asked is not None and (state.load(run_dir) or {}).get("status") not in runend.ENDED:
        from phoenix9.runner import Runner
        try:
            Runner(adapters, paths.library()).stop_now(run_dir, who=asked.get("who") or "cli")
        except TimeoutError:
            pass
    return False


def _crashed(adapters, s: dict, memory: Memory, err: Exception) -> str | None:
    """Count a crash; after MAX_CRASHES in a row fail the run. Returns the new status if it was failed."""
    n = memory.crashes.get(s["run_id"], 0) + 1
    memory.crashes[s["run_id"]] = n
    if n < MAX_CRASHES:
        return None
    memory.crashes.pop(s["run_id"], None)
    return _fail(adapters, s, f"Phoenix hit an error {n} times in a row: {type(err).__name__}: {err}")


def drive_safely(adapters, runner, s: dict, memory: Memory) -> str | None:
    """Drive one run; a usage limit pauses it, any other error is counted and may fail the run."""
    try:
        status = runner.drive(_run_dir(s))
        memory.crashes.pop(s["run_id"], None)
        return status
    except UsageLimit as limit:
        memory.crashes.pop(s["run_id"], None)
        wait_out_limit(adapters, s, limit.result)
        return state.load(_run_dir(s))["status"]
    except Exception as err:  # noqa: BLE001 - the loop must keep going
        return _crashed(adapters, s, memory, err)


def watch_once(adapters, runner, memory: Memory | None = None) -> str | None:
    """One round: resume a limit pause, re-drive answered waiting runs, or drive the next run. Returns its id."""
    memory = memory or Memory()
    heartbeat.mark_progress()
    heartbeat.write(adapters.clock.now())
    states = all_states()
    for s in states:
        if s["status"] == "paused-limit":  # left over from before a restart: wait again
            if wait_out_limit(adapters, s, claude_mod.Result(kind="rate_limited")):
                drive_safely(adapters, runner, state.load(_run_dir(s)), memory)
            return s["run_id"]
    for s in states:
        if s["status"] != "waiting":
            continue
        if _has_answer(_run_dir(s)):
            drive_safely(adapters, runner, s, memory)
            return s["run_id"]
        if hasattr(runner, "check_waiting"):   # e.g. the delegate watchdog; never drives the run
            try:
                runner.check_waiting(_run_dir(s))
            except Exception:  # noqa: BLE001 - a watchdog problem must not stop the loop
                pass
    chosen = next_run(states)
    if chosen is None or (chosen["status"] == "queued" and hold.hold_requested()):
        return None   # an update holds the harness: no new run starts until it is done
    drive_safely(adapters, runner, chosen, memory)
    return chosen["run_id"]


def catch_up() -> list[str]:
    """Close the open questions of runs that already ended (left by older code); one event each, who = phoenix."""
    closed = []
    for s in all_states():
        if s["status"] in gates.ENDED:
            closed += gates.close_questions(_run_dir(s), f"run {s['status']}", who="phoenix")
    return closed


def watch_forever(adapters, runner, interval_s: float = INTERVAL_S) -> None:
    """Remove leftover containers and close questions of ended runs once, then run a round every interval_s seconds."""
    heartbeat.reset_progress()
    heartbeat.mark_progress()
    docker_mod.cleanup_orphans(adapters.docker)
    catch_up()
    stop = threading.Event()
    ticker = heartbeat.start_ticker(adapters.clock, stop=stop)    # beats while a container runs or the loop moves
    memory = Memory()
    try:
        while True:
            watch_once(adapters, runner, memory)
            adapters.clock.sleep(interval_s)
    finally:
        stop.set()
        ticker.join(1)
