"""The Phoenix agent's service restart, and each project's chat unit (architecture 8 and 11).

No AI runs in Phoenix's own processes (rule 1): this file only starts, stops and looks at systemd units
through the Host adapter, and never starts Claude (planning sessions run in step containers, plansession.py). A build that runs out of tries is handed to the agent with a message
(`failmodes.escalate` through `agentlink.send`), never with a session started here.
"""
from __future__ import annotations


def agent_restart(adapters, why: str) -> None:
    """Restart the Phoenix agent's systemd service (the `agent.unit` setting) and tell Alex why, once."""
    from phoenix9 import scrub, settings
    unit = settings.agent_settings()["unit"]
    adapters.host.systemctl("restart", unit)
    from phoenix9 import agentsync
    agentsync.clear_pending()
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
