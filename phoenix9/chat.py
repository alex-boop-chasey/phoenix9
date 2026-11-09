"""The Phoenix agent's service restart, and each project's chat unit (architecture 8 and 11).

No AI runs in Phoenix's own processes (rule 1): this file only starts, stops and looks at systemd units
through the Host adapter. A build that runs out of tries is handed to the agent with a message
(`failmodes.escalate` through `agentlink.send`), never with a session started here.
"""
from __future__ import annotations


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


PLAN_TIMEOUT_S = 4 * 3600


def _plan_run(adapters, rec: dict, prompt: str, resume: str | None) -> dict:
    """Run the headless claude for a planning session in the project's folder and settle its record."""
    from phoenix9 import paths, plans, scrub
    out = plans.session_file(rec["id"])
    out.parent.mkdir(parents=True, exist_ok=True)
    argv = plans.build_argv(rec["model"], prompt, resume)
    rc, stdout, _err = adapters.host.run(argv, timeout=PLAN_TIMEOUT_S, cwd=paths.projects() / rec["project"])
    out.write_text(scrub.scrub(stdout or ""), encoding="utf-8")
    return plans.settle(rec, rc)


def plan_start(project: str, brief: str, model: str | None = None, adapters=None, who: str = "cli") -> dict:
    """Start a planning session: headless claude in the project's folder writing a spec in notes/specs/."""
    from phoenix9 import plans
    if adapters is None:
        from phoenix9.ops import common
        adapters = common.make_adapters()
    rec = plans.new_record(project, brief, model or plans.plan_model(), who)
    return _plan_run(adapters, rec, plans.start_prompt(brief), None)


def plan_continue(plan_id: str, adapters=None, who: str = "cli") -> dict:
    """Resume the same planning session so it reads the answers, updates the spec and records decisions."""
    from phoenix9 import events, plans
    if adapters is None:
        from phoenix9.ops import common
        adapters = common.make_adapters()
    rec = plans.load(plan_id)
    if rec["status"] == "running":
        raise plans.PlanError(f"The planning session {plan_id} is already running.")
    if not rec.get("session_id"):
        raise plans.PlanError(f"The planning session {plan_id} has no session to resume.")
    other = plans.running(rec["project"])
    if other:
        raise plans.PlanError(f"{rec['project']} already has a planning session running ({other['id']}).")
    rec.update(status="running", last_activity=plans._now())
    plans.save(rec)
    events.emit("plan.continued", project=rec["project"], plan=plan_id, who=who)
    return _plan_run(adapters, rec, plans.CONTINUE_PROMPT, rec["session_id"])
