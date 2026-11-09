"""Quick edits: a small change made in a branch copy (worktree) of one project's code/, never on main."""
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from . import atomic, events, git as git_mod, paths, runs, state

BUSY_RUN = ("queued", "running", "waiting", "paused-limit", "paused")   # run statuses that count as a build on the project
SKIP = {".git"}


STALL_SECONDS = 30 * 60      # no activity for this long marks an open edit stalled


class EditError(Exception):
    """A quick edit was refused or could not be done; the message is plain words."""

    def __init__(self, message: str, problems: list[str] | None = None):
        """Keep the message and, for a failed finish, the list of problems."""
        super().__init__(message)
        self.problems = problems or []


def edits_dir() -> Path:
    """The folder holding every quick edit's worktree and record."""
    return paths.home() / "edits"


def record_file(edit_id: str) -> Path:
    """The record file of one quick edit."""
    return edits_dir() / f"{edit_id}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _valid_id(edit_id: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]*", edit_id or ""))


def load(edit_id: str) -> dict:
    """Read one quick edit's record; EditError when there is none."""
    data = atomic.read_json(record_file(edit_id)) if _valid_id(edit_id) else None
    if not data:
        raise EditError(f"There is no quick edit called '{edit_id}'.")
    return data


def newest_change(folder: Path) -> str:
    """The time of the newest file change in the folder (ignoring .git), or '' when it is empty."""
    newest = 0.0
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for name in files:
            try:
                newest = max(newest, os.lstat(os.path.join(root, name)).st_mtime)
            except OSError:
                continue
    if not newest:
        return ""
    return datetime.fromtimestamp(newest, timezone.utc).isoformat(timespec="seconds")


def _with_activity(rec: dict) -> dict:
    """The record with last_activity moved up to the newest file change of an open edit."""
    if rec.get("status") == "open" and Path(rec["folder"]).is_dir():
        rec = dict(rec, last_activity=max(rec.get("last_activity", ""), newest_change(Path(rec["folder"]))))
    return rec


def list_edits(project: str | None = None, only_open: bool = False) -> list[dict]:
    """Quick edits (one project or all), newest first."""
    found = []
    for f in sorted(edits_dir().glob("*.json")) if edits_dir().is_dir() else []:
        rec = atomic.read_json(f)
        if not rec or (project and rec.get("project") != project) or (only_open and rec.get("status") != "open"):
            continue
        found.append(_with_activity(rec))
    return sorted(found, key=lambda r: (r["started"], r["id"]), reverse=True)


def open_edit(project: str) -> dict | None:
    """The open quick edit of a project, or None."""
    found = list_edits(project, only_open=True)
    return found[0] if found else None


def build_running(project: str) -> str | None:
    """The id of a run still going on the project, or None."""
    for r in runs.list_runs(project):
        if r["status"] in BUSY_RUN:
            return r["run_id"]
    return None


def _new_id(title: str, now: datetime) -> str:
    base = f"{now:%Y%m%d}-{runs.slugify(title, 30)}"
    edit_id, n = base, 1
    while record_file(edit_id).exists() or (edits_dir() / edit_id).exists():
        n += 1
        edit_id = f"{base}-{n}"
    return edit_id


def start(project: str, title: str, who: str = "cli") -> dict:
    """Make the worktree and record for a new quick edit; refuse when one is open or a build runs."""
    title = (title or "").strip()
    if not title:
        raise EditError("Say what the quick edit is for (--title).")
    code = paths.projects() / project / "code"
    if not code.is_dir():
        raise EditError(f"The project '{project}' has no code/ folder to edit.")
    with state.Lock(paths.project_lock(project), wait=10.0):
        current = open_edit(project)
        if current:
            raise EditError(f"{project} already has an open quick edit ({current['id']}). Finish or abandon it first.")
        busy = build_running(project)
        if busy:
            raise EditError(f"A build is running on {project} ({busy}). Wait for it to end first.")
        now = datetime.now(timezone.utc)
        edit_id = _new_id(title, now)
        branch, folder = f"edit/{edit_id}", edits_dir() / edit_id
        try:
            folder.parent.mkdir(parents=True, exist_ok=True)
            git_mod.git(code, "worktree", "add", "-q", "-b", branch, "--", str(folder), git_mod.default_branch(code))
        except git_mod.GitError as err:
            raise EditError(f"I could not make the branch copy: {err}") from None
        rec = {"id": edit_id, "project": project, "title": title, "branch": branch, "folder": str(folder),
               "started": _now(), "who": who, "status": "open", "last_activity": _now()}
        atomic.write_json(record_file(edit_id), rec)
    events.emit("edit.started", project=project, edit=edit_id, branch=branch, title=title, who=who)
    return rec


def heartbeat(edit_id: str) -> dict:
    """Record that work is going on in an open quick edit now."""
    rec = load(edit_id)
    if rec["status"] not in ("open", "stalled"):
        raise EditError(f"The quick edit {edit_id} is {rec['status']}, not open.")
    rec.update(status="open", last_activity=_now())
    atomic.write_json(record_file(edit_id), rec)
    return rec


def finish(edit_id: str, message: str | None = None, adapters=None, who: str = "cli") -> dict:
    """Check an open quick edit like a build does, then commit, push, open a merge request and remove its folder.

    Any failed check raises EditError listing every problem; the edit stays open."""
    from . import editfinish
    if adapters is None:
        from .ops import common
        adapters = common.make_adapters()
    rec = load(edit_id)
    if rec["status"] not in ("open", "stalled"):
        raise EditError(f"The quick edit {edit_id} is {rec['status']}, not open.")
    problems, changes = editfinish.check(adapters, rec)
    if problems:
        raise EditError("The quick edit is not ready:\n" + "\n".join(f"- {p}" for p in problems), problems)
    try:
        link = editfinish.publish(adapters, rec, (message or "").strip() or rec["title"], changes)
    except RuntimeError as err:
        raise EditError(str(err), [str(err)]) from None
    code = paths.projects() / rec["project"] / "code"
    git_mod.remove_worktree(code, Path(rec["folder"]))
    rec.update(status="finished", pr=link, last_activity=_now())
    atomic.write_json(record_file(edit_id), rec)
    events.emit("edit.finished", project=rec["project"], edit=edit_id, branch=rec["branch"], pr=link, who=who)
    return rec


def mark_stalled(now: float | None = None) -> list[str]:
    """Mark open quick edits with no activity for 30 minutes as stalled (nothing is deleted); return their ids."""
    now = datetime.now(timezone.utc) if now is None else datetime.fromtimestamp(now, timezone.utc)
    marked = []
    for rec in list_edits(only_open=True):
        last = datetime.fromisoformat(rec["last_activity"])
        if (now - last).total_seconds() >= STALL_SECONDS:
            rec.update(status="stalled")
            atomic.write_json(record_file(rec["id"]), rec)
            events.emit("edit.stalled", project=rec["project"], edit=rec["id"], branch=rec["branch"])
            marked.append(rec["id"])
    return marked


def abandon(edit_id: str) -> dict:
    """Remove the quick edit's worktree and local branch, and mark it abandoned."""
    rec = load(edit_id)
    if rec["status"] == "abandoned":
        raise EditError(f"The quick edit {edit_id} is already abandoned.")
    code = paths.projects() / rec["project"] / "code"
    git_mod.remove_worktree(code, Path(rec["folder"]))
    git_mod.run_git(code, "branch", "-D", "--", rec["branch"], check=False)
    rec.update(status="abandoned", last_activity=_now())
    atomic.write_json(record_file(edit_id), rec)
    events.emit("edit.abandoned", project=rec["project"], edit=edit_id, branch=rec["branch"])
    return rec
