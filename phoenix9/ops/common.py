"""Shared pieces of the ops layer: the plain-words error, project lookup and the command record."""
import json
from datetime import datetime, timezone

from phoenix9 import adapters as adapters_mod, events, paths, scrub
from phoenix9.library import Library, load_library


class OpsError(Exception):
    """Something Phoenix refused or could not do; the message is plain words for Alex."""


def make_adapters():
    """The adapters ops use for outside things (real ones; tests replace this function)."""
    return adapters_mod.real()


def library() -> Library:
    """The step library of the running copy."""
    return load_library(paths.library())


def project_dir(name: str):
    """The folder of an existing project; OpsError when there is none."""
    if not name or "/" in name or name.startswith("."):
        raise OpsError(f"'{name}' is not a project name.")
    folder = paths.projects() / name
    if not folder.is_dir():
        raise OpsError(f"There is no project called '{name}'.")
    return folder


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _append_changelog(project: str, who: str, change: str) -> None:
    """Add one '- <date> · <who> · <words>' line to the project's notes/changelog.md."""
    folder = paths.projects() / project
    if not folder.is_dir():
        return
    notes = folder / "notes"
    notes.mkdir(exist_ok=True)
    with open(notes / "changelog.md", "a", encoding="utf-8") as f:
        f.write(scrub.scrub(f"- {_today()} · {who} · {change}\n"))


def record_command(who: str, command: str, project: str | None = None, change: str | None = None) -> None:
    """Write the command event and commands.jsonl line; for a change also add a changelog line."""
    events.emit("command", project=project, who=who, command=command)
    line = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "who": who,
            "command": command, "project": project}
    paths.logs().mkdir(parents=True, exist_ok=True)
    with open(paths.logs() / "commands.jsonl", "a", encoding="utf-8") as f:
        f.write(scrub.scrub(json.dumps(line)) + "\n")
    if change and project:
        _append_changelog(project, who, change)
