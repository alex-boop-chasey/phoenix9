"""The new agent's way into Phoenix: its uid ([agent_next] uid) and the short list of routes it may use."""
import re

from phoenix9 import settings

WHO = "agent"
NAME = r"[a-z0-9][a-z0-9-]{0,40}"   # the same safe patterns as phoenix9/api/server.py
RUN_ID = r"\d{8}-\d{6}-[a-z0-9-]+"
GATE_ID = RUN_ID + r"\.\d+"
SAFE_PARTS = {"name": NAME, "project": NAME, "run_id": RUN_ID, "gate_id": GATE_ID}
NOT_ALLOWED = "Refused: the agent isn't allowed to do that."
NEEDS_HEADER = "Refused: this request didn't come from a Phoenix program."
SAFETY_SETTING = "Refused: that is a safety setting, and the agent may not change it. Change it in Settings yourself."
NO_PRESET_IN_SET = "Refused: choose a preset with the preset control, not inside the settings."
ONLY_SERVICES = "Refused: the agent may only change a project's services here, not its description, repo or profile."
NEEDS_SETTINGS = "Refused: say which settings to change, like {\"set\": {\"setting name\": value}}."


def _safe_pattern(route: str) -> str:
    """The registry's route pattern with each named part swapped for its safe pattern."""
    return re.sub(r"\(\?P<(\w+)>\[\^/\]\+\)", lambda m: SAFE_PARTS.get(m.group(1), r"[^/]+"), route)


def allowed() -> list[tuple[str, str]]:
    """The (method, route) pairs of every registry control the agent may use as a tool."""
    from phoenix9.ops.controls import CONTROLS
    return sorted({(c.method, c.route) for c in CONTROLS if c.agent == "tool"})


ALLOWED = allowed()
_COMPILED = [(m, re.compile(rf"^{_safe_pattern(p)}/?$")) for m, p in ALLOWED]


def uid() -> int | None:
    """The agent's uid from global.toml [agent_next] uid, or None when agent access is off or the value is not a uid."""
    table = settings.read_global().get("agent_next")
    value = table.get("uid") if isinstance(table, dict) else None
    return value if type(value) is int and 0 <= value < 2 ** 32 else None


def uid_problem(peer_uids: list[int]) -> str:
    """'' when the agent uid is off or safe; else why it must change (for the doctor)."""
    value = uid()
    if value is None:
        return ""
    if value == 0:
        return "agent_next.uid is 0 (root), but the agent must never run as root, so agent access is refused"
    if value in peer_uids:
        return (f"agent_next.uid {value} is also in access.peer_uids, so the agent would get full access; "
                "give the agent its own user, not one listed in access.peer_uids")
    return ""


def is_agent(peer_uid, peer_uids: list[int]) -> bool:
    """True when the connection's peer is the agent user (never root, never a uid with full access)."""
    value = uid()
    return value is not None and peer_uid == value and not uid_problem(peer_uids)


def route_allowed(method: str, path: str) -> bool:
    """True when the agent may call this method and path."""
    return any(m == method and rx.match(path) for m, rx in _COMPILED)


def _safety_refusal(keys) -> str:
    """The plain refusal when any of these setting keys is a safety key, else ''."""
    from phoenix9.ops import settings as ops_settings
    hit = sorted(k for k in keys if ops_settings.is_safety_key(str(k)))
    return f"{SAFETY_SETTING} ({', '.join(hit)})" if hit else ""


def _preset_refusal(name: str, preset) -> str:
    """The plain refusal when the preset would change a safety setting, else ''."""
    from phoenix9.ops import common, settings as ops_settings
    try:
        folder = common.project_dir(name)
    except common.OpsError:
        return ""   # the route itself answers "no such project"
    try:
        ops_settings._refuse_chat_preset(folder, str(preset), WHO)
    except common.OpsError as err:
        return f"Refused: {err}"
    return ""


def settings_refusal(method: str, path: str, body) -> str:
    """The plain refusal for an agent write that would loosen its leash (safety keys, presets, wide edits), else ''."""
    if method != "POST":
        return ""
    body = body if isinstance(body, dict) else {}
    parts = path.rstrip("/").split("/")
    last = parts[-1]
    if last == "settings":
        values = body.get("set")
        if not isinstance(values, dict) or not values or set(body) - {"set"}:
            return NEEDS_SETTINGS
        if "preset" in values:
            return NO_PRESET_IN_SET
        return _safety_refusal(values)
    if last == "preset" and len(parts) > 2 and parts[-2] == "settings":
        return _preset_refusal(parts[-3], body.get("preset"))
    if last == "edit" and set(body) - {"services"}:
        return ONLY_SERVICES
    return ""
