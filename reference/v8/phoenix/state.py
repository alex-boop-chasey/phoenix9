"""Safe file writes, a file lock, and small JSON helpers."""
from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path
from typing import Any


# Borrowed from Phoenix 0.6.0 hands/state.py:16-19
def atomic_write(path: Path, data: str) -> None:
    """Write text to a file so readers see either the old or the new file, never half of one."""
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(data)
    os.replace(tmp, path)


# Borrowed from Phoenix 0.6.0 hands/state.py:79-111
class Lock:
    """Hold an exclusive lock on a file while inside a `with` block.

    Waits up to 3 seconds for another holder, then stops with a message.
    """

    def __init__(self, path: Path):
        self.path = path
        self.fd = None

    def __enter__(self):
        self.fd = open(self.path, "w")
        deadline = time.monotonic() + 3      # Lock.held() probes hold it for microseconds
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.monotonic() > deadline:
                    self.fd.close()
                    raise SystemExit(f"another runner holds {self.path}")
                time.sleep(0.1)

    def __exit__(self, *a):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        self.fd.close()

    @staticmethod
    def held(path: Path) -> bool:
        """Return True if someone else holds the lock on this file right now."""
        if not path.exists():
            return False
        with open(path, "a") as fd:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fd, fcntl.LOCK_UN)
                return False
            except BlockingIOError:
                return True


def load_json(path: Path, default: Any) -> Any:
    """Read a JSON file. Return `default` if the file does not exist or is empty."""
    path = Path(path)
    if not path.exists():
        return default
    text = path.read_text()
    if not text.strip():
        return default
    return json.loads(text)


def save_json(path: Path, data: Any) -> None:
    """Write data as pretty JSON, atomically."""
    atomic_write(Path(path), json.dumps(data, indent=2, sort_keys=True) + "\n")
