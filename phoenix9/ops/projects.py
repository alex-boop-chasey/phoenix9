"""Ops for projects: list, show, edit, open, close, set-chat, new and the templates menu."""
from phoenix9.ops import common

ACTIVE_RUN = ("queued", "running", "waiting", "paused-limit")


def list_() -> list:
    """Every project (a folder with a CLAUDE.md) with its full info, by name."""
    from phoenix9 import project
    return project.list_projects(common.make_adapters())


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


def open_(name: str, who: str) -> dict:
    """Switch a project's chat server on."""
    from phoenix9 import project
    common.project_dir(name)
    return project.open_project(name, common.make_adapters(), who)


def close(name: str, who: str, force: bool = False) -> dict:
    """Switch a project's chat server off."""
    from phoenix9 import project
    common.project_dir(name)
    return project.close_project(name, common.make_adapters(), who, force)


def set_chat(name: str, url: str, who: str) -> dict:
    """Save a project's chat session link."""
    from phoenix9 import project
    common.project_dir(name)
    return project.set_chat(name, url, who)


def new(opts: dict, who: str, progress=None) -> dict:
    """Create a project from the form; `progress` gets one plain line per creation step."""
    from phoenix9 import project
    return project.create(opts, common.make_adapters(), who, progress)


def templates_menu() -> list:
    """The templates a new project can start from."""
    from phoenix9 import templates
    return [{k: t[k] for k in ("name", "title", "profile", "kind", "check")} for t in templates.load_menu()]


def rows() -> list:
    """The Projects page rows: every info field plus repo_url, needs_you and the active run."""
    from phoenix9 import gates, runs
    open_gates = gates.list_gates()
    active = {}
    for r in runs.list_runs():     # newest first, so the first match per project is the newest
        if r["status"] in ACTIVE_RUN and r["project"] not in active:
            active[r["project"]] = {"run_id": r["run_id"], "status": r["status"],
                                    "task": (r.get("current") or {}).get("task"), "tasks": r["tasks_total"]}
    out = []
    for row in list_():
        owner = row.get("repo_owner")
        out.append({**row, "repo_url": f"https://github.com/{owner}/{row['repo_name']}" if owner else None,
                    "needs_you": sum(1 for g in open_gates if g["project"] == row["name"]),
                    "run": active.get(row["name"])})
    return out


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
    """Markdown files under notes/specs and notes/plans: [{path, title, modified}], newest first."""
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
                          "modified": datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec="seconds"),
                          "_t": mtime})
    found.sort(key=lambda f: (f["_t"], f["path"]), reverse=True)
    return [{k: v for k, v in f.items() if k != "_t"} for f in found]
