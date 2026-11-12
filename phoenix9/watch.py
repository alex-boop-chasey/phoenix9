"""The runner service loop: picks the next run, drives it, counts crashes and waits out usage limits."""
# ported from reference/v8/phoenix/watch.py (crash counting, limit_notice, drive_safely)
from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from phoenix9 import agentwatch, atomic, docker as docker_mod, edits, gates, heartbeat, hold, paths, runend, state
from phoenix9 import claude as claude_mod
from phoenix9 import plansession, project_delete, projectchat, settings
from phoenix9.stepctx import UsageLimit

MAX_CRASHES = 3          # a run that crashes the loop this many times in a row is failed
LIMIT_NOTICE_S = 3600    # tell Alex when a usage-limit wait is longer than this
INTERVAL_S = 10
REPORT_EVERY_S = 600     # the status report is rewritten every 10 minutes


@dataclass
class Memory:
    """What the loop remembers between rounds: crashes in a row per run."""

    crashes: dict = field(default_factory=dict)
    agent_checked: float | None = None    # when the agent watchdog last ran
    chats_checked: float | None = None    # when the chats were last checked for sleep/off
    report_written: float | None = None   # when the status report was last written
    daily_checked: float | None = None    # when the daily report was last looked at
    allowance_checked: float | None = None   # when the allowance was last read


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


AGENT_CHECK_S = 60


def check_agent(adapters, memory: Memory) -> None:
    """Run the agent watchdog about every minute; a problem there never stops the loop."""
    now = adapters.clock.now()
    if memory.agent_checked is not None and now - memory.agent_checked < AGENT_CHECK_S:
        return
    memory.agent_checked = now
    try:
        agentwatch.check_once(adapters)
    except Exception:  # noqa: BLE001 - the watchdog must not stop the loop
        pass


CHAT_CHECK_S = 600
BUSY_RUN_STATUSES = ("queued", "running", "waiting", "paused-limit", "paused")


def _chat_action(project: str, info: dict, now: float, cfg: dict) -> str | None:
    """Which action ("sleep" or "off") an idle chat is due for, or None."""
    last = info.get("last_active")
    if last is None:
        return None
    idle = now - last
    if info["state"] == "live" and idle >= cfg["sleep_after_minutes"] * 60:
        return "sleep"
    if info["state"] == "sleeping" and idle >= cfg["off_after_days"] * 86400:
        return "off"
    return None


def _check_chat(project: str, adapters, now: float, cfg: dict) -> None:
    """Put one project's chat to sleep or off if it is idle long enough, and record the command."""
    from phoenix9.ops import common
    action = _chat_action(project, projectchat.state(project, adapters), now, cfg)
    if action == "sleep":
        projectchat.sleep(project, adapters, who="runner")
    elif action == "off":
        projectchat.off(project, adapters, who="runner")
    else:
        return
    common.record_command("runner", f"chat {action} {project}", project)


def check_chats(adapters, memory: Memory) -> None:
    """About every 10 minutes put idle live chats to sleep and old sleeping chats off; never raises."""
    try:
        now = adapters.clock.now()
        if memory.chats_checked is not None and now - memory.chats_checked < CHAT_CHECK_S:
            return
        memory.chats_checked = now
        from phoenix9 import project as project_mod
        cfg = settings.chat_settings()
        busy = {s["project"] for s in all_states() if s.get("status") in BUSY_RUN_STATUSES}
        for name in project_mod.project_names():
            if name == "home" or name in busy or projectchat.read_chat_doc(name)[0] is None:
                continue
            try:
                _check_chat(name, adapters, now, cfg)
            except Exception:  # noqa: BLE001 - one project must not stop the others
                continue
    except Exception:  # noqa: BLE001 - chat upkeep must not stop the loop
        pass


def catch_up() -> list[str]:
    """Close the open questions of runs that already ended (left by older code); one event each, who = phoenix."""
    closed = []
    for s in all_states():
        if s["status"] in gates.ENDED:
            closed += gates.close_questions(_run_dir(s), f"run {s['status']}", who="phoenix")
    return closed


def mark_stalled_edits() -> None:
    """Mark quick edits with no activity for 30 minutes as stalled; never raises."""
    try:
        edits.mark_stalled()
    except Exception as err:  # noqa: BLE001 - a bad edit record must not stop the runner
        print(f"phoenix runner: could not check quick edits: {type(err).__name__}: {err}", file=sys.stderr, flush=True)


def prune_deleted_copies(adapters) -> None:
    """Remove old safety copies of deleted projects; never raises (a problem is one log line, the loop goes on)."""
    try:
        project_delete.prune_backups(adapters, adapters.clock.now())
    except Exception as err:  # noqa: BLE001 - cleaning up old copies must not stop the runner
        print(f"phoenix runner: could not prune old deleted-project copies: {type(err).__name__}: {err}",
              file=sys.stderr, flush=True)


def run_plans(adapters) -> str | None:
    """Run the oldest queued planning session (in a step container, between runs); never raises."""
    try:
        return plansession.run_next(adapters)
    except Exception as err:  # noqa: BLE001 - a bad plan record must not stop the runner
        print(f"phoenix runner: could not run a planning session: {type(err).__name__}: {err}", file=sys.stderr, flush=True)
        return None


def write_status_report(adapters, memory: Memory) -> None:
    """Rewrite HOME/reports/status.md when 10 minutes have passed; a failure never stops the loop."""
    now = adapters.clock.now()
    if memory.report_written is not None and now - memory.report_written < REPORT_EVERY_S:
        return
    memory.report_written = now
    try:
        from phoenix9 import statusreport
        statusreport.write(adapters, now=now)
    except Exception:  # noqa: BLE001 - the report is a view; the runner carries on without it
        pass


DAILY_CHECK_S = 60
ALLOWANCE_CHECK_S = 300
ALLOWANCE_TELL = {"low": "Phoenix: the agent's allowance is {words}.",
                  "used_up": "Phoenix: the agent's allowance is {words}."}


def check_daily_report(adapters, memory: Memory) -> None:
    """Send the daily report when it is due, looking at most once a minute; never raises."""
    try:
        now = adapters.clock.now()
        if memory.daily_checked is not None and now - memory.daily_checked < DAILY_CHECK_S:
            return
        memory.daily_checked = now
        from phoenix9 import dailyreport
        dailyreport.send_if_due(adapters)
    except Exception:  # noqa: BLE001 - the report must not stop the loop
        pass


def check_allowance(adapters, memory: Memory) -> None:
    """Tell Alex once per month when the allowance gets low and once when it is used up; never raises."""
    try:
        now = adapters.clock.now()
        if memory.allowance_checked is not None and now - memory.allowance_checked < ALLOWANCE_CHECK_S:
            return
        memory.allowance_checked = now
        from phoenix9 import allowance
        got = allowance.read(adapters)
        if got["state"] not in ALLOWANCE_TELL:
            return
        month = datetime.fromtimestamp(now, ZoneInfo(settings.report_settings()["timezone"])).strftime("%Y-%m")
        file = paths.home() / "reports" / "allowance-state.json"
        told = atomic.read_json(file, {}) or {}
        told = told if told.get("month") == month else {"month": month}
        if told.get(got["state"]):
            return
        adapters.notify.send(ALLOWANCE_TELL[got["state"]].format(words=got["words"]))
        told[got["state"]] = True
        if got["state"] == "used_up":
            told["low"] = True
        atomic.write_json(file, told)
    except Exception:  # noqa: BLE001 - the allowance check must not stop the loop
        pass


def watch_forever(adapters, runner, interval_s: float = INTERVAL_S) -> None:
    """Remove leftover containers and close questions of ended runs once, then run a round every interval_s seconds."""
    heartbeat.reset_progress()
    heartbeat.mark_progress()
    docker_mod.cleanup_orphans(adapters.docker)
    catch_up()
    try:
        plansession.requeue_stale()          # their containers were just removed: run them again
    except Exception:  # noqa: BLE001 - a bad plan record must not stop the runner
        pass
    stop = threading.Event()
    ticker = heartbeat.start_ticker(adapters.clock, stop=stop)    # beats while a container runs or the loop moves
    memory = Memory()
    try:
        while True:
            watch_once(adapters, runner, memory)
            run_plans(adapters)                  # between runs: one planning session at a time
            check_agent(adapters, memory)
            check_chats(adapters, memory)
            prune_deleted_copies(adapters)
            mark_stalled_edits()
            write_status_report(adapters, memory)
            check_daily_report(adapters, memory)
            check_allowance(adapters, memory)
            adapters.clock.sleep(interval_s)
    finally:
        stop.set()
        ticker.join(1)
