"""The runner service's heartbeat: HOME/runner/heartbeat.json {at, pid}, written every loop round and
every 30 s by a side thread (so a long step does not look like a dead runner). status.py reads it: a
run that says running while the heartbeat is older than STALE_S shows "worker not responding".

The heartbeat proves progress, not just a live process. The service loop marks progress (`mark_progress`)
every round, at every step start and end, and while it waits (usage limit, update hold); a step's
container counts as progress for as long as it runs (`busy()`, held by DockerRunner.run, which has its own
time limit). The side thread only refreshes the heartbeat while `making_progress()`: progress in the last
PROGRESS_WINDOW_S seconds, or a container running now. A loop hung anywhere else stops the heartbeat, so
it shows "Worker not responding" too."""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager

from phoenix9 import atomic, paths

STALE_S = 120
TICK_S = 30
PROGRESS_WINDOW_S = 600          # 10 minutes without progress (and no container running) = a hung loop

_lock = threading.Lock()
_last_progress: float | None = None     # time.monotonic() of the loop's last progress, None = none yet
_busy = 0                               # containers running now (a running step is progress)


def mark_progress(at: float | None = None) -> None:
    """The service loop moved (a round, a step started or ended, a wait ticked). `at` is time.monotonic()."""
    global _last_progress
    with _lock:
        _last_progress = time.monotonic() if at is None else at


@contextmanager
def busy():
    """Inside this block a step's container is running: that counts as progress until it ends."""
    global _busy
    with _lock:
        _busy += 1
    try:
        yield
    finally:
        with _lock:
            _busy -= 1
        mark_progress()


def busy_count() -> int:
    """How many containers are running now under busy()."""
    with _lock:
        return _busy


def making_progress(now: float | None = None) -> bool:
    """True while a container runs, or the loop marked progress in the last PROGRESS_WINDOW_S seconds."""
    now = time.monotonic() if now is None else now
    with _lock:
        if _busy > 0:
            return True
        return _last_progress is not None and now - _last_progress <= PROGRESS_WINDOW_S


def reset_progress() -> None:
    """Forget all progress (tests, and a fresh service start)."""
    global _last_progress, _busy
    with _lock:
        _last_progress, _busy = None, 0


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
    """Start a daemon thread that, every interval_s seconds until `stop` is set, writes the heartbeat when
    the loop is making progress (`making_progress`); a hung loop gets no beat and soon looks not responding.
    The file is chosen once, at start, so the thread never writes anywhere else later."""
    stop = stop or threading.Event()
    path = _file()

    def tick():
        while not stop.is_set():
            if making_progress():
                write(clock.now(), path)
            stop.wait(interval_s)
    thread = threading.Thread(target=tick, name="phoenix-heartbeat", daemon=True)
    thread.start()
    return thread
