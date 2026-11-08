"""Card: a run's repair summary (status line, findings) and a proposed repair note with its dry-run result."""
import tempfile
from pathlib import Path

from phoenix9 import atomic, runs as core
from phoenix9.ops import common
from phoenix9.repair import apply as apply_mod, check as check_mod, notes, snapshot

schema = {"project": "str", "run": "str", "note": "str"}


def _find(project: str, run: str) -> Path:
    """The run folder, or NotFound."""
    folder = core.find_run(run)
    if folder is None or folder.parent.name != project:
        raise common.NotFound(f"There is no run called '{run}' in project '{project}'.")
    return folder


def _note_file(folder: Path, name: str | None) -> Path | None:
    """The named note (a file name in repairs/notes), or the newest one; None when there is none."""
    root = snapshot.repairs_dir(folder) / "notes"
    if name:
        if "/" in name or "\\" in name or name.startswith("."):
            raise common.OpsError("'note' is a file name in the run's repairs/notes folder.")
        path = root / name
        if not path.is_file():
            raise common.NotFound(f"There is no note called '{name}' for this run.")
        return path
    found = sorted(root.glob("*.md"), key=lambda p: (p.stat().st_mtime, p.name)) if root.is_dir() else []
    return found[-1] if found else None


def _dry_run(folder: Path, text: str, who: str) -> dict:
    """The dry-run outcome of note text, run on a scratch copy of the note; {error} when it cannot run."""
    try:
        notes.parse(text)
        with tempfile.TemporaryDirectory(prefix="phoenix-card-") as tmp:
            scratch = Path(tmp) / "note.md"
            atomic.write_text(scratch, text)
            return apply_mod.apply(scratch, who, dry_run=True)
    except (notes.NoteError, snapshot.RepairRefused) as err:
        return {"error": str(err)}


def _status_line(state_status: str, problems: list) -> str:
    """One plain sentence about the run."""
    if not problems:
        return f"The run is {state_status}; the check found nothing wrong."
    word = "problem" if len(problems) == 1 else "problems"
    return f"The run is {state_status}; the check found {len(problems)} {word}."


def build(query: dict) -> dict:
    """The card: data is {run_id, project, status, status_line, findings, note}; the buttons live in the body."""
    project, run = query.get("project"), query.get("run")
    if not project or not run:
        raise common.OpsError("A repair card needs 'project' and 'run'.")
    folder = _find(project, run)
    st = atomic.read_json(folder / "state.json", {}) or {}
    found = [{"code": f.code, "text": f.text, "task": f.task} for f in check_mod.run_checks(folder)]
    path = _note_file(folder, query.get("note"))
    note = None
    if path is not None:
        text = path.read_text(encoding="utf-8")
        note = {"name": path.name, "text": text, "dry_run": _dry_run(folder, text, "dashboard")}
    status = st.get("status", "unknown")
    data = {"run_id": run, "project": project, "status": status, "status_line": _status_line(status, found),
            "findings": found, "note": note}
    return {"title": f"Repair {run}", "data": data, "actions": [],
            "watch": {"projects": [project], "runs": [run], "types": ["run", "repair"]}}
