"""A run's state.json: file lock, load, safe update, and helpers for status, tasks and step lines."""
import fcntl
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import atomic

RUN_STATUSES = ("queued", "running", "waiting", "paused-limit", "done", "failed", "stopped")
TASK_STATUSES = ("pending", "running", "passed", "failed", "skipped", "waiting")
STEP_STATUSES = ("pending", "running", "passed", "failed", "skipped", "waiting")


# ported from reference/v8/phoenix/state.py:79 (Lock)
class Lock:
    """Hold an exclusive lock on a file while inside a `with` block; waits a while, then gives up."""

    def __init__(self, path: Path, wait: float = 10.0):
        self.path = Path(path)
        self.wait = wait
        self.fd = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = open(self.path, "a")
        deadline = time.monotonic() + self.wait
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.monotonic() > deadline:
                    self.fd.close()
                    raise TimeoutError(f"could not get the lock on {self.path}")
                time.sleep(0.02)

    def __exit__(self, *a):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        self.fd.close()

    @staticmethod
    def held(path: Path) -> bool:
        """True if someone else holds the lock on this file right now."""
        if not Path(path).exists():
            return False
        with open(path, "a") as fd:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fd, fcntl.LOCK_UN)
                return False
            except BlockingIOError:
                return True


def now() -> str:
    """The current UTC time as an ISO string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_state(run_id: str, project: str, tasks: dict | None = None) -> dict:
    """A fresh state.json body with status queued."""
    stamp = now()
    return {"run_id": run_id, "project": project, "status": "queued", "created": stamp, "updated": stamp,
            "current": {"group": None, "task": None, "step": None, "attempt": None, "gate": None},
            "tasks": tasks or {}, "steps": [], "usage": {"cost_usd": 0.0, "sessions": 0}}


def new_task(title: str = "", depends_on=()) -> dict:
    """A fresh task entry. Old state files may lack the later fields, so readers use .get().

    tries = the attempt being worked on (0 = not started); failures = every reason so far, fed to the
    next attempt; escalations = how many times Alex (or the project chat) acknowledged it;
    flagged = why it failed, shown on the Build tab; gate = the open gate it waits on;
    attempt_base = the commit each attempt starts from (failed attempts are reset to it);
    delegate = the project chat hand-over (handle, started_at, notified); note = why it was skipped;
    rerun = an escalation was acknowledged, so the next attempt runs whatever should_retry says.
    """
    return {"title": title, "status": "pending", "tries": 0, "failures": [], "depends_on": list(depends_on),
            "escalations": 0, "flagged": "", "gate": None, "attempt_base": None, "delegate": None, "note": "",
            "rerun": False}


def _file(run_dir: Path) -> Path:
    return Path(run_dir) / "state.json"


def load(run_dir: Path) -> dict:
    """Read the run's state.json."""
    return atomic.read_json(_file(run_dir))


def _check(value: str, allowed: tuple, what: str) -> None:
    if value not in allowed:
        raise ValueError(f"bad {what} status {value!r}; use one of {', '.join(allowed)}")


def _validate(state: dict) -> None:
    _check(state["status"], RUN_STATUSES, "run")
    for n, t in state.get("tasks", {}).items():
        _check(t["status"], TASK_STATUSES, f"task {n}")
    for line in state.get("steps", []):
        _check(line["status"], STEP_STATUSES, "step")


def update(run_dir: Path, fn: Callable[[dict], None]) -> dict:
    """Under the lock: load state, let fn change it, check it, save it, and bump `updated`."""
    with Lock(Path(run_dir) / "state.lock"):
        state = load(run_dir)
        fn(state)
        _validate(state)
        state["updated"] = now()
        atomic.write_json(_file(run_dir), state)
    return state


def set_status(run_dir: Path, status: str) -> dict:
    """Set the run's status."""
    _check(status, RUN_STATUSES, "run")
    return update(run_dir, lambda s: s.__setitem__("status", status))


def set_task(run_dir: Path, n: int, **fields) -> dict:
    """Change fields of task n (created if missing, status pending)."""
    def change(s):
        task = s["tasks"].setdefault(str(n), new_task())
        task.update(fields)
    return update(run_dir, change)


def add_step_line(run_dir: Path, group: str | None, task: int | None, step: str,
                  status: str = "pending", note: str = "", attempt: int | None = None) -> int:
    """Append a step line and return its index. Task steps get one line per attempt."""
    _check(status, STEP_STATUSES, "step")
    line = {"group": group, "task": task, "step": step, "status": status,
            "started": now() if status == "running" else None, "finished": None, "note": note}
    if attempt is not None:
        line["attempt"] = attempt
    state = update(run_dir, lambda s: s["steps"].append(line))
    return len(state["steps"]) - 1


def set_step_line(run_dir: Path, index: int, **fields) -> dict:
    """Change fields of the step line at index; stamps started/finished when the status says so."""
    def change(s):
        line = s["steps"][index]
        status = fields.get("status")
        if status == "running" and not line.get("started"):
            line["started"] = now()
        if status in ("passed", "failed", "skipped") and not line.get("finished"):
            line["finished"] = now()
        line.update(fields)
    return update(run_dir, change)
