"""The new agent's watchdog: restarts the phoenix-agentkit service when it stays down or stops answering."""
from __future__ import annotations

from phoenix9 import agentnext, atomic, paths, scrub, settings

UNIT = "phoenix-agentkit"
BAD_CHECKS_NEEDED = 2     # bad checks in a row before a restart
BACKOFF_S = 600           # wait this long after a restart before trying again
MAX_RESTARTS = 3          # restarts in a row that did not bring it back healthy before the watchdog gives up
STATUS_TIMEOUT_S = 5      # the /status check never holds the runner loop longer than this
NOTICE = "Phoenix restarted the agent service: it was not answering."
RESTART_FAILED = "Phoenix tried to restart the agent service (it was not answering), but the restart failed"
GIVE_UP = (f"The agent service keeps failing: Phoenix restarted it {MAX_RESTARTS} times in a row and it never came "
           "back healthy, so it has stopped restarting it. It needs a look (journalctl -u phoenix-agentkit).")


def memory_path():
    """The file that holds what the watchdog remembers between checks."""
    return paths.logs() / "agentkit-watch.json"


def _load() -> dict:
    """The remembered {bad, last_restart, stopped, restarts, gave_up}; fresh values when the file is missing or odd.

    restarts = restarts in a row that have not (yet) brought the service back healthy; gave_up = the watchdog
    stopped restarting after MAX_RESTARTS of them and told Alex once."""
    data = atomic.read_json(memory_path(), {})
    data = data if isinstance(data, dict) else {}
    bad, last, tries = data.get("bad"), data.get("last_restart"), data.get("restarts")
    return {"bad": _count(bad),
            "last_restart": last if isinstance(last, (int, float)) and not isinstance(last, bool) else None,
            "stopped": data.get("stopped") is True,
            "restarts": _count(tries),
            "gave_up": data.get("gave_up") is True}


def _count(value) -> int:
    """A remembered count, or 0 when it is not a whole number of zero or more."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def memory() -> dict:
    """What the watchdog remembers (for doctor): {bad, last_restart, stopped, restarts, gave_up}."""
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
        adapters.agentnext.get_json("/status", timeout=STATUS_TIMEOUT_S)
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
        mem.update(bad=0, stopped=True, restarts=0, gave_up=False)     # someone stopped it: start counting afresh
    elif active and _answers(adapters):
        mem.update(bad=0, stopped=False, restarts=0, gave_up=False)    # healthy again
    else:
        mem["stopped"] = False
        mem["bad"] += 1
        if mem["gave_up"]:
            pass                                    # already told Alex once; never restart until it is healthy again
        elif mem["bad"] >= BAD_CHECKS_NEEDED and not _backing_off(mem, now):
            if mem["restarts"] >= MAX_RESTARTS:
                mem["gave_up"], mem["bad"] = True, 0
                adapters.notify.send(scrub.scrub(GIVE_UP))
                did = "gave up restarting the agent service"
            else:
                rc, _, err = adapters.host.systemctl("restart", UNIT)
                mem["last_restart"], mem["bad"] = now, 0
                mem["restarts"] += 1
                if rc == 0:
                    adapters.notify.send(scrub.scrub(NOTICE))
                    did = "restarted the agent service"
                else:
                    why = (err or "").strip().splitlines()
                    detail = f" (systemctl exit {rc}: {why[-1][:200]})" if why else f" (systemctl exit {rc})"
                    adapters.notify.send(scrub.scrub(RESTART_FAILED + detail + "."))
                    did = "tried to restart the agent service, but the restart failed"
    atomic.write_json(memory_path(), mem)
    return did
