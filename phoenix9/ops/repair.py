"""Ops for the repair kit: check a run, write its report, apply a repair note, undo a repair."""
import contextlib
import re

from phoenix9 import atomic, events, runs as core, settings, state
from phoenix9.ops import common, runs as runs_ops
from phoenix9.repair import apply as apply_mod, check as check_mod, diagnose as diagnose_mod, lock, notes, report as report_mod, resume as resume_mod, safety, snapshot, unlock
from phoenix9.repair.steps import is_chat


def _run_folder(run_id: str, project: str | None = None):
    """The run folder for a run id (the id alone finds its project); NotFound when there is none."""
    folder = core.find_run(run_id)
    if folder is None or (project and folder.parent.name != project):
        raise common.NotFound(f"There is no run called '{run_id}'" + (f" in project '{project}'." if project else "."))
    return folder


def _may_repair(folder, who: str) -> None:
    """Refuse a caller that may not repair runs of this project (the same rule as stopping a run)."""
    if not runs_ops._may_stop(folder.parent.name, who):
        raise common.Conflict(f"'{who}' may not repair runs in {folder.parent.name}.")


def _refuse_loosening(folder, note, who: str, approve_unlock: bool) -> list[str]:
    """Refuse, before anything changes, a repair from the agent or chat that would loosen a safety check, unless
    Alex approved exactly that in the dashboard; returns the unlocks his grant covers (empty when none is needed).

    Without a grant the caller must also be allowed to repair runs of the project; Alex's approval of this one
    repair on this run stands in for that."""
    needed = safety.needed_unlocks(folder, note, approve_unlock) if safety.is_agent(who) else []
    if needed is None:
        raise common.Conflict(safety.NEVER_REFUSAL)
    if needed and unlock.find(folder, who, needed) is None:
        raise common.Conflict(safety.REFUSAL)
    if not needed:
        _may_repair(folder, who)
    return needed


def _use_grant(folder, note, who: str, approve_unlock: bool, needed: list[str], dry_run: bool) -> bool:
    """Use Alex's grant for this repair (a dry run only looks); returns approve_unlock for the apply."""
    if not needed:
        return approve_unlock
    why = safety.refusal(folder, note, who, approve_unlock, use=not dry_run)
    if why:
        raise common.Conflict(why)
    return approve_unlock or "unlock-checks" in needed


@contextlib.contextmanager
def _one_at_a_time(folder):
    """Hold the run's repair lock; a second repair on the same run is a plain Conflict."""
    try:
        with lock.held(folder):
            yield
    except lock.Busy as err:
        raise common.Conflict(str(err)) from None


def undo(run_id: str, to: int | None = None, who: str = "cli", project: str | None = None) -> dict:
    """Undo a repair: put the run back as snapshot `to` (default the newest) had it; refused while the runner walks it."""
    folder = _run_folder(run_id, project)
    _may_repair(folder, who)
    if is_chat(who):
        raise common.Conflict("Undoing a repair needs Alex: ask him to run it from the dashboard or the command line.")
    try:
        done = snapshot.undo(folder, to=to, who=who)
    except (snapshot.RepairRefused, snapshot.SnapshotError) as err:
        raise common.OpsError(str(err)) from None
    return {"run_id": run_id, "project": folder.parent.name, **done}


def request_unlock(run_id: str, steps, why: str, who: str = "agent", project: str | None = None) -> dict:
    """Ask Alex to allow, once, repairs the agent or a chat may not do alone; he answers in the dashboard.

    Opens a repair-unlock question on the run (the run itself is not changed). Only the dashboard can answer
    it; approving gives a one-time grant for exactly these repairs on this run, for 30 minutes."""
    folder = _run_folder(run_id, project)
    if not safety.is_agent(who):
        raise common.OpsError("Only the agent or a chat needs Alex's approval; you can do this repair yourself.")
    asker = who.split(":", 1)[1] if is_chat(who) else ""
    if asker and asker != "home" and asker != folder.parent.name:
        raise common.Conflict(f"A project chat may only ask about runs of its own project, not {folder.parent.name}.")
    try:
        gate = unlock.request(folder, steps, why, who)
    except unlock.UnlockError as err:
        raise common.OpsError(str(err)) from None
    common.record_command(who, f"repair request-unlock {run_id} --steps {','.join(gate['unlock_steps'])}",
                          folder.parent.name)
    return {"run_id": run_id, "project": folder.parent.name, "gate": gate["id"], "title": gate["title"],
            "steps": gate["unlock_steps"], "why": gate["why"]}


def check(run_id: str, project: str | None = None) -> dict:
    """Check a run for broken state: {run_id, project, ok, problems: [{code, text, task}]}."""
    folder = _run_folder(run_id, project)
    found = check_mod.run_checks(folder)
    return {"run_id": run_id, "project": folder.parent.name, "ok": not found,
            "problems": [{"code": f.code, "text": f.text, "task": f.task} for f in found]}


def report(run_id: str, project: str | None = None) -> dict:
    """Write and return the run report: {run_id, project, path, text, failed_steps}."""
    folder = _run_folder(run_id, project)
    text = report_mod.write(folder)
    failed = check_mod.failed_steps(state.load(folder) or {})
    return {"run_id": run_id, "project": folder.parent.name, "path": str(report_mod.report_path(folder)), "text": text,
            "failed_steps": failed}


def apply(note_path: str, who: str = "cli", dry_run: bool = False, approve_unlock: bool = False) -> dict:
    """Apply a repair note to its run (or only show what it would do): the outcome, with the steps and both checks."""
    try:
        note = apply_mod._read_note(note_path)[2]
    except snapshot.RepairRefused as err:
        raise common.OpsError(str(err)) from None
    folder = _run_folder(note.run)
    needed = _refuse_loosening(folder, note, who, approve_unlock)
    with _one_at_a_time(folder):
        approve_unlock = _use_grant(folder, note, who, approve_unlock, needed, dry_run)
        try:
            return apply_mod.apply(note_path, who, dry_run=dry_run, approve_unlock=approve_unlock,
                                   granted=tuple(needed))
        except snapshot.RepairRefused as err:
            raise common.OpsError(str(err)) from None


def apply_text(run_id: str, text: str, who: str = "dashboard", dry_run: bool = False,
               approve_unlock: bool = False) -> dict:
    """Save posted note text in the run's repairs/notes and apply it; unreadable notes are OpsError, refusals Conflict."""
    folder = _run_folder(run_id)
    try:
        note = notes.parse(text)
    except notes.NoteError as err:
        raise common.OpsError(str(err)) from None
    if note.run != run_id:
        raise common.OpsError(f"line 1: the note is for run '{note.run}', not '{run_id}'.")
    needed = _refuse_loosening(folder, note, who, approve_unlock)
    with _one_at_a_time(folder):
        approve_unlock = _use_grant(folder, note, who, approve_unlock, needed, dry_run)
        path = snapshot.repairs_dir(folder) / "notes" / f"{snapshot.next_number(folder)}-{apply_mod.slug_of(note.why)}.md"
        atomic.write_text(path, text if text.endswith("\n") else text + "\n")
        try:
            return apply_mod.apply(path, who, dry_run=dry_run, approve_unlock=approve_unlock,
                                   granted=tuple(needed))
        except snapshot.RepairRefused as err:
            raise common.Conflict(str(err)) from None


def resume(run_id: str, who: str = "cli", project: str | None = None) -> dict:
    """Resume a repaired run: snapshot it, move it to running (or queued), and record the repair."""
    folder = _run_folder(run_id, project)
    _may_repair(folder, who)
    title = "Resume the run"
    with _one_at_a_time(folder):
        try:
            snapshot.refuse_if_walking(folder)
            why = resume_mod.refusal(folder)
            if why:
                raise snapshot.RepairRefused(why)
            got = snapshot.take(folder, title)
            status = resume_mod.resume(folder, who)
        except (snapshot.RepairRefused, snapshot.SnapshotError) as err:
            raise common.OpsError(str(err)) from None
    events.emit("repair.applied", project=folder.parent.name, run=run_id, who=who, note="resume", title=title,
                steps=["resume"], check_before=[], check_after=[], forced=False, rolled_back=False, snapshot=got)
    common.record_command(who, f"repair resume {run_id}", folder.parent.name,
                          f"repair on run {run_id}: {title} (applied, snapshot {got})")
    return {"run_id": run_id, "project": folder.parent.name, "status": status, "snapshot": got}


def _note_text(run_id: str, why: str, steps: list[str]) -> str:
    """Build the text of a repair note from typed parts."""
    return f"# Repair {run_id}\n\nWhy: {why}\n\n## Steps\n" + "".join(f"- {s}\n" for s in steps)


def rerun_step(run_id: str, task: int | None = None, finish_step: str | None = None, who: str = "agent") -> dict:
    """Re-run a task (`retry task N`) or a finish step (`rerun finish step NAME`) through a repair note."""
    if (task is None) == (finish_step is None):
        raise common.OpsError("Say either a task number or a finish step name, not both and not neither.")
    if task is not None:
        if isinstance(task, bool) or not isinstance(task, int) or task < 1:
            raise common.OpsError("The task must be a number from 1 up.")
        step, why = f"retry task {task}", f"Run task {task} again"
    else:
        if not re.fullmatch(notes.WORD, finish_step):
            raise common.OpsError("The finish step name may only use letters, digits and . _ : -")
        step, why = f"rerun finish step {finish_step}", f"Run finish step {finish_step} again"
    return apply_text(run_id, _note_text(run_id, why, [step]), who=who)


def resume_from(run_id: str, task: int, who: str = "agent") -> dict:
    """Resume a run from a task: `retry task N` then `resume`, through one repair note."""
    if isinstance(task, bool) or not isinstance(task, int) or task < 1:
        raise common.OpsError("The task must be a number from 1 up.")
    text = _note_text(run_id, f"Resume the run from task {task}", [f"retry task {task}", "resume"])
    return apply_text(run_id, text, who=who)


def _clean_task_and_why(task: int, why: str) -> str:
    """Check the task number and the reason (one printable line, no note syntax); return the trimmed reason."""
    if isinstance(task, bool) or not isinstance(task, int) or task < 1:
        raise common.OpsError("The task must be a number from 1 up.")
    if not isinstance(why, str) or not why.strip():
        raise common.OpsError("Give a reason, in one line.")
    why = why.strip()
    if len(why.splitlines()) != 1 or not why.isprintable():
        raise common.OpsError("The reason must be one line of plain text.")
    return why


def skip_task(run_id: str, task: int, why: str, who: str = "agent") -> dict:
    """Skip a task (`mark task N skipped because WHY`) through a repair note."""
    why = _clean_task_and_why(task, why)
    text = _note_text(run_id, why, [f"mark task {task} skipped because {why}"])
    return apply_text(run_id, text, who=who)


def rewrite_checks(run_id: str, task: int, why: str, who: str = "agent") -> dict:
    """Rewrite a task's checks (`rewrite the checks of task N because WHY`), never unlocking locked checks."""
    why = _clean_task_and_why(task, why)
    text = _note_text(run_id, why, [f"rewrite the checks of task {task} because {why}"])
    return apply_text(run_id, text, who=who, approve_unlock=False)


def diagnose(project: str, run_id: str) -> dict:
    """Say in typed data why a run stopped or failed: the cause, what was tried and which repairs fit."""
    from phoenix9 import state
    shown = runs_ops.task_tries(project, run_id)
    folder = _run_folder(run_id, project)
    st = state.load(folder) or {}
    found = check_mod.run_checks(folder)
    detail = runs_ops.detail(project, run_id)
    return diagnose_mod.diagnose(folder, project, run_id, st, shown["task"], shown["tries"], shown["max_tries"],
                                 detail.get("preset"), found)


MAX_TRIES_LIMIT = 10   # the most tries per task a repair may allow


def raise_max_tries(run_id: str, tries: int, who: str = "agent") -> dict:
    """Raise a run's max tries (`set max_tries=N for this run`); never lower it, never above the fixed limit."""
    if isinstance(tries, bool) or not isinstance(tries, int):
        raise common.OpsError("The number of tries must be a whole number.")
    if tries > MAX_TRIES_LIMIT:
        raise common.Conflict(f"A run may have at most {MAX_TRIES_LIMIT} tries per task; {tries} is too many.")
    folder = _run_folder(run_id)
    current = runs_ops.detail(folder.parent.name, run_id).get("max_tries")
    if isinstance(current, int) and tries <= current:
        raise common.Conflict(f"The run already allows {current} tries; ask for more than that.")
    if tries < 1:
        raise common.OpsError("The number of tries must be 1 or more.")
    text = _note_text(run_id, f"Allow {tries} tries per task", [f"set max_tries={tries} for this run"])
    return apply_text(run_id, text, who=who)


def restart_on_preset(project: str, run_id: str, preset: str, who: str = "agent") -> dict:
    """Start a new run from a stopped or failed run's spec on another preset, and record it on the old run."""
    folder = _run_folder(run_id, project)
    _may_repair(folder, who)
    if preset not in settings.PRESETS:
        raise common.OpsError(f"'{preset}' is not a preset. Use one of: {', '.join(settings.PRESETS)}.")
    status = (state.load(folder) or {}).get("status")
    if status not in ("stopped", "failed"):
        raise common.Conflict(f"The run is {status}; only a stopped or failed run can be restarted on another preset.")
    current = runs_ops.detail(project, run_id).get("preset")
    if preset == current:
        raise common.Conflict(f"The run already uses the {preset} preset; pick a different one.")
    kept = atomic.read_json(folder / "overrides.json") or {}
    with _one_at_a_time(folder):
        started = runs_ops.start(project, folder / "spec.md", {**kept, "preset": preset}, who=who)
    title = f"Restart the build on the {preset} preset"
    events.emit("repair.applied", project=project, run=run_id, who=who, note="restart-on-preset", title=title,
                steps=[f"restart on preset {preset}"], new_run=started["run_id"], preset=preset,
                check_before=[], check_after=[], forced=False, rolled_back=False)
    common.record_command(who, f"repair restart {run_id} {preset}", project,
                          f"restarted run {run_id} on preset {preset} as {started['run_id']}")
    return {"run_id": run_id, "project": project, "new_run_id": started["run_id"], "preset": preset}
