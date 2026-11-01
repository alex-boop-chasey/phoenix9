"""The project chat hand-over for `on_failure = "delegate"` (architecture 9 and 11, rule 1 exception).

This is the ONLY place in phoenix9 that starts Claude on the host. It starts one detached, headless
`claude -p` session in the project folder, with the same permissions as the project's own chat service
(claude-rc@<project>), and walks away: the runner never talks to it again. The session either answers
the escalation gate itself (`phoenix gate answer <id> acknowledged --who chat:delegate`) or gives up.
"""
from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

WHO = "chat:delegate"
_started: dict[str, subprocess.Popen] = {}   # sessions this process started, by handle (pid)


def command(prompt: str) -> list[str]:
    """The command line: headless, plain-text output, project-chat permissions; never --bare (rule 7)."""
    return ["claude", "-p", prompt, "--permission-mode", "bypassPermissions", "--output-format", "text"]


def delegate(project: str, project_dir, gate: str, prompt: str, log_path) -> dict:
    """Start the session in the background. Returns {"started", "handle", "error"}; never raises."""
    log_path = Path(log_path)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "ab") as log:
            proc = subprocess.Popen(command(prompt), cwd=str(project_dir), stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                    env={**os.environ, "PHOENIX_WHO": WHO})
    except (OSError, ValueError) as err:
        return {"started": False, "handle": "", "error": f"{type(err).__name__}: {err}"}
    handle = str(proc.pid)
    _started[handle] = proc
    return {"started": True, "handle": handle, "error": ""}


def reap() -> None:
    """Collect every finished session this process started, so none lingers as a zombie process."""
    for handle, proc in list(_started.items()):
        if proc.poll() is not None:
            del _started[handle]


def stop(handle: str) -> None:
    """Stop a still-running session (its whole process group); quiet if it already ended."""
    reap()
    proc = _started.get(str(handle))
    try:
        pid = proc.pid if proc is not None else int(handle)
        if status(handle) == "running":
            os.killpg(pid, signal.SIGTERM)
    except (OSError, ValueError):
        pass


def status(handle: str) -> str:
    """"running" or "exited". A handle this process does not know (e.g. after a restart) is looked up
    by process id; if no such process is alive it counts as exited."""
    reap()
    proc = _started.get(str(handle))
    if proc is not None:
        return "running"
    try:
        stat = Path(f"/proc/{int(handle)}/stat").read_text()
    except (OSError, ValueError):
        return "exited"
    return "exited" if stat.rsplit(")", 1)[-1].split()[0] == "Z" else "running"
