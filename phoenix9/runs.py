"""Runs: make a run folder from a spec, find runs, list them newest first."""
import re
from datetime import datetime, timezone
from pathlib import Path

from . import atomic, events, paths, spec as spec_mod, state


def slugify(text: str, limit: int = 30) -> str:
    """Lowercase letters, digits and single dashes, at most limit characters."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit].strip("-")
    return slug or "run"


def new_run_id(spec_title: str, now: datetime | None = None) -> str:
    """A run id: YYYYMMDD-HHMMSS-<spec-slug> in UTC."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo:
        now = now.astimezone(timezone.utc)
    return f"{now:%Y%m%d-%H%M%S}-{slugify(spec_title)}"


def run_dir(project: str, run_id: str) -> Path:
    """The folder of one run."""
    return paths.runs(project) / run_id


def _tasks_from_spec(parsed) -> dict:
    return {str(t.number): {"title": t.title, "status": "pending", "tries": 0, "failures": [],
                            "depends_on": list(t.depends_on)} for t in parsed.tasks}


def create_run(project: str, spec_path: Path, overrides: dict | None = None) -> Path:
    """Make a queued run: read-only spec copy, state.json, run.queued event; returns the run folder."""
    text = Path(spec_path).read_text(encoding="utf-8")
    parsed = spec_mod.parse(text)
    title = parsed.title or Path(spec_path).stem
    base = new_run_id(title)
    run_id, k = base, 1
    while find_run(run_id):  # same second: ids stay unique across all projects
        k += 1
        run_id = f"{base}-{k}"
    folder = run_dir(project, run_id)
    folder.mkdir(parents=True)
    atomic.write_text(folder / "spec.md", text, mode=0o444)
    if overrides:
        atomic.write_json(folder / "overrides.json", overrides)
    atomic.write_json(folder / "state.json", state.new_state(run_id, project, _tasks_from_spec(parsed)))
    events.emit("run.queued", project=project, run=run_id, title=title)
    return folder


def _summary(s: dict) -> dict:
    tasks = s.get("tasks", {})
    return {"run_id": s["run_id"], "project": s["project"], "status": s["status"],
            "created": s["created"], "updated": s["updated"], "current": s.get("current"),
            "tasks_total": len(tasks),
            "tasks_passed": sum(1 for t in tasks.values() if t["status"] == "passed"),
            "usage": s.get("usage")}


def list_runs(project: str | None = None) -> list[dict]:
    """Summaries of runs (one project or all), newest first."""
    root = paths.runs(project) if project else paths.runs()
    if not root.is_dir():
        return []
    folders = [root] if project else [p for p in root.iterdir() if p.is_dir()]
    found = []
    for proj in folders:
        for d in proj.iterdir():
            s = atomic.read_json(d / "state.json") if d.is_dir() else None
            if s:
                found.append(_summary(s))
    return sorted(found, key=lambda r: (r["created"], r["run_id"]), reverse=True)


def find_run(run_id: str) -> Path | None:
    """The folder of the run with this id in any project, or None."""
    root = paths.runs()
    if not root.is_dir():
        return None
    for proj in sorted(root.iterdir()):
        d = proj / run_id
        if (d / "state.json").is_file():
            return d
    return None
