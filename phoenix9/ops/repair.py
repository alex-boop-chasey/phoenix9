"""Ops for the repair kit: undo a repair of a run."""
from phoenix9 import runs as core
from phoenix9.ops import common
from phoenix9.repair import snapshot


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
