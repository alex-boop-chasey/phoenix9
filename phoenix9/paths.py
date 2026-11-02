"""Where Phoenix keeps things on disk (docs/architecture.md section 3). Env vars override defaults."""
import os
from pathlib import Path


def home() -> Path:
    """Phoenix's own state folder (config, secrets, keys, runs, logs)."""
    return Path(os.environ.get("PHOENIX_HOME", "/var/lib/phoenix9"))


def projects() -> Path:
    """The folder holding every project workspace."""
    return Path(os.environ.get("PHOENIX_PROJECTS", "/srv/projects"))


def install() -> Path:
    """The installed copy of Phoenix that actually runs (written only by the updater)."""
    return Path(os.environ.get("PHOENIX_INSTALL", "/opt/phoenix9"))


def library() -> Path:
    """The folder holding steps/, presets/, profiles/, services/, deployers/, templates/."""
    return Path(os.environ.get("PHOENIX_LIBRARY", Path(__file__).resolve().parent.parent))


def config() -> Path:
    """Non-secret global settings."""
    return home() / "config"


def secrets() -> Path:
    """Global secret files (owner-only)."""
    return home() / "secrets"


def keys() -> Path:
    """Per-project key files (owner-only)."""
    return home() / "keys"


def cache() -> Path:
    """Recomputable data (project folder sizes)."""
    return home() / "cache"


def runs(project: str | None = None) -> Path:
    """All run folders, or one project's run folders."""
    return home() / "runs" / project if project else home() / "runs"


def work(project: str, run_id: str) -> Path:
    """The git worktree a run builds in."""
    return home() / "work" / project / run_id


def logs() -> Path:
    """Global logs (commands, updater, api)."""
    return home() / "logs"


def events() -> Path:
    """The global event stream."""
    return home() / "events.jsonl"


VSCODE_URL = "https://files.rebirthwebdesign.com.au/"
