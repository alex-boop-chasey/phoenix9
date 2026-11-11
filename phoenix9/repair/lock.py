"""A per-run repair lock: only one repair at a time may change a run."""
import contextlib
import os
import time
from pathlib import Path

LOCK_NAME = ".lock"
STALE_SECONDS = 600
BUSY = "Another repair on this run is still going; try again when it has finished."


class Busy(Exception):
    """Another repair holds the lock of this run."""


def lock_path(run_dir: Path) -> Path:
    """Return the lock file of a run (in its repairs folder)."""
    return Path(run_dir) / "repairs" / LOCK_NAME


def _drop_if_stale(path: Path) -> None:
    """Remove a lock file that is older than the stale time (its repair must have died)."""
    try:
        if time.time() - path.stat().st_mtime > STALE_SECONDS:
            path.unlink()
    except FileNotFoundError:
        pass


def _create(path: Path) -> None:
    """Create the lock file exclusively; Busy when it already exists."""
    try:
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    except FileExistsError:
        raise Busy(BUSY) from None


@contextlib.contextmanager
def held(run_dir: Path):
    """Hold the repair lock of a run for the block; Busy when another repair is going."""
    path = lock_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    _drop_if_stale(path)
    _create(path)
    try:
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
