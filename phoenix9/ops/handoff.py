"""Ops for a build task Phoenix handed to the agent: the agent's own fix (try again, or rewrite the checks once)
and its giving up (the question goes back to Alex).

Only the agent (`who == "agent"`) may call these, and only while Phoenix itself says the task is handed to it:
the run exists, the task's escalation question is open and carries the hand-off flag, and tasks/<n>/handoff.json
has a working hand-off for exactly that question. Everything else is refused in plain words."""
from phoenix9 import events, failmodes, gates as core, handoff, runs, scrub
from phoenix9.ops import common, gates as gates_ops, repair as repair_ops
from phoenix9.repair import unlock

ACTIONS = ("retry", "rewrite-checks")
NOT_HANDED = "That task is not handed to the agent right now."
NOTE_MAX = 2000
WHY_MAX = unlock.WHY_MAX
GAVE_UP = core.GAVE_UP_PREFIX


def _handed(project: str, run_id: str, task, who: str) -> tuple:
    """(run folder, open escalation gate, working hand-off) for this task; Conflict when it is not handed to the agent."""
    if who != "agent":
        raise common.Conflict("Only the Phoenix agent acts on a hand-off; answer the question itself instead.")
    if isinstance(task, bool) or not isinstance(task, int) or task < 1:
        raise common.OpsError("The task must be a number from 1 up.")
    folder = runs.find_run(run_id) if isinstance(run_id, str) and run_id else None
    if folder is None or folder.parent.name != project:
        raise common.Conflict(NOT_HANDED)
    item = handoff.current(folder, task)
    gate = next((g for g in core.run_gates(folder)
                 if g.get("state") == "open" and g.get("kind") == "escalation" and g.get("task") == task
                 and core.HANDOFF_FLAG in (g.get("flags") or [])), None)
    if item is None or gate is None or item.get("gate") != gate["id"]:
        raise common.Conflict(NOT_HANDED)
    return folder, gate, item


def _clean_note(note) -> str:
    """The note for the builder as one scrubbed paragraph of at most NOTE_MAX characters (may be empty)."""
    if note is None:
        return ""
    if not isinstance(note, str):
        raise common.OpsError("The note must be text.")
    flat = " ".join(note.split())
    if len(flat) > NOTE_MAX:
        raise common.OpsError(f"Keep the note under {NOTE_MAX} characters.")
    return scrub.scrub(flat)


def _clean_why(task: int, why) -> str:
    """The reason as one short plain line (required)."""
    why = repair_ops._clean_task_and_why(task, why)
    if len(why) > WHY_MAX:
        raise common.OpsError(f"Keep the reason under {WHY_MAX} characters.")
    return scrub.scrub(why)


def _retry(folder, gate: dict, task: int, note: str) -> dict:
    """Answer the handed question `acknowledged` (the runner tries the task once more, with the note)."""
    gates_ops.answer(gate["id"], "acknowledged", note=note, who="agent")
    handoff.mark(folder, task, action="retry")
    return {"done": f"Task {task} will be tried again" + (" with your note for the builder." if note else ".")}


def _rewrite_checks(folder, gate: dict, task: int, why: str) -> dict:
    """Rewrite the task's checks once under a hand-off grant, then close the question so the run goes on."""
    if handoff.rewrite_used(folder, task):
        raise common.Conflict("The agent already rewrote this task's checks once; it needs Alex now.")
    grant = unlock.grant_for_handoff(folder, task, why, gate=gate["id"])
    text = repair_ops._note_text(folder.name, why, [f"rewrite the checks of task {task} because {why}"])
    try:
        done = repair_ops.apply_text(folder.name, text, who="agent", approve_unlock=True)
    except common.OpsError as err:
        unlock.withdraw(folder, grant, str(err))
        raise common.Conflict(f"Phoenix did not rewrite the checks: {err}") from None
    if not done.get("ok") or done.get("refused"):
        why_not = " ".join(str(done.get("refused") or "the run did not pass its check afterwards").split())
        unlock.withdraw(folder, grant, why_not)
        raise common.Conflict(f"Phoenix did not rewrite the checks: {scrub.scrub(why_not)}")
    if not any(g.get("used_at") and g.get("approved_at") == grant["approved_at"] for g in unlock.records(folder)):
        unlock.withdraw(folder, grant, "not needed: the task's checks were not locked")
    core.close_questions(folder, "the agent rewrote the task's checks", who="agent", only=gate["id"])
    handoff.mark(folder, task, action="rewrite-checks", rewrote_checks=True)
    return {"done": f"The checks of task {task} were removed; the check writer writes them again and the task "
                    "starts over.", "snapshot": done.get("snapshot")}


def fix(project: str, run_id: str, task: int, action: str, why: str = "", note: str = "", who: str = "agent") -> dict:
    """On a task handed to the agent: try it again (with an optional note) or rewrite its checks (once per task)."""
    if action not in ACTIONS:
        raise common.OpsError(f"'{action}' is not a hand-off action. Use one of: {', '.join(ACTIONS)}.")
    folder, gate, _item = _handed(project, run_id, task, who)
    if action == "retry":
        why = scrub.scrub(" ".join(str(why or "").split()))[:WHY_MAX]
        done = _retry(folder, gate, task, _clean_note(note))
    else:
        why = _clean_why(task, why)
        done = _rewrite_checks(folder, gate, task, why)
    events.emit("handoff.acted", project=project, run=run_id, task=task, gate=gate["id"], who="agent",
                action=action, why=why)
    common.record_command("agent", f"handoff fix {run_id} --task {task} --action {action}", project,
                          f"the agent acted on the hand-off of task {task} of run {run_id}: {action}")
    return {"project": project, "run_id": run_id, "task": task, "gate": gate["id"], "action": action, **done}


def give_up(project: str, run_id: str, task: int, why: str, who: str = "agent") -> dict:
    """On a task handed to the agent: hand the question back to Alex with the reason (one Telegram line)."""
    folder, gate, _item = _handed(project, run_id, task, who)
    why = _clean_why(task, why)
    handoff.finish(folder, task, "gave-up", why)
    core.set_flags(folder, gate["id"], [f"{GAVE_UP}{why}"])
    adapters = common.make_adapters()
    adapters.notify.send(f"Phoenix: the agent couldn't fix {project} task {task}: {why}. It needs you "
                         f"(gate {gate['id']}).")
    posted = failmodes.post_outcome(getattr(adapters, "agentnext", None), gate["id"], "gave-up", project=project,
                                    run=run_id, task=task)
    events.emit("handoff.ended", project=project, run=run_id, task=task, gate=gate["id"], state="gave-up", why=why)
    common.record_command("agent", f"handoff give-up {run_id} --task {task}", project,
                          f"the agent handed task {task} of run {run_id} back to Alex: {why}")
    return {"project": project, "run_id": run_id, "task": task, "gate": gate["id"], "state": "gave-up",
            "posted": posted}
