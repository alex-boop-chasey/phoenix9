"""Ops for the repair kit: check a run, write its report, apply a repair note, undo a repair."""
from phoenix9 import events, runs as core
from phoenix9.ops import common
from phoenix9.repair import apply as apply_mod, check as check_mod, report as report_mod, resume as resume_mod, snapshot


def _run_folder(run_id: str, project: str | None = None):
    """The run folder for a run id (the id alone finds its project); NotFound when there is none."""
    folder = core.find_run(run_id)
    if folder is None or (project and folder.parent.name != project):
        raise common.NotFound(f"There is no run called '{run_id}'" + (f" in project '{project}'." if project else "."))
    return folder


def undo(run_id: str, to: int | None = None, who: str = "cli", project: str | None = None) -> dict:
    """Undo a repair: put the run back as snapshot `to` (default the newest) had it; refused while the runner walks it."""
    folder = _run_folder(run_id, project)
    try:
        done = snapshot.undo(folder, to=to, who=who)
    except (snapshot.RepairRefused, snapshot.SnapshotError) as err:
        raise common.OpsError(str(err)) from None
    return {"run_id": run_id, "project": folder.parent.name, **done}


def check(run_id: str, project: str | None = None) -> dict:
    """Check a run for broken state: {run_id, project, ok, problems: [{code, text, task}]}."""
    folder = _run_folder(run_id, project)
    found = check_mod.run_checks(folder)
    return {"run_id": run_id, "project": folder.parent.name, "ok": not found,
            "problems": [{"code": f.code, "text": f.text, "task": f.task} for f in found]}


def report(run_id: str, project: str | None = None) -> dict:
    """Write and return the run report: {run_id, project, path, text}."""
    folder = _run_folder(run_id, project)
    text = report_mod.write(folder)
    return {"run_id": run_id, "project": folder.parent.name, "path": str(report_mod.report_path(folder)), "text": text}


def apply(note_path: str, who: str = "cli", dry_run: bool = False, approve_unlock: bool = False) -> dict:
    """Apply a repair note to its run (or only show what it would do): the outcome, with the steps and both checks."""
    try:
        return apply_mod.apply(note_path, who, dry_run=dry_run, approve_unlock=approve_unlock)
    except snapshot.RepairRefused as err:
        raise common.OpsError(str(err)) from None


def resume(run_id: str, who: str = "cli", project: str | None = None) -> dict:
    """Resume a repaired run: snapshot it, move it to running (or queued), and record the repair."""
    folder = _run_folder(run_id, project)
    title = "Resume the run"
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
