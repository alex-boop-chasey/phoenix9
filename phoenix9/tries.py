"""Per-task tries of a run: one line per attempt, worked out from the run's state step lines."""
from phoenix9 import atomic, failmodes, scrub

REASON_CHARS = 200
_WORKING = ("running", "waiting", "paused", "pending")


def _one_line(text) -> str:
    """Scrub text, join it to one line and cut it short."""
    line = " ".join(scrub.scrub(str(text or "")).split())
    return line if len(line) <= REASON_CHARS else line[:REASON_CHARS - 3] + "..."


def _status(lines: list) -> str:
    """The try's overall status: failed if any step failed, running if one is still going, else passed."""
    statuses = [x.get("status") for x in lines]
    if "failed" in statuses:
        return "failed"
    if any(s in _WORKING for s in statuses):
        return "running"
    return "passed" if "passed" in statuses else "skipped"


def _ending_line(lines: list, status: str) -> dict:
    """The step line that ended the try: the first failing step, else the last one."""
    if status == "failed":
        return next(x for x in lines if x.get("status") == "failed")
    return lines[-1]


def _result_reason(run_dir, task: int, attempt: int) -> str:
    """The first reason the attempt's result.json recorded (empty when there is none)."""
    done = failmodes.attempt_result(run_dir, task, attempt) or {}
    return next(iter(done.get("reasons") or []), "")


def _try_entry(run_dir, task: int, attempt: int, lines: list) -> dict:
    """One try: attempt number, ending step, overall status, when it ended and a one-line reason."""
    status = _status(lines)
    end = _ending_line(lines, status)
    reason = end.get("note") or (_result_reason(run_dir, task, attempt) if status == "failed" else "")
    return {"attempt": attempt, "step": end.get("step"), "status": status,
            "at": end.get("finished") or end.get("started"), "reason": _one_line(reason)}


def by_task(run_dir, state: dict) -> dict:
    """Each task's tries, as {task number (text): [one entry per attempt, oldest first]}."""
    grouped: dict = {n: {} for n in (state.get("tasks") or {})}
    for line in state.get("steps") or []:
        if line.get("task") is None:
            continue
        attempts = grouped.setdefault(str(line["task"]), {})
        attempts.setdefault(int(line.get("attempt") or 1), []).append(line)
    return {n: [_try_entry(run_dir, int(n), k, attempts[k]) for k in sorted(attempts)]
            for n, attempts in grouped.items()}


def counts(tries: dict) -> dict:
    """How many tries each task has, from by_task()'s result."""
    return {n: len(found) for n, found in tries.items()}


def of_run(run_dir) -> tuple[dict, dict]:
    """(tries count per task, try lines per task) for a run folder."""
    from phoenix9 import state
    found = by_task(run_dir, atomic.read_json(run_dir / "state.json") or state.load(run_dir) or {})
    return counts(found), found
