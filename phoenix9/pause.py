"""Pause now: the pause request file and the plain-words rules for pausing and resuming a run.

The runner holds the run lock while it walks a run, so a pause from outside leaves a request file
(`pause-request.json`) instead; the runner reads it after a stopped AI session and at the next step start.
"""
from __future__ import annotations

import re
from pathlib import Path

from phoenix9 import atomic, state

RESUME_LINE = "You were paused mid-step. Check the files you were changing, then carry on."
# A Claude session id is a UUID; anything else is never looked up or passed to `--resume`.
SESSION_ID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
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


def valid_session_id(session_id) -> bool:
    """True when `session_id` is a plain UUID (the only form Claude Code uses)."""
    return isinstance(session_id, str) and SESSION_ID.fullmatch(session_id) is not None


def drop_stale(run_dir, project: str, run_id: str, why: str) -> bool:
    """Throw away a pause request the run can no longer act on (it ended, or it waits or was queued, so no
    step of it is running); an event says so. Returns True when there was one."""
    from phoenix9 import events
    asked = requested(run_dir)
    if asked is None:
        return False
    clear(run_dir)
    events.emit("run.pause.dropped", project=project, run=run_id, who=asked.get("who") or "cli", reason=why)
    return True


def session_file(attempt_dir, session_id: str, role: str = "") -> Path | None:
    """The saved Claude session file for this id under the attempt's claude/<role>/ folder, or None.

    Only a UUID session id is looked up; any other value gives None (the step restarts clean)."""
    if not valid_session_id(session_id):
        return None
    root = Path(attempt_dir) / "claude"
    if role:
        root = root / role
    if not root.is_dir():
        return None
    return next((p for p in root.rglob(f"{session_id}.jsonl") if p.is_file() and not p.is_symlink()), None)
