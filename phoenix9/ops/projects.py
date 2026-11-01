"""Ops for projects (read-only for now): list them and show one."""
import json
import subprocess

from phoenix9 import paths
from phoenix9.ops import common


def _description(folder) -> str:
    """The first paragraph of the project's CLAUDE.md (heading lines skipped)."""
    try:
        text = (folder / "CLAUDE.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    for block in text.split("\n\n"):
        lines = [x.strip() for x in block.splitlines() if x.strip() and not x.lstrip().startswith("#")]
        if lines:
            return " ".join(lines)
    return ""


def _repo(folder) -> str:
    """The repo from .phoenix/project.json, else the git remote of code/, else ''."""
    try:
        recorded = json.loads((folder / ".phoenix" / "project.json").read_text(encoding="utf-8")).get("repo")
    except (OSError, ValueError, AttributeError):
        recorded = None
    if recorded:
        return str(recorded)
    code = folder / "code"
    if not code.is_dir():
        return ""
    try:
        done = subprocess.run(["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
                               "-C", str(code), "remote", "get-url", "origin"],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _facts(folder) -> dict:
    return {"name": folder.name, "path": str(folder), "description": _description(folder),
            "repo": _repo(folder), "has_phoenix_toml": (folder / "phoenix.toml").is_file()}


def list_() -> list:
    """Every project folder with its facts, by name."""
    root = paths.projects()
    if not root.is_dir():
        return []
    return [_facts(p) for p in sorted(root.iterdir()) if p.is_dir() and not p.name.startswith(".")]


def show(name: str) -> dict:
    """The facts of one project."""
    return _facts(common.project_dir(name))


list = list_
