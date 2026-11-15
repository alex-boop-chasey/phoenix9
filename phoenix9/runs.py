"""Runs: make a run folder from a spec, find runs, list them newest first."""
import re
from datetime import datetime, timezone
from pathlib import Path

from . import atomic, events, git as git_mod, paths, proc, refsnapshot, scrub, spec as spec_mod, state


def slugify(text: str, limit: int = 30) -> str:
    """Lowercase letters, digits and single dashes, at most limit characters."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit].strip("-")
    return slug or "run"


RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[a-z0-9-]+$")  # what new_run_id makes (YYYYMMDD-HHMMSS-slug)


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


def create_run(project: str, spec_path: Path, overrides: dict | None = None, reference_from: Path | None = None) -> Path:
    """Make a queued run: read-only spec copy, state.json, run.queued event; returns the run folder.

    With `reference_from` (an earlier run's folder) the run gets a copy of that run's frozen reference folder
    instead of a fresh snapshot of the project's."""
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
    if reference_from is not None:
        refsnapshot.copy_from(Path(reference_from), folder)
    else:
        refsnapshot.snapshot(project, folder)
    return folder


def _summary(s: dict) -> dict:
    tasks = s.get("tasks", {})
    return {"run_id": s["run_id"], "project": s["project"], "status": s["status"],
            "created": s["created"], "updated": s["updated"], "current": s.get("current"),
            "tasks_total": len(tasks),
            "tasks_passed": sum(1 for t in tasks.values() if t["status"] == "passed"),
            "usage": s.get("usage"), "discarded": bool(s.get("discarded")),
            "failed_at": s.get("failed_at") if s["status"] == "failed" else None}


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
    """The folder of the run with this id in any project, or None (also for an id that is not a run id, or a
    folder that resolves outside the runs folder, for example through a symlink)."""
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        return None
    root = paths.runs()
    if not root.is_dir():
        return None
    top = root.resolve()
    for proj in sorted(root.iterdir()):
        d = proj / run_id
        if (d / "state.json").is_file() and d.resolve().parent.parent == top and d.resolve().name == run_id:
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


STOPPED_PATCH = "stopped-work.patch"


def _newest_try_patch(run_dir: Path) -> Path | None:
    """The newest try's saved changes (tasks/*/attempt-*/diff.patch), or None."""
    found = [p for p in run_dir.glob("tasks/*/attempt-*/diff.patch") if p.is_file() and p.stat().st_size]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def save_stopped_work(git, code: Path, work: Path, run_dir: Path) -> list[str]:
    """Save the worktree's changes since it branched (committed or not) as stopped-work.patch; returns notes."""
    notes = []
    base = git.git(work, "merge-base", git.default_branch(code), "HEAD").strip()
    text = git.diff_text(work, base, binary=True)
    if text.strip():
        clean = scrub.scrub(text)
        path = run_dir / STOPPED_PATCH
        atomic.write_text(path, clean, mode=0o600)
        notes.append(f"The build's unfinished changes are saved in {path} (apply with: git apply {path}).")
        masked = sum(a != b for a, b in zip(text.splitlines(), clean.splitlines()))
        if masked:
            notes.append(f"{masked} line{'s' if masked != 1 else ''} that looked like a secret "
                         f"{'were' if masked != 1 else 'was'} masked in it.")
    last = _newest_try_patch(run_dir)
    if last is not None:
        notes.append(f"The last try's changes: {last}")
    return notes


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
            try:
                notes += save_stopped_work(git, code, work, paths.runs(project) / run_id)
            except Exception as err:
                notes.append(f"the build's unfinished changes could not be saved: {err}")
            git.remove_worktree(code, work)
        git.git(code, "branch", "-D", branch, check=False)
        if git.remote_url(code) and git.git(code, "rev-parse", "-q", "--verify", f"refs/remotes/origin/{branch}", check=False).strip():
            what = "Deleting the build's branch on GitHub"
            result = adapters.host.run(["git", *git_mod.SAFE, "-C", str(code), "push", "origin", "--delete", branch],
                                       timeout=120, what=what)
            if result[0] != 0:
                notes.append(f"the branch {branch} was not deleted on GitHub ({proc.failure_text(what, result)})")
    except Exception as err:
        notes.append(f"the run's branch was not cleaned up: {err}")
    return notes


def tidy_branch(adapters, project: str, run_id: str, merged_head: str) -> tuple[list[str], list[str]]:
    """Remove a merged run's worktree, local branch and GitHub branch; returns (what was removed, notes), never raises.

    The GitHub branch is deleted only while its tip is still the merged commit `merged_head`."""
    code, removed, notes = paths.projects() / project / "code", [], []
    if not (code / ".git").exists():
        return removed, notes
    git = adapters.git
    try:
        branch = git.branch_name(run_id)
        work = paths.work(project, run_id)
        if work.exists():
            git.remove_worktree(code, work)
            removed.append("worktree")
        if git.git(code, "rev-parse", "-q", "--verify", f"refs/heads/{branch}", check=False).strip():
            git.git(code, "branch", "-D", branch, check=False)
            removed.append("local branch")
        if git.remote_url(code):
            what = "Asking GitHub whether the build's branch is still there"
            result = adapters.host.run(["git", *git_mod.SAFE, "-C", str(code), "ls-remote", "--heads", "origin",
                                        f"refs/heads/{branch}"], timeout=120, what=what)
            rc, out, _ = result
            tip = out.split()[0] if rc == 0 and out.strip() else ""
            if rc != 0:
                notes.append(f"GitHub did not say whether the branch {branch} is still there, so it was left alone "
                             f"({proc.failure_text(what, result)})")
            elif tip and tip != merged_head:
                notes.append(f"the branch {branch} on GitHub has commits added after the merge, so it was kept")
            elif tip:
                what = "Deleting the build's branch on GitHub"
                deleted = adapters.host.run(["git", *git_mod.SAFE, "-C", str(code), "push", "origin", "--delete", branch],
                                            timeout=120, what=what)
                rc = deleted[0]
                if rc == 0:
                    removed.append("GitHub branch")
                else:
                    notes.append(f"the branch {branch} was not deleted on GitHub ({proc.failure_text(what, deleted)})")
            if rc == 0 and not tip:
                git.git(code, "branch", "-D", "-r", f"origin/{branch}", check=False)
    except Exception as err:
        notes.append(f"the run's branch was not cleaned up: {err}")
    return removed, notes
