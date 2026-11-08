"""What a project is doing now, decided in ONE place: current build, open questions, needs-you, active or idle.

Every reader uses this module: the API routes for projects, gates and runs, `phoenix gate list`,
`phoenix run status`, `phoenix project list` (harness column) and, through the API fields, the
dashboard (sidebar, Projects rows, Overview, header bell, tab badge, Current build card). Nothing
else may work these out again (docs/architecture.md section 8, "One truth").
"""
from __future__ import annotations

import time

from phoenix9 import gates, heartbeat, runs

ACTIVE = ("queued", "running", "waiting", "paused-limit")
ENDED = gates.ENDED


# ---------------------------------------------------------------------- one run as Alex should see it
def carrying_on(st: dict, open_ids) -> bool:
    """True when the run still says waiting but none of its questions is open any more (all answered)."""
    return st.get("status") == "waiting" and not any(g in open_ids for g in _run_gate_ids(st, open_ids))


def _run_gate_ids(st: dict, open_ids) -> list:
    """The open question ids that belong to this run (ids are '<run-id>.<n>')."""
    prefix = f"{st.get('run_id')}."
    return [g for g in open_ids if str(g).startswith(prefix)]


def seen_run(st: dict, open_ids) -> dict:
    """The run's state as Alex should see it: a waiting run whose questions are all answered shows as
    running (carrying_on); its waiting steps and tasks show as running too, marked `answered`. The
    runner still changes the real state later."""
    if not carrying_on(st, open_ids):
        return st
    mark = lambda x: {**x, "status": "running", "answered": True} if x.get("status") == "waiting" else x
    out = {**st, "status": "running", "carrying_on": True}
    if "steps" in st:
        out["steps"] = [mark(x) for x in st["steps"]]
    if "tasks" in st:
        out["tasks"] = {k: mark(v) for k, v in st["tasks"].items()}
    return out


# ---------------------------------------------------------------------- the current build of a project
def _task_number(r: dict) -> int | None:
    """The task the run is on: current.task, else (while running) the first one not passed yet."""
    task = (r.get("current") or {}).get("task")
    if task:
        return task
    if r["status"] == "running" and r.get("tasks_total") and r.get("tasks_passed", 0) < r["tasks_total"]:
        return r["tasks_passed"] + 1
    return None


def _pick(active: list, asking: set) -> dict | None:
    """The current build: the run that needs Alex, else running, paused, carrying on, queued (newest first in each)."""
    rank = {"running": 1, "paused-limit": 2, "waiting": 3, "queued": 4}
    if not active:
        return None
    return min(active, key=lambda r: (0 if r["run_id"] in asking else rank.get(r["status"], 9),
                                      -_order(active, r)))


def _order(found: list, r: dict) -> int:
    """Position from the oldest (runs.list_runs is newest first), so newer runs win ties."""
    return len(found) - found.index(r)


def _why(status: str, asking: bool, carrying: bool) -> str:
    if asking:
        return "It is waiting for your answer."
    if carrying:
        return "Your answer is in; Phoenix is carrying on."
    return {"running": "It is running.", "paused-limit": "It is paused until Claude's usage limit resets.",
            "queued": "It is queued and starts when the server is free.",
            "waiting": "It is waiting."}.get(status, "")


def _now_line(run: dict, step: str | None, asking: bool) -> str:
    if run.get("worker") == NOT_RESPONDING:
        return "Now: worker not responding. Phoenix's runner has not checked in for over 2 minutes."
    if run["carrying_on"]:
        return "Now: answered, Phoenix is carrying on."
    if asking and step:
        return f"Now: the {step} step is waiting for you."
    if asking:
        return "Now: waiting for you."
    if run["status"] == "running":
        return f"Now: working on task {run['task']} of {run['tasks']}." if run["task"] is not None else "Now: running."
    return f"Now: {run['status']}."


NOT_RESPONDING = "not responding"


def _worker(shown_status: str, now: float) -> str:
    """alive, or 'not responding' when the run says running and the runner's heartbeat is stale (heartbeat.STALE_S)."""
    return NOT_RESPONDING if shown_status == "running" and heartbeat.is_stale(now) else "alive"


def _run_view(r: dict, open_ids: set, now: float) -> dict:
    """The current build as the rows carry it: id, status (as seen), task, tasks, carrying_on, why, now, worker."""
    asking = bool(_run_gate_ids(r, open_ids))
    carrying = carrying_on(r, open_ids)
    shown = "running" if carrying else r["status"]
    run = {"run_id": r["run_id"], "status": shown, "task": _task_number({**r, "status": shown}),
           "tasks": r.get("tasks_total", 0), "carrying_on": carrying, "why": _why(r["status"], asking, carrying),
           "worker": _worker(shown, now)}
    if run["worker"] == NOT_RESPONDING:
        run["why"] = "It says running, but Phoenix's runner has not checked in for over 2 minutes."
    run["now"] = _now_line(run, (r.get("current") or {}).get("step"), asking)
    return run


# ---------------------------------------------------------------------- words
def _run_text(run: dict | None) -> str:
    """The Projects page words for the current build."""
    if not run:
        return "Idle"
    if run.get("worker") == NOT_RESPONDING:
        return "Worker not responding"
    return {"queued": "Queued", "waiting": "Waiting for you", "paused-limit": "Paused (usage limit)",
            "running": f"Running task {run['task']} of {run['tasks']}" if run["task"] is not None else "Running"
            }.get(run["status"], "Idle")


def _activity(needs: int, run: dict | None, last_failed: bool) -> str:
    """need (waiting on Alex), run, fail (paused, or the latest finished build failed) or idle."""
    if needs > 0:
        return "need"
    if run and (run["status"] == "paused-limit" or run.get("worker") == NOT_RESPONDING):
        return "fail"
    if run:
        return "run"
    return "fail" if last_failed else "idle"


def _status_line(activity: str, needs: int, run: dict | None, last_used: str) -> str:
    """One plain line for the sidebar."""
    if activity == "need":
        return f"{needs} questions waiting" if needs > 1 else "1 question waiting"
    if activity == "fail" and run and run.get("worker") == NOT_RESPONDING:
        return "Worker not responding"
    if activity == "fail":
        return "Paused at a limit" if run and run["status"] == "paused-limit" else "Last build failed"
    if activity == "run":
        if run["status"] == "queued":
            return "Build queued"
        return f"Building, task {run['task']} of {run['tasks']}" if run["task"] is not None else "Building"
    return f"Idle, used {last_used}" if last_used else "Idle"


# ---------------------------------------------------------------------- the one function
def project_state(name: str, *, all_runs: list | None = None, open_gates: list | None = None,
                  last_used: str = "", now: float | None = None) -> dict:
    """Everything about what project `name` is doing now, from its runs and open questions.

    `all_runs` (runs.list_runs, newest first) and `open_gates` (gates.list_gates) may be passed in when
    several projects are worked out at once, so the files are read only once. `now` (seconds since
    1970) is for tests; the heartbeat age is measured against it."""
    now = time.time() if now is None else now
    found = [r for r in (runs.list_runs(name) if all_runs is None else all_runs) if r["project"] == name]
    questions = [g for g in (gates.list_gates(name) if open_gates is None else open_gates) if g["project"] == name]
    open_ids = {g["id"] for g in questions}
    asking = {g["run"] for g in questions}
    current = _pick([r for r in found if r["status"] in ACTIVE], asking)
    run = _run_view(current, open_ids, now) if current else None
    finished = [r for r in found if r["status"] in ENDED]
    last_failed = bool(finished) and finished[0]["status"] == "failed"
    activity = _activity(len(questions), run, last_failed)
    run_text = _run_text(run)
    return {"needs_you": len(questions), "questions": [g["id"] for g in questions], "run": run,
            "last_build_failed": last_failed, "activity": activity,
            "status_line": _status_line(activity, len(questions), run, last_used),
            "run_text": run_text, "harness": "needs you" if activity == "need" else run_text.lower(),
            "worker": run["worker"] if run else "alive"}


def all_project_states(names: list, last_used: dict | None = None) -> dict:
    """project_state for many projects at once (runs and gates read once)."""
    all_runs, open_gates = runs.list_runs(), gates.list_gates()
    return {n: project_state(n, all_runs=all_runs, open_gates=open_gates, last_used=(last_used or {}).get(n, ""))
            for n in names}


def run_view(st: dict, open_ids: set, now: float | None = None) -> dict:
    """One run as the rows carry it (id, status as seen, task, why, now, worker), from its state and open question ids."""
    summary = {**st, "tasks_total": len(st.get("tasks") or {}),
               "tasks_passed": sum(1 for t in (st.get("tasks") or {}).values() if t.get("status") == "passed")}
    return _run_view(summary, open_ids, time.time() if now is None else now)
