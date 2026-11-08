"""Resume a repaired run: put a failed or stopped run back to running (or queued) so the runner carries on."""
import tempfile
from pathlib import Path

from phoenix9 import atomic, events, paths, runend, state
from phoenix9.repair import check, snapshot
from phoenix9.repair.snapshot import RepairRefused

RESUMABLE = ("failed", "stopped", "running")     # running: only reached with a stale heartbeat (dead runner)
BUSY_ELSEWHERE = ("running", "waiting", "paused-limit")


def _others_busy(run_dir: Path) -> list[str]:
    """The ids of other runs on the server that are running or waiting."""
    root = paths.runs()
    busy = []
    for proj in sorted(root.iterdir()) if root.is_dir() else []:
        for d in sorted(proj.iterdir()) if proj.is_dir() else []:
            if d.is_dir() and d != run_dir and (atomic.read_json(d / "state.json") or {}).get("status") in BUSY_ELSEWHERE:
                busy.append(d.name)
    return busy


def _flip(s: dict) -> None:
    """Change a state dict as resuming does: running (queued if never started), no gate, no error."""
    s["status"] = "queued" if never_started(s) else "running"
    s.setdefault("current", {})["gate"] = None
    s.pop("error", None)


def _problems_after_flip(run_dir: Path) -> str:
    """The check of the run as it will be once resumed (done on a scratch copy), in words; empty when it passes."""
    with tempfile.TemporaryDirectory(prefix="phoenix-resume-") as tmp:
        scratch = Path(tmp) / run_dir.parent.name / run_dir.name
        snapshot.scratch_copy(run_dir, scratch)
        state.update(scratch, _flip)
        return " ".join(f.text for f in check.run_checks(scratch, as_run=run_dir))


def refusal(run_dir) -> str | None:
    """Why the run cannot be resumed now, in plain words, or None when it can."""
    run_dir = Path(run_dir)
    st = state.load(run_dir) or {}
    if st.get("status") not in RESUMABLE:
        return f"The run is {st.get('status')}; only a failed or stopped run can be resumed."
    others = _others_busy(run_dir)
    if others:
        return "Another run is running or waiting on the server (" + ", ".join(others) + "); only one run can go at a time."
    found = _problems_after_flip(run_dir)
    return f"The run still has problems: {found}" if found else None


def never_started(st: dict) -> bool:
    """True when no task of the run has been started, so the run can go through the normal queue."""
    return all(t.get("status") in ("pending", "skipped") and not t.get("tries") for t in st["tasks"].values())


def resume_locked(run_dir, who: str) -> str:
    """With the run lock held: refuse or move the run to running (queued if it never started); return the new status."""
    run_dir = Path(run_dir)
    snapshot.refuse_if_walking(run_dir, lock_ok=True)
    why = refusal(run_dir)
    if why:
        raise RepairRefused(why)
    st = state.update(run_dir, _flip)
    runend._request_file(run_dir).unlink(missing_ok=True)
    events.emit("run.started", project=st["project"], run=st["run_id"], who=who, resumed=True)
    return st["status"]


def resume(run_dir, who: str) -> str:
    """Resume a run under the run lock; refused while the runner walks it."""
    run_dir = Path(run_dir)
    snapshot.refuse_if_walking(run_dir)
    try:
        with runend.lock(run_dir, wait=snapshot.LOCK_WAIT_S):
            return resume_locked(run_dir, who)
    except TimeoutError:
        raise RepairRefused(snapshot.WALKING_MESSAGE) from None
