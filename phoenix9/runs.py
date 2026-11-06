"""Runs: make a run folder from a spec, find runs, list them newest first."""
import re
from datetime import datetime, timezone
from pathlib import Path

from . import atomic, events, git as git_mod, paths, spec as spec_mod, state


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
    return {str(t.number): state.new_task(t.title, t.depends_on) for t in parsed.tasks}


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
            "usage": s.get("usage"), "discarded": bool(s.get("discarded"))}


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


def adopt_plan(run_dir, plan_path) -> int:
    """Use the approved plan's tasks: rewrite spec.json and reset state.json tasks to pending; returns the task count."""
    run_dir = Path(run_dir)
    parsed = spec_mod.parse(Path(plan_path).read_text(encoding="utf-8"))
    atomic.write_json(run_dir / "spec.json", spec_mod.to_json(parsed))
    tasks = _tasks_from_spec(parsed)
    state.update(run_dir, lambda s: s.__setitem__("tasks", tasks))
    return len(tasks)


def discard_branch(adapters, project: str, run_id: str) -> list[str]:
    """Delete a stopped run's worktree and branch (and its GitHub branch when pushed); returns notes, never raises."""
    code, notes = paths.projects() / project / "code", []
    if not (code / ".git").exists():
        return notes
    git = adapters.git
    try:
        branch = git.branch_name(run_id)
        work = paths.work(project, run_id)
        if work.exists():
            git.remove_worktree(code, work)
        git.git(code, "branch", "-D", branch, check=False)
        if git.remote_url(code) and git.git(code, "rev-parse", "-q", "--verify", f"refs/remotes/origin/{branch}", check=False).strip():
            rc, out, err = adapters.host.run(["git", *git_mod.SAFE, "-C", str(code), "push", "origin", "--delete", branch], timeout=120)
            if rc != 0:
                notes.append(f"the branch {branch} was not deleted on GitHub")
    except Exception as err:
        notes.append(f"the run's branch was not cleaned up: {err}")
    return notes
