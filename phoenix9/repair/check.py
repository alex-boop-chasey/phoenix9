"""The repair check, part 1: does a run's recorded state agree with itself (statuses, tries, steps, questions)?"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from phoenix9 import atomic, gates, state, status

ENDED_TASK_OK = {"done": ("passed", "skipped"), "failed": gates.TASK_ENDED, "stopped": gates.TASK_ENDED}


@dataclass
class Finding:
    """One thing wrong in a run: a short code, plain words, the task it concerns and a hint for the fix."""
    code: str
    text: str
    task: int | None = None
    fix: dict = field(default_factory=dict)


def _tasks(st: dict):
    """The run's tasks as (number, task) pairs in number order."""
    return sorted(((int(n), t) for n, t in (st.get("tasks") or {}).items()), key=lambda x: x[0])


def check_statuses(run_dir: Path, st: dict) -> list[Finding]:
    """Run, task and step statuses must be known words."""
    return [Finding("bad-status", problem.capitalize() + ".", fix={"kind": "set-status"})
            for problem in state.status_problems(st)]


def _ended_mismatches(st: dict) -> list[Finding]:
    """An ended run must have no task or step line still going and no gate it waits on."""
    found = []
    allowed = ENDED_TASK_OK.get(st["status"], ())
    for n, t in _tasks(st):
        if t["status"] not in allowed:
            found.append(Finding("task-not-final", f"The run is {st['status']} but task {n} is still {t['status']}.",
                                 task=n, fix={"kind": "task-status", "task": n}))
    for i, x in enumerate(st.get("steps") or []):
        if x["status"] in ("pending", "running", "waiting"):
            found.append(Finding("step-not-final", f"The run is {st['status']} but step {x.get('step')} is still {x['status']}.",
                                 task=x.get("task"), fix={"kind": "step-line", "line": i}))
    if (st.get("current") or {}).get("gate"):
        found.append(Finding("ended-holds-gate", f"The run is {st['status']} but still points at question "
                             f"{st['current']['gate']}.", fix={"kind": "clear-gate"}))
    return found


def _live_mismatches(st: dict) -> list[Finding]:
    """A run that is not ended: waiting tasks and steps need a waiting run; running ones need a started run."""
    found, run = [], st["status"]
    for n, t in _tasks(st):
        if t["status"] == "waiting" and run != "waiting":
            found.append(Finding("task-waiting-run-not", f"Task {n} is waiting for a question but the run is {run}.",
                                 task=n, fix={"kind": "task-status", "task": n}))
        if t["status"] == "running" and run == "queued":
            found.append(Finding("task-running-run-queued", f"Task {n} is running but the run is only queued.",
                                 task=n, fix={"kind": "task-status", "task": n}))
    for i, x in enumerate(st.get("steps") or []):
        if x["status"] == "waiting" and run != "waiting":
            found.append(Finding("step-waiting-run-not", f"Step {x.get('step')} is waiting for a question but the "
                                 f"run is {run}.", task=x.get("task"), fix={"kind": "step-line", "line": i}))
        if x["status"] == "running" and run == "queued":
            found.append(Finding("step-running-run-queued", f"Step {x.get('step')} is running but the run is only "
                                 "queued.", task=x.get("task"), fix={"kind": "step-line", "line": i}))
    return found


def check_agreement(run_dir: Path, st: dict) -> list[Finding]:
    """The run status agrees with its tasks, step lines and current.gate."""
    if st.get("status") in gates.ENDED:
        return _ended_mismatches(st)
    return _live_mismatches(st) if st.get("status") in status.ACTIVE else []


def _attempt_numbers(run_dir: Path, n: int) -> list[int]:
    """The attempt folder numbers of task n, in order."""
    base = Path(run_dir) / "tasks" / str(n)
    if not base.is_dir():
        return []
    return sorted(int(m.group(1)) for p in base.iterdir() if p.is_dir() and (m := re.fullmatch(r"attempt-(\d+)", p.name)))


def _attempt_findings(run_dir: Path, n: int, tries: int, have: list[int]) -> list[Finding]:
    """Attempt folders must be 1..tries (the newest may be missing: tries moves one ahead of the folder)."""
    if have in (list(range(1, tries + 1)), list(range(1, tries))):
        return []
    return [Finding("tries-mismatch", f"Task {n} says it is on try {tries} but its attempt folders are "
                    f"{have or 'missing'}.", task=n, fix={"kind": "tries", "task": n, "folders": have})]


def _result_findings(run_dir: Path, n: int, tries: int, have: list[int]) -> list[Finding]:
    """Every attempt below `tries` must have a readable result.json that names its own attempt."""
    found = []
    for k in (k for k in have if k < tries):
        result = atomic.read_json(Path(run_dir) / "tasks" / str(n) / f"attempt-{k}" / "result.json")
        if not isinstance(result, dict):
            found.append(Finding("attempt-no-result", f"Task {n} attempt {k} is over but has no result.json.",
                                 task=n, fix={"kind": "attempt-result", "task": n, "attempt": k}))
        elif result.get("attempt", k) != k:
            found.append(Finding("attempt-wrong-result", f"Task {n} attempt {k} has a result.json for attempt "
                                 f"{result['attempt']}.", task=n, fix={"kind": "attempt-result", "task": n, "attempt": k}))
    return found


def check_tries(run_dir: Path, st: dict) -> list[Finding]:
    """Per task, `tries` matches the attempt folders and their result.json files."""
    found = []
    for n, t in _tasks(st):
        tries, have = int(t.get("tries", 0)), _attempt_numbers(run_dir, n)
        problems = _attempt_findings(run_dir, n, tries, have)
        found += problems or _result_findings(run_dir, n, tries, have)
    return found


def check_one_running(run_dir: Path, st: dict) -> list[Finding]:
    """At most one step line in the run is running."""
    running = [x for x in st.get("steps") or [] if x.get("status") == "running"]
    if len(running) < 2:
        return []
    names = ", ".join(str(x.get("step")) for x in running)
    return [Finding("many-running", f"{len(running)} step lines say running at once ({names}); only one can.",
                    fix={"kind": "step-line"})]


def check_questions(run_dir: Path, st: dict) -> list[Finding]:
    """The open questions are exactly the ones the run waits on."""
    found = [Finding("orphan-question", f"Question {g['id']} is unanswered but nothing waits on it.",
                     task=g.get("task"), fix={"kind": "close-question", "gate": g["id"]})
             for g in gates.orphans(run_dir)]
    if st.get("status") != "waiting":
        return found
    every = gates.run_gates(run_dir)
    open_ids = {g["id"] for g in every if g["state"] == "open"}
    answered_held = [g for g in every if g["state"] == "answered" and gates.held(st, g["id"])]
    if status.carrying_on(st, open_ids) and not answered_held:
        found.append(Finding("waiting-no-question", "The run is waiting but no open question is waiting for an answer.",
                             fix={"kind": "run-status"}))
    return found


CHECKS = (check_statuses, check_agreement, check_tries, check_one_running, check_questions)


def run_checks(run_dir) -> list[Finding]:
    """Run every state invariant on one run folder and return all findings (empty = healthy)."""
    run_dir = Path(run_dir)
    st = state.load(run_dir) or {}
    found = check_statuses(run_dir, st)
    if found:
        return found                    # the other checks need known statuses
    for check in CHECKS[1:]:
        found += check(run_dir, st)
    return found
