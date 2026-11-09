"""Ops for projects: list, show, edit, new, remove, import and the templates menu."""
from pathlib import Path

from phoenix9 import paths
from phoenix9.ops import common

AGENT_FOLDER_TEXT = "This is the Phoenix agent's folder, not a project."


def agent_name() -> str:
    """The folder name of the Phoenix agent's own folder (from the agent settings; 'home' by default)."""
    from pathlib import PurePosixPath
    from phoenix9 import settings
    return PurePosixPath(settings.agent_settings()["folder"].rstrip("/")).name


def list_(names: list | None = None, include_agent: bool = False) -> list:
    """Every project (a folder with a CLAUDE.md) except the agent's folder unless include_agent, or just `names`."""
    from phoenix9 import project
    if names is None:
        names = [n for n in project.project_names() if include_agent or n != agent_name()]
    return project.list_projects(common.make_adapters(), names=names)


list = list_


def show(name: str) -> dict:
    """All info of one project, plus recent changelog lines and open gates."""
    from phoenix9 import project
    common.project_dir(name)
    return project.show_project(name, common.make_adapters())


def edit(name: str, who: str, description=None, profile=None, repo=None) -> dict:
    """Change a project's description, profile or repo."""
    from phoenix9 import project
    common.project_dir(name)
    return project.edit(name, common.make_adapters(), who, description, profile, repo)


def set_services(name: str, names: list, who: str) -> dict:
    """Choose a project's services (adds empty key rows and allowed hosts)."""
    from phoenix9 import project_services
    common.project_dir(name)
    return project_services.set_services(name, names, who)


def new(opts: dict, who: str, progress=None) -> dict:
    """Create a project from the form; `progress` gets one plain line per creation step."""
    from phoenix9 import project
    return project.create(opts, common.make_adapters(), who, progress)


def delete_plan(name: str, who: str) -> dict:
    """The dry run for deleting a project entirely: what would go and what refuses it; changes nothing."""
    from phoenix9 import project_delete
    plan = project_delete.plan(name, who, common.make_adapters())
    common.record_command(who, f"project delete {name} --dry-run", name)
    return plan


def delete(name: str, confirm_name: str, who: str) -> dict:
    """Delete a project entirely after a safety copy; returns the steps and what was not done."""
    from phoenix9 import project_delete
    return project_delete.delete(name, confirm_name, who, common.make_adapters())


def delete_repo(name: str, who: str) -> dict:
    """Retry only the GitHub repo delete of an already deleted project."""
    from phoenix9 import project_delete
    common.record_command(who, f"project delete-repo {name}", name)
    return project_delete.delete_repo(name, who, common.make_adapters())


def remove(name: str, who: str) -> dict:
    """Remove a project from Phoenix's list; every file is kept."""
    from phoenix9 import project_removal
    return project_removal.remove(name, who, common.make_adapters())


def import_candidates() -> list:
    """Projects that can be imported: removed ones, and folders Phoenix does not list yet."""
    from phoenix9 import project_removal
    return project_removal.candidates()


def import_(name_or_path: str, who: str) -> dict:
    """Bring a removed project or an unlisted folder into Phoenix and add its missing workspace files."""
    from phoenix9 import project_removal
    return project_removal.import_(name_or_path, who, common.make_adapters())


def check_files(name: str | None, who: str) -> list:
    """Add the missing memory files to one project, or to every listed project when name is None."""
    from phoenix9 import project, project_removal
    names = [name] if name else project.project_names()
    return [project_removal.check_files(n, who) for n in names]


def list_folders(path: str = "") -> dict:
    """The sub-folders of a folder under the projects root: {path, parent, folders: [{name, path}]}."""
    root = paths.projects().resolve()
    text = (path or "").strip()
    here = (Path(text).expanduser() if text else root)
    if not here.is_absolute():
        here = root / here
    here = here.resolve()
    if here != root and root not in here.parents:
        raise common.OpsError(f"{text} is not inside {root}. Only folders under the projects folder can be browsed.")
    if not here.is_dir():
        raise common.NotFound(f"{text} is not a folder.")
    folders = []
    for child in sorted(here.iterdir(), key=lambda c: c.name.lower()):
        if child.name.startswith(".") or not child.is_dir():
            continue
        real = child.resolve()
        if real != root and root not in real.parents:      # a symlink that leaves the projects folder
            continue
        folders.append({"name": child.name, "path": str(here / child.name)})
    return {"path": str(here), "root": str(root), "parent": str(here.parent) if here != root else None,
            "folders": folders}


def templates_menu() -> list:
    """The templates a new project can start from."""
    from phoenix9 import templates
    return [{k: t[k] for k in ("name", "title", "profile", "kind", "check")} for t in templates.load_menu()]


STATE_KEYS = ("needs_you", "questions", "run", "last_build_failed", "activity", "status_line", "run_text", "harness",
              "worker")


def rows(only: str | None = None, include_agent: bool = False) -> list:
    """The Projects page rows (just project `only` when given): every info field plus repo_url and the
    project's state from status.project_state (needs_you, questions, run, last_build_failed, activity,
    status_line, run_text, harness, worker)."""
    from phoenix9 import status
    found = list_([only] if only else None, include_agent)
    states = status.all_project_states([r["name"] for r in found], {r["name"]: r.get("last_used") or "" for r in found})
    adapters = common.make_adapters()
    out = []
    agent = agent_work([r["name"] for r in found])
    for row in found:
        owner = row.get("repo_owner")
        out.append({**row, "repo_url": f"https://github.com/{owner}/{row['repo_name']}" if owner else None,
                    **states[row["name"]], "chat": chat_or_none(row["name"], adapters),
                    **agent[row["name"]]})
    return out


def agent_work(names: list) -> dict:
    """For each project, its open or stalled quick edit and its running or waiting planning session (or None)."""
    from phoenix9 import edits, plans
    out = {n: {"edit": None, "plan": None} for n in names}
    for e in edits.list_edits():
        if e.get("project") in out and e.get("status") in ("open", "stalled") and not out[e["project"]]["edit"]:
            out[e["project"]]["edit"] = {"id": e["id"], "title": e.get("title", ""), "status": e["status"]}
    for p in plans.list_plans():
        if p.get("project") in out and p.get("status") in ("queued", "running", "waiting") and not out[p["project"]]["plan"]:
            brief = (p.get("brief") or "").strip().splitlines()
            out[p["project"]]["plan"] = {"id": p["id"], "title": brief[0][:80] if brief else "", "status": p["status"]}
    return out


def chat_or_none(name: str, adapters) -> dict | None:
    """The project's chat state for its row, or None when it cannot be read."""
    from phoenix9 import projectchat
    try:
        return projectchat.state(name, adapters)
    except Exception:
        return None


STATUSES = ("all", "run", "fail", "idle", "need")
SORTS = ("name", "active", "size", "created", "modified")
SKIP_DIRS = (".git", "node_modules", ".venv", "__pycache__")


def state_of(row: dict) -> str:
    """A row's state in one word (need, run, fail or idle), as status.project_state worked it out."""
    return row.get("activity") or "idle"


def created_at(row: dict) -> float:
    """When the project was created: the date in .phoenix/project.json, else that file's change time (0 if unknown)."""
    import datetime
    import json
    meta_file = Path(row["path"]) / ".phoenix" / "project.json"
    try:
        made = json.loads(meta_file.read_text(encoding="utf-8")).get("created")
        if made:
            return datetime.datetime.fromisoformat(str(made)).timestamp()
    except (OSError, ValueError):
        pass
    try:
        return meta_file.stat().st_mtime
    except OSError:
        return 0.0


def modified_at(row: dict) -> float:
    """When the project last changed: the latest of its last run, its changelog and its project files."""
    import os
    folder = Path(row["path"])
    latest = float(row.get("last_used_at") or 0)
    try:
        latest = max(latest, (folder / "notes" / "changelog.md").stat().st_mtime)
    except OSError:
        pass
    for here, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            try:
                latest = max(latest, os.stat(os.path.join(here, f), follow_symlinks=False).st_mtime)
            except OSError:
                pass
    return latest


def _sorted(found: list, sort: str) -> list:
    """Rows in the chosen order: name, recently active, largest, newest created or most recently modified."""
    if sort == "active":
        return sorted(found, key=lambda r: (-(r.get("last_used_at") or 0), r["name"]))
    if sort == "size":
        return sorted(found, key=lambda r: (-(r.get("size") or 0), r["name"]))
    if sort == "created":
        return sorted(found, key=lambda r: (-created_at(r), r["name"]))
    if sort == "modified":
        return sorted(found, key=lambda r: (-modified_at(r), r["name"]))
    return sorted(found, key=lambda r: r["name"])


def query(q: str = "", status: str = "all", owner: str = "all", sort: str = "name", attention: bool = False,
          include_agent: bool = False) -> dict:
    """Search, filter and sort the rows: {top, rest, total, counts}; counts ignore the status choice."""
    if status not in STATUSES:
        raise common.OpsError(f"'{status}' is not a status. Use one of: {', '.join(STATUSES)}.")
    if sort not in SORTS:
        raise common.OpsError(f"'{sort}' is not a sort order. Use one of: {', '.join(SORTS)}.")
    needle = (q or "").strip().lower()
    owner = owner or "all"
    matched = []
    for r in (rows(include_agent=True) if include_agent else rows()):
        if needle and needle not in f"{r['name']} {r['description']}".lower():
            continue
        if owner == "none" and r["repo"]:
            continue
        if owner not in ("all", "none") and r.get("repo_owner") != owner:
            continue
        matched.append(r)
    counts = {"all": len(matched), "run": 0, "fail": 0, "idle": 0, "need": 0}
    for r in matched:
        counts[state_of(r)] += 1
    found = _sorted([r for r in matched if status == "all" or state_of(r) == status], sort)
    top = [r for r in found if state_of(r) == "need"] if attention else []
    rest = [r for r in found if r not in top]
    return {"top": top, "rest": rest, "total": len(found), "counts": counts}


def row(name: str) -> dict:
    """One Projects page row (as `rows`) for an existing project."""
    common.project_dir(name)
    found = next((r for r in rows(only=name) if r["name"] == name), None)
    if found is None:
        raise common.NotFound(f"There is no project called '{name}'.")
    return found


def check_name(name: str) -> dict:
    """Say whether a new project name is usable: {ok, message}."""
    from phoenix9 import paths, project
    if not project.NAME_RE.match(name or ""):
        return {"ok": False, "message": f"'{name}' is not a good project name: use lowercase letters, digits and dashes (up to 41)."}
    if (paths.projects() / name).exists():
        return {"ok": False, "message": f"A project called '{name}' already exists."}
    return {"ok": True, "message": "This name is free."}


def changelog(name: str, limit: int = 20) -> list:
    """The last `limit` changelog lines as [{date, who, text}], newest last."""
    folder = common.project_dir(name)
    try:
        lines = (folder / "notes" / "changelog.md").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in (x for x in lines if x.startswith("- ")):
        parts = line[2:].split(" · ", 2)
        if len(parts) == 3:
            out.append({"date": parts[0], "who": parts[1], "text": parts[2]})
        else:
            out.append({"date": "", "who": "", "text": line[2:]})
    return out[-limit:] if limit > 0 else []


def specs(name: str) -> list:
    """Markdown files under notes/specs and notes/plans: [{path, title, modified, task_format}], newest first.

    `task_format` is True when the file passes the strict spec check (else only the Planner can build from it)."""
    from phoenix9 import spec as spec_core
    from datetime import datetime, timezone
    notes = common.project_dir(name) / "notes"
    found = []
    for sub in ("specs", "plans"):
        for path in sorted((notes / sub).glob("**/*.md")) if (notes / sub).is_dir() else []:
            if not path.is_file() or path.is_symlink():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            title = next((x[2:].strip() for x in text.splitlines() if x.startswith("# ")), path.stem)
            mtime = path.stat().st_mtime
            found.append({"path": str(path.relative_to(notes)), "title": title,
                          "task_format": not spec_core.check(text),
                          "modified": datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec="seconds"),
                          "_t": mtime})
    found.sort(key=lambda f: (f["_t"], f["path"]), reverse=True)
    return [{k: v for k, v in f.items() if k != "_t"} for f in found]
