"""Removing a project from Phoenix and importing one back (nothing is ever deleted)."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from phoenix9 import atomic, events, git, paths, project, settings, tomlw
from phoenix9.ops import common
from phoenix9.ops.common import Conflict, NotFound, OpsError

PROTECTED = {"phoenix9": "phoenix9 is Phoenix itself, so it cannot be removed.",
             project.HOME_PROJECT: "home is the front door, so it cannot be removed."}


def removed_list() -> list:
    """The removed-projects list from Phoenix's global config: [{name, path, repo, removed_on}]."""
    rows = settings.read_global().get("removed_projects")
    return [r for r in rows if isinstance(r, dict) and r.get("name")] if isinstance(rows, list) else []


def removed_names() -> set:
    """The names of the removed projects."""
    return {r["name"] for r in removed_list()}


def _save_removed(rows: list) -> None:
    """Write the removed-projects list back into global.toml, keeping the other settings."""
    data = dict(settings.read_global())
    data.pop("removed_projects", None)
    if rows:
        data["removed_projects"] = rows
    tomlw.dump(paths.config() / "global.toml", data)


def untrust(host, folder: Path) -> None:
    """Undo project.trust: drop the trust entry for the folder from Claude Code's settings."""
    path = project.claude_json()
    try:
        data = json.loads(host.read_text(path))
    except (FileNotFoundError, ValueError):
        return
    entries = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return
    changed = False
    for where in {str(folder), os.path.realpath(folder)}:
        entry = entries.get(where)
        if isinstance(entry, dict) and "hasTrustDialogAccepted" in entry:
            del entry["hasTrustDialogAccepted"]
            changed = True
            if not entry:
                del entries[where]
    if changed:
        host.write_text(path, json.dumps(data, indent=2))


def _folder_repo(folder: Path) -> str:
    """The repo of a folder: recorded, else the origin of code/ or of the folder itself."""
    repo = project.repo_of(folder)
    if not repo and (folder / ".git").exists():
        repo = git.remote_url(folder)
    return repo


def remove(name: str, who: str, adapters) -> dict:
    """Take a project off Phoenix's list and its chat out of the Claude app; keeps every file."""
    if name in PROTECTED:
        raise OpsError(PROTECTED[name])
    folder = common.project_dir(name)
    if name in removed_names():
        raise Conflict(f"{name} is already removed.")
    host = adapters.host
    host.systemctl("disable", "-q", "--now", project.unit(name))
    untrust(host, folder)
    row = {"name": name, "path": str(folder), "repo": _folder_repo(folder),
           "removed_on": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
    _save_removed([r for r in removed_list() if r["name"] != name] + [row])
    events.emit("project.changed", project=name, who=who, what="removed")
    common.record_command(who, f"project remove {name}", name,
                          change="removed from Phoenix (chat switched off; files kept)")
    return {"name": name, "path": row["path"], "repo": row["repo"] or None, "removed_on": row["removed_on"],
            "kept": "The folder, notes, code, repo and keys are untouched."}


def candidates() -> list:
    """Removed projects, then unlisted folders: [{name, path, repo, removed_on, kind}]."""
    out = [{"name": r["name"], "path": r.get("path") or str(paths.projects() / r["name"]),
            "repo": r.get("repo") or None, "removed_on": r.get("removed_on"), "kind": "removed"}
           for r in removed_list()]
    root = paths.projects()
    skip = removed_names()
    for folder in sorted(root.iterdir()) if root.is_dir() else []:
        if (not folder.is_dir() or folder.name.startswith(".") or folder.name in skip
                or (folder / "CLAUDE.md").is_file() or not project.NAME_RE.match(folder.name)):
            continue
        out.append({"name": folder.name, "path": str(folder), "repo": _folder_repo(folder) or None,
                    "removed_on": None, "kind": "folder"})
    return out


def _find(name_or_path: str) -> str:
    """The project name for a name or a path; the folder must sit directly in the projects folder."""
    text = (name_or_path or "").strip()
    if not text:
        raise OpsError("Say which project: a name or a folder path.")
    if "/" not in text:
        return text
    path = Path(text).expanduser()
    if path.parent.resolve() != paths.projects().resolve():
        raise OpsError(f"{text} is not inside {paths.projects()}. Projects live directly in that folder.")
    return path.name


def _add_missing(path: Path, text: str) -> bool:
    """Write the file only if it does not exist yet; True when written."""
    if path.exists() or path.is_symlink():
        return False
    atomic.write_text(path, text)
    return True


def add_standard_files(folder: Path, name: str, repo: str) -> list:
    """Add the standard workspace files that are missing (never overwrites); returns what was added."""
    added = []
    notes = folder / "notes"
    for sub in project.NOTES_SUBFOLDERS:
        (notes / sub).mkdir(parents=True, exist_ok=True)
    today = common._today()
    files = {
        "CLAUDE.md": f"# {name}\n\n{name}: an existing project brought into Phoenix.\n\n- Code: code/\n"
                     f"- Repo: {repo or '(none yet)'}\n\n@notes/NOW.md\n",
        "notes/NOW.md": f"# Now ({name})\n\n- {today}: imported into Phoenix; next: first chat refines CLAUDE.md.\n",
        "notes/decisions.md": f"# Decisions ({name})\n\n",
        "notes/changelog.md": f"# Changelog ({name})\n\nPlain-English log of every change, newest last: date · who "
                              "(chat, subagent, grunt, Phoenix) · what.\n\n"}
    for rel, text in files.items():
        if _add_missing(folder / rel, text):
            added.append(rel)
    meta = folder / ".phoenix" / "project.json"
    if not meta.exists():
        atomic.write_json(meta, {"created": today, "who": "import", "source": "import", "template": None,
                                 "profile": None, "repo": repo or None, "code": "code/",
                                 "chat_session_url": None, "environment_id": None, "services_set_up": []})
        added.append(".phoenix/project.json")
    return added


def import_(name_or_path: str, who: str, adapters) -> dict:
    """Bring a removed project or an unlisted folder into Phoenix (no chat service is started)."""
    name = _find(name_or_path)
    folder = paths.projects() / name
    if not folder.is_dir():
        raise NotFound(f"There is no folder called '{name}' to import.")
    if name in PROTECTED:
        raise OpsError(PROTECTED[name])
    was_removed = name in removed_names()
    if (folder / "CLAUDE.md").is_file() and not was_removed:
        raise Conflict(f"{name} is already in Phoenix.")
    if not project.NAME_RE.match(name):
        raise OpsError(f"'{name}' is not a good project name: use lowercase letters, digits and dashes (up to 41).")
    repo = _folder_repo(folder)
    added = add_standard_files(folder, name, repo)
    _save_removed([r for r in removed_list() if r["name"] != name])
    project.trust(adapters.host, folder)
    project.mark_used(name)
    events.emit("project.changed", project=name, who=who, what="imported")
    common.record_command(who, f"project import {name}", name,
                          change="imported into Phoenix (no chat service)")
    return {"name": name, "path": str(folder), "repo": repo or None, "was_removed": was_removed,
            "added": added, "chat": "off"}
