"""The runner service loop: picks the next run, drives it, counts crashes and waits out usage limits."""
# ported from reference/v8/phoenix/watch.py (crash counting, limit_notice, drive_safely)
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from phoenix9 import atomic, docker as docker_mod, events, gates, hold, paths, state
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
    """Mark a run failed with the error in its state, tell the event stream and Alex."""
    run_dir = _run_dir(s)

    def change(st):
        st["status"] = "failed"
        st["error"] = reason
    state.update(run_dir, change)
    events.emit("run.finished", project=s["project"], run=s["run_id"], status="failed", reason=reason)
    adapters.notify.send(f"Phoenix run {s['run_id']} failed: {reason}")
    return "failed"


def _now(adapters) -> datetime:
    return datetime.fromtimestamp(adapters.clock.now(), timezone.utc)


def wait_out_limit(adapters, s: dict, result) -> bool:
    """Pause the run, wait for Claude to answer again (telling Alex once if over an hour); True = resume."""
    run_dir = _run_dir(s)
    state.set_status(run_dir, "paused-limit")
    waited, told = [0.0], [False]

    def sleep(seconds):
        waited[0] += seconds
        if waited[0] > LIMIT_NOTICE_S and not told[0]:
            told[0] = True
            when = result.resets_at.isoformat() if result.resets_at else "unknown"
            adapters.notify.send(f"Phoenix run {s['run_id']} is waiting more than an hour for Claude's "
                                 f"usage limit (resets at {when}).")
        adapters.clock.sleep(seconds)

    ok = claude_mod.wait_for_limit(result, adapters.claude.probe, lambda: _now(adapters), sleep)
    if not ok:
        _fail(adapters, s, "Claude's usage limit did not clear in time.")
        return False
    state.set_status(run_dir, "running")
    return True


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


def watch_forever(adapters, runner, interval_s: float = INTERVAL_S) -> None:
    """Remove leftover containers once, then run a round every interval_s seconds, forever."""
    docker_mod.cleanup_orphans(adapters.docker)
    memory = Memory()
    while True:
        watch_once(adapters, runner, memory)
        adapters.clock.sleep(interval_s)
