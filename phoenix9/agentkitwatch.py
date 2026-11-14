"""The new agent's watchdog: restarts the phoenix-agentkit service when it stays down or stops answering."""
from __future__ import annotations

from phoenix9 import agentnext, atomic, paths, scrub, settings

UNIT = "phoenix-agentkit"
BAD_CHECKS_NEEDED = 2     # bad checks in a row before a restart
BACKOFF_S = 600           # wait this long after a restart before trying again
NOTICE = "Phoenix restarted the agent service: it was not answering."


def memory_path():
    """The file that holds what the watchdog remembers between checks."""
    return paths.logs() / "agentkit-watch.json"


def _load() -> dict:
    """The remembered {bad, last_restart, stopped}; fresh values when the file is missing or odd."""
    data = atomic.read_json(memory_path(), {})
    data = data if isinstance(data, dict) else {}
    bad, last = data.get("bad"), data.get("last_restart")
    return {"bad": bad if isinstance(bad, int) and not isinstance(bad, bool) and bad >= 0 else 0,
            "last_restart": last if isinstance(last, (int, float)) and not isinstance(last, bool) else None,
            "stopped": data.get("stopped") is True}


def memory() -> dict:
    """What the watchdog remembers (for doctor): {bad, last_restart, stopped}."""
    return _load()


def set_up() -> bool:
    """True when global.toml has an [agent_next] table (the new agent is installed)."""
    return isinstance(settings.read_global().get("agent_next"), dict)


def stopped_on_purpose(adapters) -> bool:
    """True when systemd says the unit is inactive and ended cleanly (Result=success): someone stopped it."""
    rc, out, _ = adapters.host.systemctl("show", "-p", "ActiveState", "-p", "Result", UNIT)
    if rc != 0:
        return False
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    return props.get("ActiveState") == "inactive" and props.get("Result") == "success"


def _active(adapters) -> bool:
    """True when systemd says the unit is active."""
    rc, out, _ = adapters.host.systemctl("is-active", UNIT)
    return rc == 0 and (out.split() or [""])[0] == "active"


def _answers(adapters) -> bool:
    """True when the agent service answers /status."""
    try:
        adapters.agentnext.get_json("/status")
    except agentnext.AgentUnavailable:
        return False
    return True


def _backing_off(mem: dict, now: float) -> bool:
    """True when a restart happened less than BACKOFF_S ago."""
    last = mem["last_restart"]
    return last is not None and not now - last >= BACKOFF_S


def check_once(adapters) -> str:
    """One watchdog check; returns "" when it did nothing, else what it did ("restarted the agent service")."""
    if not set_up():
        return ""
    mem = _load()
    now = adapters.clock.now()
    active = _active(adapters)
    did = ""
    if not active and stopped_on_purpose(adapters):
        mem["bad"], mem["stopped"] = 0, True
    elif active and _answers(adapters):
        mem["bad"], mem["stopped"] = 0, False
    else:
        mem["stopped"] = False
        mem["bad"] += 1
        if mem["bad"] >= BAD_CHECKS_NEEDED and not _backing_off(mem, now):
            adapters.host.systemctl("restart", UNIT)
            mem["last_restart"], mem["bad"] = now, 0
            adapters.notify.send(scrub.scrub(NOTICE))
            did = "restarted the agent service"
    atomic.write_json(memory_path(), mem)
    return did
