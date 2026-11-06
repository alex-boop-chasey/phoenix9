"""The runner service's heartbeat: HOME/runner/heartbeat.json {at, pid}, written every loop round and
every 30 s by a side thread (so a long step does not look like a dead runner). status.py reads it: a
run that says running while the heartbeat is older than STALE_S shows "worker not responding"."""
from __future__ import annotations

import os
import threading

from phoenix9 import atomic, paths

STALE_S = 120
TICK_S = 30


def _file():
    return paths.home() / "runner" / "heartbeat.json"


def write(at: float, path=None) -> None:
    """Record that the runner service is alive at time `at` (seconds since 1970); a write problem is ignored."""
    path = path or _file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic.write_json(path, {"at": float(at), "pid": os.getpid()})
    except OSError:
        pass


def read() -> dict | None:
    """The last heartbeat {at, pid}, or None when the runner never wrote one."""
    return atomic.read_json(_file())


def age(now: float) -> float | None:
    """Seconds since the last heartbeat, or None when there is none."""
    beat = read()
    if not beat or not isinstance(beat.get("at"), (int, float)):
        return None
    return max(0.0, now - float(beat["at"]))


def is_stale(now: float) -> bool:
    """True when there is no heartbeat, or it is older than STALE_S seconds."""
    seconds = age(now)
    return seconds is None or seconds > STALE_S


def start_ticker(clock, interval_s: float = TICK_S, stop: threading.Event | None = None) -> threading.Thread:
    """Start a daemon thread that writes the heartbeat every interval_s seconds until `stop` is set.
    The file is chosen once, at start, so the thread never writes anywhere else later."""
    stop = stop or threading.Event()
    path = _file()

    def tick():
        while not stop.is_set():
            write(clock.now(), path)
            stop.wait(interval_s)
    thread = threading.Thread(target=tick, name="phoenix-heartbeat", daemon=True)
    thread.start()
    return thread
