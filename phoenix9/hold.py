"""The update hold: asks the runner to stop at its next task boundary, and tells whether it is busy.

The updater writes HOME/update/hold; the runner checks it between tasks and waits there (writing
`current.held = true`) until the hold is gone. A run counts as busy only while it is `running` and not
held. The hold counts only while the hold file exists AND an updater holds HOME/update/lock, so an
updater killed before it could clean up (its lock dies with it) never freezes the runner
(docs/architecture.md section 15).
"""
import fcntl
import time
from pathlib import Path

from phoenix9 import atomic, paths


def _file() -> Path:
    return paths.home() / "update" / "hold"


def lock_file() -> Path:
    """HOME/update/lock: an updater holds an exclusive flock on it while it runs."""
    return paths.home() / "update" / "lock"


def lock_held() -> bool:
    """True while some updater holds HOME/update/lock. Opens it read-only (the API may not run as
    root); a missing lock file means no update is running."""
    try:
        fd = open(lock_file(), "rb")
    except FileNotFoundError:
        return False
    except OSError:
        return True          # exists but cannot be read: assume an update holds it
    with fd:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False


def request_hold(why: str) -> None:
    """Ask every run to stop at its next task boundary (only counts while the update lock is held)."""
    atomic.write_json(_file(), {"why": why, "at": time.time()})


def release_hold() -> None:
    """Let held runs go on."""
    _file().unlink(missing_ok=True)


def hold_info() -> dict | None:
    """The hold file's contents ({why, at}) while a live hold exists, else None. Live = the file exists
    and an updater holds the lock; a damaged file counts as {"why": "update"}."""
    if not _file().exists() or not lock_held():
        return None
    try:
        data = atomic.read_json(_file())
    except (OSError, ValueError):
        return {"why": "update", "at": 0} if _file().exists() else None
    if data is None:         # released between the two looks
        return None
    return data if isinstance(data, dict) else {"why": "update", "at": 0}


def hold_requested() -> bool:
    """True while an update asks runs to hold at their next task boundary."""
    return hold_info() is not None


def _states() -> list[dict]:
    """Every run's state.json (unreadable ones skipped)."""
    found = []
    root = paths.runs()
    for project in sorted(root.iterdir()) if root.is_dir() else []:
        for run in sorted(project.iterdir()) if project.is_dir() else []:
            try:
                st = atomic.read_json(run / "state.json")
            except (OSError, ValueError):
                continue
            if isinstance(st, dict):
                found.append(st)
    return found


def _where(st: dict) -> str:
    """Plain words for where a running run is: "run X is on task 3 of 7"."""
    tasks = st.get("tasks") or {}
    running = [n for n, t in tasks.items() if (t or {}).get("status") == "running"]
    n = running[0] if running else (st.get("current") or {}).get("task")
    name = f"run {st.get('run_id')} ({st.get('project')})"
    if n is None:
        return f"{name} is running"
    return f"{name} is on task {n} of {len(tasks)}"


def harness_busy() -> tuple[bool, str]:
    """(True, reason) while some run is mid-task: status running and not held at a task boundary."""
    for st in _states():
        if st.get("status") == "running" and not (st.get("current") or {}).get("held"):
            return True, _where(st)
    return False, ""
