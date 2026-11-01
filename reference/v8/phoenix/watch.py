"""`phoenix watch`: pick up plans, run them one at a time, notice merged pull requests.

Every 30 seconds one round (`watch_once`):
1. Every `plans/*.md` is moved into a new run folder (`1-concept/plan.md`)
   and checked (first renamed into `plans/.taken/`, then copied, because
   plans/ and runs/ are separate Docker volumes on the VPS). A bad plan gets `ERROR.txt`, status `failed` and a
   notification; a good one becomes a `queued` run.
2. A run whose step loop ended but which was never finished (Phoenix was
   stopped in between) is finished now.
3. `done` runs with a pull request are checked for merged / closed.
4. One run is taken forward: a `running` (or `paused`) run is resumed
   first; otherwise the oldest `queued` run is started. The round only
   ends when that run has finished, so there is never more than one.
"""
from __future__ import annotations

import dataclasses
import hashlib
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from phoenix import config, loop, runs
from phoenix import plan as pplan
from phoenix import run as prun
from phoenix.log import log
from phoenix.state import Lock, atomic_write

INTERVAL_S = 30
TAKEN = ".taken"                         # plans/.taken/<run-id>--<name>.md: claimed, not yet in its run folder
TAKEN_RE = re.compile(r"\d{8}-\d{4}-[a-z]{4}--.+\.md")
LIMIT_NOTICE_S = 3600                    # tell the owner when a usage-limit wait is longer than this
MAX_CRASHES = 3                          # a run that crashes the loop this many times in a row is failed
RESUMABLE = ("running", "paused")


@dataclass
class Watcher:
    """The outside pieces one watch round uses, and what it remembers between rounds. Tests swap the pieces."""

    hands: prun.Hands = field(default_factory=prun.Hands)
    loop_tools: loop.Tools = field(default_factory=loop.Tools)
    start_run: Callable = prun.start_run
    run_plan: Callable = loop.run_plan
    finish_run: Callable = prun.finish_run
    check_merged: Callable = prun.check_merged
    notify: Callable | None = None                   # None = run.notify with the settings
    crashes: dict = field(default_factory=dict)      # run id -> crashes in a row


def _notify(w: Watcher, s: dict) -> Callable[[str], None]:
    """The notify function to use (the fake one in tests)."""
    return w.notify or (lambda text: prun.notify(text, s))


# ------------------------------------------------------------- 1. new plans
def new_plans() -> list[Path]:
    """The plan files waiting in plans/, oldest first."""
    folder = config.paths().plans
    if not folder.is_dir():
        return []
    files = [p for p in folder.glob("*.md") if p.is_file() and not p.is_symlink()]
    return sorted(files, key=lambda p: (p.stat().st_mtime, p.name))


def error_text(source: str, problems: list[str]) -> str:
    """ERROR.txt for a plan Phoenix will not run, in plain English."""
    lines = [f"Phoenix did not start the plan '{source}' because it has {len(problems)} problem(s):", ""]
    lines += [f"- {p}" for p in problems]
    lines += ["", "Nothing was built. Fix the plan and put it in the plans folder again."]
    return "\n".join(lines) + "\n"


def take_plan(path: Path, w: Watcher, s: dict) -> str:
    """Move one plan file into a new run folder and check it. Returns the run id.

    The file is first renamed into plans/.taken/ (same folder tree, so the
    rename is atomic), so it is picked up only once. It is then copied into
    the run folder and the claimed copy deleted: plans/ and runs/ may be on
    different disks (Docker volumes), where a rename is not possible.
    """
    run_id = runs.new_run_id()
    claimed = config.paths().plans / TAKEN / f"{run_id}--{path.name}"
    claimed.parent.mkdir(parents=True, exist_ok=True)
    os.replace(path, claimed)
    return check_taken(claimed, w, s)


def move_into_run(claimed: Path, dest: Path) -> None:
    """Copy a claimed plan into its run folder (all or nothing), then delete the claimed file."""
    if not dest.exists():
        tmp = dest.with_name(f".{dest.name}.tmp.{os.getpid()}")
        tmp.write_bytes(claimed.read_bytes())
        os.replace(tmp, dest)
    claimed.unlink()


def check_taken(claimed: Path, w: Watcher, s: dict) -> str:
    """Finish taking a claimed plan (plans/.taken/<run-id>--<name>.md): move it and check it."""
    run_id, _, source = claimed.name.partition("--")
    dest = runs.run_dir(run_id) / "1-concept" / "plan.md"
    move_into_run(claimed, dest)
    log(run_id, f"picked up plan {source}")
    data = dest.read_bytes()
    try:
        parsed = pplan.parse(data.decode("utf-8"))
        problems = pplan.check(parsed)
    except UnicodeDecodeError:
        parsed, problems = pplan.Plan(), ["The file is not plain UTF-8 text."]
    prun.note_run(run_id, plan_path=str(dest), plan_name=parsed.name, repo=parsed.repo,
                  plan_sha=hashlib.sha256(data).hexdigest(), source_name=source, picked_up=time.time())
    if problems:
        atomic_write(runs.run_dir(run_id) / "ERROR.txt", error_text(source, problems))
        prun.note_run(run_id, status="failed", reason="plan rejected: see ERROR.txt", finished_at=runs.now_iso())
        log(run_id, f"plan rejected ({len(problems)} problem(s)); see ERROR.txt")
        _notify(w, s)(f"Phoenix rejected the plan '{source}' (run {run_id}): "
                      f"{len(problems)} problem(s). First: {problems[0]}")
    else:
        prun.note_run(run_id, status="queued")
        log(run_id, f"queued: '{parsed.name}' on {parsed.repo}, {len(parsed.steps)} steps")
    return run_id


def left_taken() -> list[Path]:
    """Plans claimed in an earlier round whose move was cut off (Phoenix stopped in between)."""
    folder = config.paths().plans / TAKEN
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if TAKEN_RE.fullmatch(p.name)
                  and p.is_file() and not p.is_symlink())


def pick_up_plans(w: Watcher, s: dict) -> list[str]:
    """Turn every plan in plans/ into a run (queued, or failed with ERROR.txt). Returns the run ids."""
    ids = [check_taken(claimed, w, s) for claimed in left_taken()]
    for path in new_plans():
        try:
            ids.append(take_plan(path, w, s))
        except FileNotFoundError:
            continue                                  # gone already (picked up elsewhere)
    return ids


# ------------------------------------------------------------- the run list
def all_runs() -> list[dict]:
    """Every run.json record, oldest first (by start time, then pick-up order, then id)."""
    folder = config.paths().runs
    if not folder.is_dir():
        return []
    records = [runs.load_run(p.name) for p in folder.iterdir() if (p / "run.json").is_file()]
    return sorted(records, key=lambda r: (r.get("started_at", ""), r.get("picked_up") or 0, r.get("run_id", "")))


def unfinished(record: dict) -> bool:
    """True when the step loop ended (done or failed) but finish_run never completed."""
    return record.get("status") in ("done", "failed") and not record.get("finished_at") \
        and bool(record.get("base_sha"))


def next_run(records: list[dict]) -> dict | None:
    """The run to take forward now: a running/paused one first, else the oldest queued one."""
    for status in (("running",), ("paused",), ("queued",)):
        for r in records:
            if r.get("status") in status and r.get("repo") and r.get("plan_path"):
                return r
    return None


# ------------------------------------------------------------- usage-limit notice
def limit_notice(run_id: str, wait: Callable, notify_fn: Callable[[str], None]) -> Callable:
    """Wrap loop's wait_for_limit so the owner hears about a usage-limit wait longer than an hour (once per wait)."""
    def wrapped(result, probe, now, sleep, **kw):
        waited, told = [0.0], [False]

        def counting_sleep(seconds):
            waited[0] += seconds
            if waited[0] > LIMIT_NOTICE_S and not told[0]:
                told[0] = True
                notify_fn(f"Phoenix run {run_id} is waiting more than an hour for Claude's usage limit "
                          f"(resets at {getattr(result, 'resets_at', None) or 'unknown'}).")
            sleep(seconds)

        return wait(result, probe, now, counting_sleep, **kw)
    return wrapped


# ------------------------------------------------------------- 4. one run
def drive(record: dict, w: Watcher, s: dict) -> str:
    """Take one run forward until it is finished or paused. Returns its status."""
    run_id = record["run_id"]
    with Lock(runs.run_dir(run_id) / "loop.lock"):
        if record.get("status") == "queued":
            if w.start_run(run_id, hands=w.hands, settings=s) != "ready":
                return runs.load_run(run_id).get("status", "failed")
        tools = dataclasses.replace(w.loop_tools, wait_for_limit=limit_notice(
            run_id, w.loop_tools.wait_for_limit, _notify(w, s)))
        status = w.run_plan(run_id, tools=tools, settings=s)
        if status in ("done", "failed"):
            status = w.finish_run(run_id, hands=w.hands, settings=s)
        return status


def drive_safely(record: dict, w: Watcher, s: dict) -> str:
    """drive(), but an unexpected error is logged instead of stopping `phoenix watch`.

    The run stays as it was (so it is resumed next round); after
    MAX_CRASHES in a row it is marked failed.
    """
    run_id = record["run_id"]
    try:
        status = drive(record, w, s)
        w.crashes.pop(run_id, None)
        return status
    except Exception as e:                            # noqa: BLE001 - the watcher must keep going
        n = w.crashes.get(run_id, 0) + 1
        w.crashes[run_id] = n
        log(run_id, f"the run stopped with an error ({n} in a row): {type(e).__name__}: {e}")
        if n >= MAX_CRASHES:
            w.crashes.pop(run_id, None)
            return prun.fail_run(run_id, f"Phoenix hit an error {n} times in a row: {type(e).__name__}: {e}",
                                 dataclasses.replace(w.hands, notify=_notify(w, s)), s)
        return runs.load_run(run_id).get("status", "")


# ------------------------------------------------------------- one round, and forever
def watch_once(w: Watcher | None = None, settings: dict | None = None) -> str | None:
    """One watch round. Returns the id of the run it took forward, or None."""
    w = w or Watcher()
    s = settings or config.load()
    pick_up_plans(w, s)
    for record in all_runs():
        if unfinished(record):
            drive_finish(record, w, s)
    for record in all_runs():
        if record.get("status") == "done" and record.get("pr_url"):
            try:
                w.check_merged(record["run_id"], hands=w.hands)
            except Exception as e:                    # noqa: BLE001 - one bad check must not stop the round
                log(record["run_id"], f"merge check failed: {type(e).__name__}: {e}")
    record = next_run(all_runs())
    if record is None or busy(record["run_id"]):
        return None
    drive_safely(record, w, s)
    return record["run_id"]


def busy(run_id: str) -> bool:
    """True when someone else (a `phoenix run <id>` by hand) holds the run's loop lock right now."""
    return Lock.held(runs.run_dir(run_id) / "loop.lock")


def drive_finish(record: dict, w: Watcher, s: dict) -> None:
    """Finish a run whose step loop ended while Phoenix was stopped.

    After MAX_CRASHES failed tries in a row it is marked finished anyway, so
    it is not retried forever.
    """
    run_id = record["run_id"]
    if busy(run_id):
        return
    try:
        with Lock(runs.run_dir(run_id) / "loop.lock"):
            w.finish_run(run_id, hands=w.hands, settings=s)
        w.crashes.pop(run_id, None)
    except Exception as e:                            # noqa: BLE001 - the watcher must keep going
        n = w.crashes.get(run_id, 0) + 1
        w.crashes[run_id] = n
        log(run_id, f"finishing the run failed ({n} in a row): {type(e).__name__}: {e}")
        if n >= MAX_CRASHES:
            w.crashes.pop(run_id, None)
            prun.note_run(run_id, finished_at=runs.now_iso(),
                          reason=f"Phoenix could not finish the run: {type(e).__name__}: {e}")
            _notify(w, s)(f"Phoenix could not finish run {run_id}: {type(e).__name__}: {e}")


def watch_forever(w: Watcher | None = None, interval_s: float = INTERVAL_S, sleep: Callable = time.sleep) -> None:
    """Run watch rounds forever, one every `interval_s` seconds. Only one watcher may run at a time."""
    w = w or Watcher()
    with Lock(config.paths().home / "watch.lock"):
        while True:
            config.paths().create()
            watch_once(w, config.load())
            sleep(interval_s)
