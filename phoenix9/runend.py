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

from phoenix9 import atomic, events, gates, runs as runs_mod, state, summary

ENDED = ("done", "failed", "stopped")
TASK_FINAL = ("passed", "failed", "skipped")
LOCK_WAIT_S = 10.0
NOTES = {"stopped": "the run was stopped", "failed": "the run failed", "done": "the run ended"}


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
            after_stop: Callable[[], None] | None = None, lib_root=None) -> dict:
    """End the run as `status` (done | failed | stopped) the one clean way; returns {status, notes}.

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
    state.update(run_dir, tidy)
    gates.close_questions(run_dir, f"run {status}", who=who)   # before the slow work: nothing is left to adopt
    if status == "stopped" and after_stop is not None:
        after_stop()
    notes = runs_mod.discard_branch(adapters, st["project"], st["run_id"]) \
        if status == "stopped" and adapters is not None else []
    _request_file(run_dir).unlink(missing_ok=True)
    words = "; ".join(x for x in (reason, *notes) if x)
    data = {"reason": words} if words else {}
    if who != "phoenix":
        data["who"] = who
    events.emit("run.finished", project=st["project"], run=st["run_id"], status=status, **data)
    summary.refresh(run_dir, lib_root)    # a summary written mid-run gets its final status
    return {"status": status, "notes": notes}
