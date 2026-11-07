"""The project chat hand-over for `on_failure = "delegate"` (architecture 9 and 11, rule 1 exception).

This is the ONLY place in phoenix9 that starts Claude on the host. It starts one detached, headless
`claude -p` session in the project folder, with full permissions (bypassPermissions), and walks away: the runner never talks to it again. The session either answers
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
    """The command line: headless, plain-text output, full permissions; never --bare (rule 7)."""
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


def agent_restart(adapters, why: str) -> None:
    """Restart the Phoenix agent's systemd service (the `agent.unit` setting) and tell Alex why, once."""
    from phoenix9 import scrub, settings
    unit = settings.agent_settings()["unit"]
    adapters.host.systemctl("restart", unit)
    adapters.notify.send(scrub.scrub(f"Phoenix agent restarted: {why}"))


def chat_unit(project: str) -> str:
    """The systemd unit that holds a project's chat connection; refuses any name that is not a listed project."""
    from phoenix9 import project as project_mod
    if not isinstance(project, str) or project not in project_mod.project_names():
        raise ValueError(f"not a listed project: {project!r}")
    return f"claude-rc-chat@{project}"


def unit_state(host, project: str) -> str:
    """The chat unit's state: active, activating, inactive or failed (anything else reads as inactive)."""
    _, out, _ = host.systemctl("is-active", chat_unit(project))
    word = out.strip().splitlines()[0] if out.strip() else ""
    return word if word in ("active", "activating", "inactive", "failed") else "inactive"


def unit_main_pid(host, project: str) -> int | None:
    """The chat unit's main process id, or None when it is not running."""
    rc, out, _ = host.systemctl("show", "-p", "MainPID", "--value", chat_unit(project))
    try:
        pid = int(out.strip()) if rc == 0 else 0
    except ValueError:
        pid = 0
    return pid or None


def start_unit(host, project: str) -> None:
    """Enable and start the project's chat unit; a plain NotReady-style error when systemd refuses."""
    rc, _out, err = host.systemctl("enable", "--now", chat_unit(project))
    if rc != 0:
        from phoenix9.projectchat import NotReady
        first = (err or "").strip().splitlines()[0] if (err or "").strip() else "systemctl exit %d" % rc
        raise NotReady("Phoenix couldn't start the chat service %s: %s" % (chat_unit(project), first))


def stop_unit(host, project: str) -> None:
    """Disable and stop the project's chat unit."""
    host.systemctl("disable", "--now", chat_unit(project))


def stop_conversation(host, project: str, pid: int) -> None:
    """Send SIGTERM to a conversation process, only if it is the unit's main process's direct child or a
    registry entry for this project; raises ValueError for any other pid."""
    from phoenix9 import agentlink, paths
    chat_unit(project)
    main = unit_main_pid(host, project)
    if main is not None and host.parent_pid(pid) == main:
        return host.stop_pid(pid)
    live = agentlink._live_in(host, agentlink.CLAUDE_HOME, str(paths.projects() / project))
    if any(e["pid"] == pid for e in live):
        return host.stop_pid(pid)
    raise ValueError(f"process {pid} is not a conversation of project {project}")
