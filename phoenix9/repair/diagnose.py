"""Plain-rules diagnosis of a stopped or failed run: the cause, what was tried and which repairs fit (no AI)."""
from phoenix9 import failmodes

RERUN, REWRITE, SKIP = "step-rerun", "task-checks-rewrite", "task-skip"
RESUME, RESTART, RAISE = "run-resume-from", "run-restart-preset", "max-tries-raise"
ENDED_BAD = ("failed", "stopped")


def _option(control: str, label: str, **inputs) -> dict:
    """One repair option: the control to use, a button label and the inputs to pre-fill."""
    return {"control": control, "label": label, "inputs": inputs}


def tried_lines(tries: list) -> list[str]:
    """One plain line per try, from the task's try entries."""
    out = []
    for t in tries:
        line = f"Try {t['attempt']} ({t.get('step') or 'a step'}): {t['status']}"
        out.append(line + (f" - {t['reason']}" if t.get("reason") else ""))
    return out


def _last_reasons(run_dir, task: int, tries: list) -> list[str]:
    """The reasons the last try ended with (from its result file, else the try's own line)."""
    if not tries:
        return []
    done = failmodes.attempt_result(run_dir, task, tries[-1]["attempt"]) or {}
    return [str(r) for r in done.get("reasons") or []] or ([tries[-1]["reason"]] if tries[-1].get("reason") else [])


def _same_twice(run_dir, task: int, tries: list) -> bool:
    """True when the last two tries failed for exactly the same reasons."""
    if len(tries) < 2:
        return False
    before = failmodes.attempt_result(run_dir, task, tries[-2]["attempt"]) or {}
    now = failmodes.attempt_result(run_dir, task, tries[-1]["attempt"]) or {}
    a, b = failmodes._trimmed(before.get("reasons")), failmodes._trimmed(now.get("reasons"))
    return bool(a) and a == b


def cause_of(run_dir, status: str, task: int | None, task_status: str | None, tries: list,
             max_tries: int | None, findings: list) -> tuple[str, str]:
    """The cause code and a plain-English sentence for it."""
    n = f"Task {task}"
    reasons = _last_reasons(run_dir, task, tries) if task is not None else []
    if status in ("passed", "done", "running", "queued", "paused") and task_status != "failed":
        return "no-problem", f"Nothing has gone wrong: the run is {status}."
    if task is None:
        return ("state-broken", f"The run is {status} but its saved state disagrees with itself: {findings[0].text}"
                ) if findings else ("unknown", f"The run is {status}, and no task is to blame.")
    if any(r.startswith("AUTH_ERROR") for r in reasons):
        return "auth-error", f"{n} could not sign in to the AI service, so trying again would not help."
    if any(r.startswith("SPEC_PROBLEM") for r in reasons):
        return "spec-problem", f"{n} cannot be done as the spec words it; the builder said the spec is wrong."
    if task_status == "waiting":
        return "waiting-for-answer", f"{n} is waiting for an answer after {len(tries)} tries."
    if task_status == "failed" and max_tries and len(tries) >= max_tries:
        return "out-of-tries", f"{n} failed on all {len(tries)} of its allowed tries."
    if task_status == "failed" and _same_twice(run_dir, task, tries):
        return "same-failure", f"{n} failed twice in a row for the same reason, so Phoenix stopped trying."
    if task_status == "failed":
        return "task-failed", f"{n} failed."
    if status == "stopped":
        return "run-stopped", f"The run was stopped while {n} was {task_status or 'unfinished'}."
    return "stuck", f"{n} is still marked {task_status or 'unfinished'} but the run is {status}."


def options_of(code: str, project: str, run_id: str, task: int | None, tries: int, max_tries: int | None,
               preset: str | None) -> list[dict]:
    """The repair controls that fit this cause."""
    base = {"project": project, "run_id": run_id}
    t = {**base, "task": task}
    again = _option(RERUN, f"Re-run task {task}", **t)
    rewrite = _option(REWRITE, f"Rewrite the checks of task {task}", **t)
    skip = _option(SKIP, f"Skip task {task}", **t)
    resume = _option(RESUME, "Resume the run", **t)
    restart = _option(RESTART, "Restart the build on another preset", **base, current=preset)
    raise_ = _option(RAISE, f"Allow {max(tries, max_tries or 0) + 1} tries", **base, max_tries=max(tries, max_tries or 0) + 1)
    return {
        "out-of-tries": [raise_, again, skip],
        "same-failure": [again, rewrite, skip],
        "task-failed": [again, rewrite, skip],
        "waiting-for-answer": [again, skip],
        "spec-problem": [rewrite, skip, restart],
        "auth-error": [again, resume],
        "run-stopped": [resume, restart],
        "stuck": [resume, again],
    }.get(code, [])


def diagnose(run_dir, project: str, run_id: str, st: dict, task: int | None, tries: list,
             max_tries: int | None, preset: str | None, findings: list) -> dict:
    """The typed diagnosis: {cause_code, cause, task, tried, options}."""
    info = (st.get("tasks") or {}).get(str(task)) or {} if task is not None else {}
    code, cause = cause_of(run_dir, st.get("status", ""), task, info.get("status"), tries, max_tries, findings)
    return {"project": project, "run_id": run_id, "status": st.get("status"), "task": task,
            "title": info.get("title"), "cause_code": code, "cause": cause, "tried": tried_lines(tries),
            "options": options_of(code, project, run_id, task, len(tries), max_tries, preset)}
