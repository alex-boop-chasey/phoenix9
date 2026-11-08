"""Pause now: the pause request file and the plain-words rules for pausing and resuming a run.

The runner holds the run lock while it walks a run, so a pause from outside leaves a request file
(`pause-request.json`) instead; the runner reads it after a stopped AI session and at the next step start.
"""
from __future__ import annotations

from pathlib import Path

from phoenix9 import atomic, state

RESUME_LINE = "You were paused mid-step. Check the files you were changing, then carry on."
CLEAN_NOTE = "Restarted clean from the start of the try: the paused session could not be continued."


def _file(run_dir) -> Path:
    return Path(run_dir) / "pause-request.json"


def request(run_dir, who: str) -> dict:
    """Leave a pause request for the runner."""
    data = {"who": who, "at": state.now()}
    atomic.write_json(_file(run_dir), data)
    return data


def requested(run_dir) -> dict | None:
    """The run's pause request, or None."""
    return atomic.read_json(_file(run_dir))


def clear(run_dir) -> None:
    """Remove the pause request (the run paused, resumed or ended)."""
    _file(run_dir).unlink(missing_ok=True)


def session_file(attempt_dir, session_id: str) -> Path | None:
    """The saved Claude session file for this id under the attempt's claude/ folder, or None."""
    if not session_id or "/" in session_id or session_id.startswith("."):
        return None
    root = Path(attempt_dir) / "claude"
    return next(iter(root.rglob(f"{session_id}.jsonl")), None) if root.is_dir() else None
