"""What happens when a task keeps failing (harness spec 13): retry, give up, or ask for help.

The runner calls three things from here:
- `should_retry` after every failed attempt: another try, or stop trying?
- `after_last_try` when it stops trying: `continue` fails the task (its dependents are skipped);
  `pause` and `delegate` open an escalation gate and the run waits (`delegate` also sends one message
  to the Phoenix agent, which falls back to `pause` when it cannot be reached).
- `acknowledge` when an escalation is answered `acknowledged`: commit any outside fix, count the
  escalation, and let the runner run exactly one more attempt.

Nothing here knows any step by name. Everything it needs is in the run folder: state.json, the frozen
settings.json, spec.json and each attempt's tasks/<n>/attempt-<k>/result.json.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from phoenix9 import agentnext as agentnext_mod
from phoenix9 import atomic, events, gatenotify, gates, handoff, paths, scrub, state, taskfile
from phoenix9.agentnext import AgentUnavailable
from phoenix9.git import is_env_file
from phoenix9 import spec as spec_mod

MAX_ESCALATIONS = 2          # a task is escalated at most this many times, then it is failed
EARLY_PREFIXES = ("SPEC_PROBLEM", "AUTH_ERROR")   # reasons that make retrying pointless
HANDOFF_FLAG = gates.HANDOFF_FLAG


# ---------------------------------------------------------------------- attempt records
def attempt_dir(run_dir, task_no: int, attempt: int) -> Path:
    """tasks/<n>/attempt-<k>/ in the run folder (prompts, session logs and result.json)."""
    return Path(run_dir) / "tasks" / str(task_no) / f"attempt-{attempt}"


def attempt_result(run_dir, task_no: int, attempt: int) -> dict | None:
    """How attempt k ended ({attempt, status, reasons}), or None while it is still going."""
    found = atomic.read_json(attempt_dir(run_dir, task_no, attempt) / "result.json")
    return found if isinstance(found, dict) and "status" in found else None   # a session record is not an end


def write_attempt_result(run_dir, task_no: int, attempt: int, status: str, reasons, kept: bool = False) -> None:
    """Record that attempt k is over. From here on a restart starts the next attempt, not this one."""
    atomic.write_json(attempt_dir(run_dir, task_no, attempt) / "result.json",
                      {"attempt": attempt, "status": status, "reasons": [scrub.scrub(r) for r in reasons],
                       "kept": bool(kept), "at": state.now()})


def _trimmed(reasons) -> list[str]:
    return [" ".join(str(r).split()) for r in reasons or []]


# ---------------------------------------------------------------------- retry or not
def should_retry(run_dir, task_no: int, max_tries: int) -> bool:
    """After a failed attempt: True = try again. False when any of these is true:
    the task was already escalated (after an acknowledgement there is exactly one more attempt),
    a reason starts with SPEC_PROBLEM or AUTH_ERROR, this attempt failed for exactly the same
    reasons as the one before, or the task has used all its tries."""
    task = state.load(run_dir)["tasks"][str(task_no)]
    k = task.get("tries", 0)
    now = _trimmed((attempt_result(run_dir, task_no, k) or {}).get("reasons"))
    if task.get("escalations", 0) > 0:
        return False
    if any(r.startswith(EARLY_PREFIXES) for r in now):
        return False
    if k > 1 and now == _trimmed((attempt_result(run_dir, task_no, k - 1) or {}).get("reasons")):
        return False
    return k < max(1, int(max_tries))


def after_last_try(runner, run_dir, task_no: int, reasons) -> str:
    """Apply the on_failure mode once the task has stopped retrying. Returns "failed" or "waiting".

    continue, or MAX_ESCALATIONS already used: the task is failed and flagged, its dependents skipped.
    pause / delegate: an escalation gate opens (see `escalate`) and the run waits for the answer.
    """
    run_dir = Path(run_dir)
    mode = (atomic.read_json(run_dir / "settings.json") or {}).get("on_failure", "pause")
    task = state.load(run_dir)["tasks"][str(task_no)]
    if mode == "continue" or task.get("escalations", 0) >= MAX_ESCALATIONS:
        fail_task(run_dir, task_no, reasons)
        return "failed"
    escalate(runner, run_dir, task_no, reasons)
    return "waiting"


# ---------------------------------------------------------------------- final task outcomes
def _spec(run_dir: Path):
    return spec_mod.from_json(atomic.read_json(run_dir / "spec.json"))


ALREADY_DONE = "already done: nothing needed changing"


def already_done_marker(run_dir, task_no: int, attempt: int) -> Path:
    """The file the builder leaves when the task needed no change (its checks are what decide)."""
    return attempt_dir(run_dir, task_no, attempt) / "already-done.txt"


def _finish_task(run_dir: Path, task_no: int, status: str, adapters=None, **fields) -> None:
    def change(s):
        s["tasks"][str(task_no)].update(status=status, gate=None, **fields)
    st = state.update(run_dir, change)
    taskfile.refresh(run_dir, task_no)
    events.emit("task.finished", project=st["project"], run=st["run_id"], task=task_no, status=status,
                note=fields.get("flagged") or fields.get("note", ""))
    if status == "passed" and handoff.current(run_dir, task_no):
        _handoff_fixed(adapters, run_dir, st, task_no)


ACTION_WORDS = {"retry": "it tried again", "rewrite-checks": "it rewrote the task's checks", "": "it tried again"}


def _handoff_fixed(adapters, run_dir: Path, st: dict, task_no: int) -> None:
    """The task passed while the agent had it: record `fixed`, tell Alex in one line and tell the conversation."""
    item = handoff.finish(run_dir, task_no, "fixed")
    project, run_id = st["project"], st["run_id"]
    events.emit("handoff.ended", project=project, run=run_id, task=task_no, gate=item["gate"], state="fixed")
    if adapters is None:
        return
    words = ACTION_WORDS.get(item.get("action", ""), ACTION_WORDS[""])
    adapters.notify.send(f"Phoenix: the agent fixed {project} task {task_no} ({words}); the build goes on.")
    post_outcome(getattr(adapters, "agentnext", None), item["gate"], "fixed", project=project, run=run_id, task=task_no)


def fail_task(run_dir, task_no: int, reasons) -> None:
    """Task failed: flag it with its reasons and skip every task that depends on it."""
    run_dir = Path(run_dir)
    handoff.finish(run_dir, task_no, "failed-again")   # a hand-off still open when the task fails did not hold
    flagged = scrub.scrub("; ".join(reasons)) or "it failed"
    _finish_task(run_dir, task_no, "failed", flagged=flagged)
    skip_dependents(run_dir, _spec(run_dir), task_no)


def skip_task(run_dir, task_no: int, note: str) -> None:
    """Task skipped (by an answer, or because a task it needs did not pass), and its dependents too."""
    run_dir = Path(run_dir)
    _finish_task(run_dir, task_no, "skipped", note=note)
    skip_dependents(run_dir, _spec(run_dir), task_no)


def skip_dependents(run_dir, spec, task_no: int) -> list[int]:
    """Skip every unfinished task that depends on task_no, directly or through others."""
    run_dir = Path(run_dir)
    st = state.load(run_dir)
    what = "failed" if st["tasks"][str(task_no)]["status"] == "failed" else "was skipped"
    note = f"depends on task {task_no}, which {what}"
    done = []
    for dep in spec_mod.dependents_of(spec, task_no):
        if st["tasks"].get(str(dep.number), {}).get("status") in ("pending", "running", "waiting"):
            _finish_task(run_dir, dep.number, "skipped", note=note)
            done.append(dep.number)
    return done


# ---------------------------------------------------------------------- escalation
def _links(run_dir: Path, task_no: int, tries: int) -> list[dict]:
    return [{"label": f"Attempt {k} logs", "url": str(attempt_dir(run_dir, task_no, k))}
            for k in range(1, tries + 1) if attempt_dir(run_dir, task_no, k).is_dir()]


HANDOFF_PATH = "/handoffs"
HANDOFF_TIMEOUT = 10     # seconds: a hand-off is one short call; a slow agent must not hold up the runner
NOT_SET_UP = "it isn't set up yet"
NOT_ANSWERING = "it isn't answering"
ODD_ANSWER = "it answered in a way Phoenix does not understand"


def handoff_body(run_id: str, task_no: int, gate_id: str, project: str) -> dict:
    """What is sent to the agent: only the four ids, never failure text or file content."""
    return {"run_id": run_id, "task": int(task_no), "gate_id": gate_id, "project": project}


def _first_sentence(text: str) -> str:
    line = " ".join(str(text).split())
    return line.split(". ")[0].rstrip(".")[:200]


def _hand_to_agent(agentnext, gate: dict, run_id: str, project: str, task_no: int) -> tuple[str, str]:
    """POST the hand-off to the agent's /handoffs. Returns (problem, thread_id): ("", thread) when it took the
    question (200/202 with a thread_id), else (the plain reason it did not, "") (not set up, not answering,
    no key, refused)."""
    if agentnext is None or not getattr(agentnext, "set_up", True):
        return NOT_SET_UP, ""
    body = json.dumps(handoff_body(run_id, task_no, gate["id"], project)).encode()
    try:
        reply = agentnext.request("POST", HANDOFF_PATH, body, {"Content-Type": "application/json"},
                                  timeout=HANDOFF_TIMEOUT)
        raw = b"".join(reply.chunks)
    except AgentUnavailable as err:
        return (NOT_SET_UP if str(err) == agentnext_mod.NOT_SET_UP else NOT_ANSWERING), ""
    except Exception:  # noqa: BLE001 - an agent that is down or broken must fall back to Alex, not crash
        return NOT_ANSWERING, ""
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    data = data if isinstance(data, dict) else {}
    if reply.status in (200, 202) and isinstance(data.get("thread_id"), str) and data["thread_id"]:
        return "", data["thread_id"]
    if reply.status == 409 and isinstance(data.get("error"), str) and data["error"].strip():
        return scrub.scrub(_first_sentence(data["error"])), ""
    return ODD_ANSWER, ""


OUTCOME_PATH = "/handoffs/outcome"
OUTCOMES = ("fixed", "failed-again", "gave-up")
TRIED_TWICE = "the agent already tried twice; waiting for you"


def post_outcome(agentnext, gate_id: str, outcome: str, project: str | None = None, run: str | None = None,
                 task: int | None = None) -> bool:
    """Tell the hand-off conversation how it ended (POST /handoffs/outcome). Best effort: any error is only
    recorded as a `handoff.ended` event with posted=False and never reaches the caller. True when it was taken."""
    if outcome not in OUTCOMES:
        raise ValueError(f"not a hand-off outcome: {outcome!r}")
    ok = False
    try:
        if agentnext is not None and getattr(agentnext, "set_up", True):
            body = json.dumps({"gate_id": gate_id, "outcome": outcome}).encode()
            reply = agentnext.request("POST", OUTCOME_PATH, body, {"Content-Type": "application/json"},
                                      timeout=HANDOFF_TIMEOUT)
            b"".join(reply.chunks)
            ok = 200 <= reply.status < 300
    except Exception:  # noqa: BLE001 - the conversation missing one line must never stop a build
        ok = False
    if not ok:
        try:
            events.emit("handoff.ended", project=project, run=run, task=task, gate=gate_id, outcome=outcome,
                        posted=False)
        except Exception:  # noqa: BLE001 - not even a log problem may break the runner
            pass
    return ok


def escalate(runner, run_dir, task_no: int, reasons) -> dict:
    """Open the escalation gate for a task and tell Alex, or hand it to the agent (delegate).

    The gate: kind escalation, actions acknowledged / skip / stop, title "Task N needs you", why = the
    last reasons, links = the attempt folders. In delegate mode the gate carries the flag
    HANDOFF_FLAG and ONE hand-off (only the ids) goes to the agent's /handoffs, recorded in
    tasks/<n>/handoff.json (`handoff`); Alex gets no line now (the bell shows it; the usual reminders follow).
    When the agent's earlier fix did not hold, that hand-off becomes `failed-again` first. When the agent
    cannot take it, or already had this task handoff.LIMIT times, the flag is replaced by a note saying why
    and Alex is told, exactly as in pause mode.
    """
    from phoenix9.runner import _open_gate
    run_dir = Path(run_dir)
    mode = (atomic.read_json(run_dir / "settings.json") or {}).get("on_failure", "pause")
    st = state.load(run_dir)
    task = st["tasks"][str(task_no)]
    project, run_id, tries = st["project"], st["run_id"], task.get("tries", 0)
    why = scrub.scrub("; ".join(reasons)) or "it kept failing"
    gate = _open_gate(run_dir, ("task", task_no), kind="escalation", title=f"Task {task_no} needs you", why=why,
                      task=task_no, links=_links(run_dir, task_no, tries),
                      flags=[HANDOFF_FLAG] if mode == "delegate" else [])
    told = f"Phoenix: task {task_no} of run {run_id} ({project}) needs you: {why} (gate {gate['id']})"
    if mode != "delegate":
        runner.adapters.notify.send(told)
        gatenotify.mark_sent(runner.adapters, run_dir, gate)     # this is its one message; reminders follow it
        return gate
    agentnext = getattr(runner.adapters, "agentnext", None)
    before = handoff.current(run_dir, task_no)
    if handoff.load(run_dir, task_no)["count"] >= handoff.LIMIT:
        if before:
            handoff.finish(run_dir, task_no, "failed-again")
            events.emit("handoff.ended", project=project, run=run_id, task=task_no, gate=before["gate"],
                        state="failed-again")
        gate = gates.set_flags(run_dir, gate["id"], [TRIED_TWICE])
        runner.adapters.notify.send(told)
        gatenotify.mark_sent(runner.adapters, run_dir, gate)
        return gate
    if before:                                               # the agent's fix did not hold
        handoff.finish(run_dir, task_no, "failed-again")
        events.emit("handoff.ended", project=project, run=run_id, task=task_no, gate=before["gate"],
                    state="failed-again")
        post_outcome(agentnext, before["gate"], "failed-again", project=project, run=run_id, task=task_no)
    problem, thread = _hand_to_agent(agentnext, gate, run_id, project, task_no)
    if problem:
        note = f"could not be handed to the Phoenix agent ({problem}); waiting for you"
        gate = gates.set_flags(run_dir, gate["id"], [note])
        runner.adapters.notify.send(f"Phoenix: the Phoenix agent could not be reached: {problem}. {told}")
        return gate
    handoff.start(run_dir, task_no, gate["id"], thread)
    events.emit("handoff.started", project=project, run=run_id, task=task_no, gate=gate["id"], thread=thread)
    gatenotify.mark_sent(runner.adapters, run_dir, gate)     # no message now; reminders follow as for any gate
    return gate


ENV_SKIP_DIRS = {".git", "node_modules"}


def move_env_out(adapters, run_dir, worktree, task_no: int) -> list[str]:
    """Move every .env-style file out of the worktree into tasks/<n>/outside-env/<path>: keys belong
    in Phoenix secrets, never in the code. Each one adds a failure line and tells Alex.
    Returns the moved paths (relative to the worktree)."""
    worktree, moved = Path(worktree), []
    for folder, dirs, files in os.walk(worktree):
        dirs[:] = [d for d in dirs if d not in ENV_SKIP_DIRS]
        for name in sorted(files):
            if is_env_file(name):
                moved.append(str((Path(folder) / name).relative_to(worktree)))
    lines = []
    for rel in sorted(moved):
        target = Path(run_dir) / "tasks" / str(task_no) / "outside-env" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(worktree / rel), str(target))
        lines.append(f"env file {rel} was moved out of the worktree; keys belong in Phoenix secrets")
    if lines:
        state.update(Path(run_dir), lambda s: s["tasks"][str(task_no)]["failures"].extend(lines))
        adapters.notify.send(f"Phoenix: task {task_no}: " + "; ".join(lines) + ".")
    return sorted(moved)


def outside_fix_commit(adapters, run_dir, worktree, task_no: int, who: str) -> str | None:
    """Commit what someone changed in the worktree while the task waited. .env-style files are
    first moved out of the worktree (`move_env_out`), and the commit skips them anyway.
    Returns the new commit (the next attempt starts from it), or None when nothing changed."""
    if worktree is None or not Path(worktree).is_dir():
        return None
    move_env_out(adapters, run_dir, worktree, task_no)
    if not adapters.git.pending_paths(worktree, skip_env=True):
        return None
    run_id = state.load(run_dir)["run_id"]
    return adapters.git.commit(worktree, f"Outside fix before retry of task {task_no}",
                               {"Phoenix-Run": run_id, "Phoenix-Task": str(task_no), "Phoenix-Fix-By": who},
                               skip_env=True)


def acknowledge(runner, run_dir, task_no: int, answer: dict) -> None:
    """An escalation was acknowledged: commit any outside fix, set attempt_base to the worktree's
    HEAD (always, so a crash after the fix commit still keeps it), count the escalation, add the
    note to the failures, set `rerun`, and close the gate. The runner then runs exactly one more
    attempt (starting it clears `rerun`)."""
    run_dir = Path(run_dir)
    st = state.load(run_dir)
    worktree = paths.work(st["project"], st["run_id"])
    outside_fix_commit(runner.adapters, run_dir, worktree, task_no, answer.get("who", "cli"))
    sha = runner.adapters.git.head(worktree) if worktree.is_dir() else None
    note = (answer.get("note") or "").strip()

    def change(s):
        t = s["tasks"][str(task_no)]
        t["escalations"] = t.get("escalations", 0) + 1
        t["gate"] = None
        t["rerun"] = True
        if sha:
            t["attempt_base"] = sha
        if note:
            t["failures"].append(scrub.scrub(f"Note from {answer.get('who', 'cli')}: {note}"))
        s["current"]["gate"] = None
    state.update(run_dir, change)
