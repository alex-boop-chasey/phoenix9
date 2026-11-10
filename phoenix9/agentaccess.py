"""The new agent's way into Phoenix: its uid ([agent_next] uid) and the short list of routes it may use."""
import re

from phoenix9 import settings

WHO = "agent"
SETTINGS_KEY = "steps.notify.on"
NAME = r"[a-z0-9][a-z0-9-]{0,40}"
# (method, path pattern): everything else is refused with 403, whatever the agent does.
ALLOWED = [
    ("GET", "/api/projects"),
    ("GET", f"/api/projects/{NAME}"),
    ("GET", f"/api/projects/{NAME}/runs"),
    ("GET", "/api/routes"),
    ("POST", f"/api/projects/{NAME}/settings"),
]
_COMPILED = [(m, re.compile(rf"^{p}/?$")) for m, p in ALLOWED]
NOT_ALLOWED = "Refused: the agent isn't allowed to do that."
NEEDS_HEADER = "Refused: this request didn't come from a Phoenix program."
ONE_SETTING = f"Refused: the agent may only change one setting here: {SETTINGS_KEY}."


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


def settings_refusal(method: str, path: str, body) -> str:
    """'' unless this is a settings change that sets anything but steps.notify.on (then the plain refusal)."""
    if method != "POST" or not path.rstrip("/").endswith("/settings"):
        return ""
    values = body.get("set") if isinstance(body, dict) else None
    if not isinstance(values, dict) or list(values) != [SETTINGS_KEY] or set(body) - {"set"}:
        return ONE_SETTING
    return ""
