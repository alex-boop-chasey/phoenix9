"""How a run ends: the run lock, the stop request, and the ONE end function every way of ending uses.

- The runner holds the run lock (`run.lock` in the run folder) for as long as it walks a run
  (`Runner.drive`). Anyone else who wants to end a run takes the same lock first; when they cannot get
  it, the runner is walking the run and they leave a stop request instead (`stop-request.json`), which
  the runner reads between steps, before opening a gate and before finishing (`check`).
- `end_run` is the only place a run becomes done, failed or stopped. Its FIRST state update marks
  unfinished tasks and step lines skipped, clears current.gate and writes the final status, all at once;
  then open questions are closed. Only after that does the slow work run: after-stop steps (stop only, they
  add their own step lines), branch discard (stop only), run.finished and the summary refresh. So a reader
  (the service loop's check_waiting, adopt_gate, the dashboard) never sees a half-ended run as waiting.
  Apart from those after-stop step lines, an ended run is never changed again.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from phoenix9 import atomic, events, gates, pause, runs as runs_mod, scrub, state, summary

ENDED = ("done", "failed", "stopped")
TASK_FINAL = ("passed", "failed", "skipped")
LOCK_WAIT_S = 10.0
NOTES = {"stopped": "the run was stopped", "failed": "the run failed", "done": "the run ended"}


RUN_GROUPS = ("run-start", "run-finish")
REASON_MAX = 160


def _first_line(text) -> str:
    """The first non-empty line of some text, trimmed."""
    return next((x.strip() for x in str(text or "").splitlines() if x.strip()), "")


def failed_step(st: dict, title_of: Callable[[str], str]) -> dict | None:
    """The first failed run-start or run-finish step of a run as {step, title, reason, text, error}, or None.

    `text` is the line Alex sees ("Failed at: Full suite: 2 tests failed"); `error` is the run's
    recorded reason ("Full suite failed: 2 tests failed"). Both are scrubbed."""
    line = next((x for x in st.get("steps") or []
                 if x.get("status") == "failed" and x.get("group") in RUN_GROUPS and x.get("task") is None), None)
    if line is None:
        return None
    name = line.get("step") or ""
    title = title_of(name) or name
    reason = _first_line(scrub.scrub(line.get("note") or "")).removeprefix("The checks did not pass:").strip()
    if len(reason) > REASON_MAX:
        reason = reason[:REASON_MAX - 3].rstrip() + "..."
    return {"step": name, "title": title, "reason": reason,
            "text": f"Failed at: {title}: {reason}" if reason else f"Failed at: {title}",
            "error": f"{title} failed: {reason}" if reason else f"{title} failed"}


def mark_failed_step(s: dict, found: dict | None) -> None:
    """Write (or, with None, clear) the failed step fields of a run's state: failed_step, failed_at, error."""
    s.pop("failed_step", None)
    s.pop("failed_at", None)
    if found is None:
        return
    s["failed_step"] = found["step"]
    s["failed_at"] = {k: found[k] for k in ("step", "title", "reason", "text")}
    s["error"] = found["error"]


class StopRequested(Exception):
    """Someone asked for the run to stop; the runner ends it cleanly at this boundary."""

    def __init__(self, who: str = "cli"):
        super().__init__(f"stop requested by {who}")
        self.who = who


class RunEnded(Exception):
    """The run already ended (done, failed or stopped) while the runner was walking it; leave it as it is."""

    def __init__(self, status: str):
        super().__init__(f"the run is already {status}")
        self.status = status


def lock(run_dir, wait: float = LOCK_WAIT_S) -> state.Lock:
    """The run lock: held by the runner while it walks the run, and by anyone ending it from outside."""
    return state.Lock(Path(run_dir) / "run.lock", wait=wait)


def _request_file(run_dir) -> Path:
    return Path(run_dir) / "stop-request.json"


def request_stop(run_dir, who: str) -> dict:
    """Leave a stop request for the runner (it is walking the run, so it ends it itself at the next boundary)."""
    data = {"who": who, "at": state.now()}
    atomic.write_json(_request_file(run_dir), data)
    return data


def stop_requested(run_dir) -> dict | None:
    """The stop request of this run, or None."""
    return atomic.read_json(_request_file(run_dir))


def check(run_dir) -> None:
    """A boundary: raise RunEnded when the run already ended, StopRequested when a stop was asked for."""
    st = state.load(Path(run_dir)) or {}
    if st.get("status") in ENDED:
        raise RunEnded(st["status"])
    asked = stop_requested(run_dir)
    if asked is not None:
        raise StopRequested(asked.get("who") or "cli")


def end_run(run_dir, status: str, *, reason: str = "", who: str = "phoenix", adapters=None,
            after_stop: Callable[[], None] | None = None, lib_root=None,
            failed_at: dict | None = None) -> dict:
    """End the run as `status` (done | failed | stopped) the one clean way; returns {status, notes}.

    `failed_at` (from failed_step) names the run-start or run-finish step a failed run failed at.

    The caller holds the run lock (the runner while walking, or a stop from outside). A run that already
    ended is left exactly as it is."""
    if status not in ENDED:
        raise ValueError(f"a run cannot end as {status!r}")
    run_dir = Path(run_dir)
    st = state.load(run_dir)
    if st["status"] in ENDED:
        return {"status": st["status"], "notes": []}
    note = NOTES[status]

    def tidy(s):
        for t in s["tasks"].values():
            if t["status"] not in TASK_FINAL:
                t.update(status="skipped", gate=None, note=t.get("note") or note)
        for line in s["steps"]:
            if line["status"] in ("waiting", "running", "pending"):
                line.update(status="skipped", finished=line.get("finished") or state.now())
        s.setdefault("current", {})["gate"] = None
        s["status"] = status            # final in the SAME update: no reader ever sees a tidied run still waiting
        if status == "failed" and reason:
            s["error"] = reason
        if status == "failed" and failed_at is not None:
            mark_failed_step(s, failed_at)
    state.update(run_dir, tidy)
    gates.close_questions(run_dir, f"run {status}", who=who)   # before the slow work: nothing is left to adopt
    pause.drop_stale(run_dir, st["project"], st["run_id"], f"run {status}")   # an ended run never pauses
    if status == "stopped" and after_stop is not None:
        after_stop()
    notes = runs_mod.discard_branch(adapters, st["project"], st["run_id"]) \
        if status == "stopped" and adapters is not None else []
    _request_file(run_dir).unlink(missing_ok=True)
    words = "; ".join(x for x in (reason or (failed_at or {}).get("error", ""), *notes) if x)
    data = {"reason": words} if words else {}
    if who != "phoenix":
        data["who"] = who
    events.emit("run.finished", project=st["project"], run=st["run_id"], status=status, **data)
    summary.refresh(run_dir, lib_root)    # a summary written mid-run gets its final status
    return {"status": status, "notes": notes}
