"""The agent watchdog: restarts the Phoenix agent's service when it stays down (never touches builds)."""
from __future__ import annotations

from phoenix9 import agentlink, atomic, chat, paths, settings

BAD_CHECKS_NEEDED = 2     # bad checks in a row before a restart
BACKOFF_S = 600           # wait this long after a restart before trying again


def memory_path():
    """The file that holds what the watchdog remembers between checks."""
    return paths.logs() / "agent-watch.json"


def _load() -> dict:
    """The remembered {bad, last_restart, stopped}; fresh values when the file is missing or odd."""
    data = atomic.read_json(memory_path(), {})
    data = data if isinstance(data, dict) else {}
    bad, last = data.get("bad"), data.get("last_restart")
    return {"bad": bad if isinstance(bad, int) and bad >= 0 else 0,
            "last_restart": last if isinstance(last, (int, float)) else None,
            "stopped": data.get("stopped") is True}


def memory() -> dict:
    """What the watchdog remembers (for doctor): {bad, last_restart, stopped}."""
    return _load()


def stopped_on_purpose(adapters, unit: str) -> bool:
    """True when systemd says the unit is inactive and ended cleanly (Result=success): someone stopped it."""
    rc, out, _ = adapters.host.systemctl("show", "-p", "ActiveState", "-p", "Result", unit)
    if rc != 0:
        return False
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    return props.get("ActiveState") == "inactive" and props.get("Result") == "success"


def problem(adapters, unit: str) -> str:
    """Why the agent looks down ("the service is not active", "no agent session"), or "" when healthy."""
    rc, _out, _err = adapters.host.systemctl("is-active", unit)
    if rc != 0:
        return f"the service {unit} is not active"
    if agentlink.find(host=adapters.host) is None:
        return "no agent session is running"
    return ""


def _backing_off(mem: dict, now: float) -> bool:
    """True when a restart happened less than BACKOFF_S ago."""
    last = mem["last_restart"]
    return last is not None and not now - last >= BACKOFF_S


def check_once(adapters) -> str:
    """One watchdog check; returns "off", "ok", "bad", "backoff", "restarted", "restarted-rules"
    (healthy and idle, restarted once to load updated rules) or "stopped" (the unit was stopped
    on purpose: recorded and left alone until it runs again)."""
    cfg = settings.agent_settings()
    if not cfg["watchdog"]:
        return "off"
    mem = _load()
    now = adapters.clock.now()
    why = problem(adapters, cfg["unit"])
    result = "ok"
    if why and why.startswith("the service") and stopped_on_purpose(adapters, cfg["unit"]):
        mem["bad"], mem["stopped"] = 0, True
        result = "stopped"
    elif why:
        mem["stopped"] = False
        mem["bad"] += 1
        result = "bad"
        if mem["bad"] >= BAD_CHECKS_NEEDED:
            if _backing_off(mem, now):
                result = "backoff"
            else:
                mem["last_restart"] = now
                mem["bad"] = 0
                chat.agent_restart(adapters, why)
                result = "restarted"
    else:
        mem["bad"], mem["stopped"] = 0, False
        if restart_for_rules(adapters):
            mem["last_restart"] = now
            result = "restarted-rules"
    atomic.write_json(memory_path(), mem)
    return result


def restart_for_rules(adapters) -> bool:
    """When updated agent rules wait for a restart (HOME/agent-rules-pending) and the agent is idle, restart it
    once, clear the note and record an event; True when it restarted."""
    from phoenix9 import agentsync, events
    if not agentsync.pending_restart():
        return False
    if agentlink.status(host=adapters.host)["state"] != "idle":
        return False
    chat.agent_restart(adapters, "its rules were updated")
    agentsync.clear_pending()
    events.emit("agent.restarted_for_rules", project=None, why="updated agent rules were waiting for an idle agent")
    return True
