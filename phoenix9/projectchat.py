"""A project's chat document (.phoenix/chat.md): written, parsed strictly and kept up to date."""
import calendar
import re
import time

from phoenix9 import agentlink, atomic, paths

KEYS = ("Project", "Desktop app link", "Web link", "Conversation id", "Local session id",
        "Created", "Last active")
DESKTOP_PREFIX = "claude://claude.ai/code/"
WEB_PREFIX = "https://claude.ai/code/"
THROTTLE_SECONDS = 600
TIME_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", re.ASCII)


def doc_path(project: str):
    """Where a project's chat document lives."""
    return paths.projects() / project / ".phoenix" / "chat.md"


def format_time(when: float) -> str:
    """A Unix time as UTC YYYY-MM-DDTHH:MM:SSZ."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(when))


def parse_time(text: str) -> float | None:
    """Seconds since the epoch for a document timestamp, or None when it is not one."""
    if not TIME_RE.fullmatch(text):
        return None
    try:
        return float(calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ")))
    except ValueError:
        return None


def build_fields(project: str, bridge_id: str, session_id: str, created: float, last_active: float) -> dict:
    """The document fields for a conversation, with both links built from its conversation id."""
    return {"Project": project, "Desktop app link": DESKTOP_PREFIX + bridge_id,
            "Web link": WEB_PREFIX + bridge_id, "Conversation id": bridge_id,
            "Local session id": session_id, "Created": format_time(created),
            "Last active": format_time(last_active)}


def write_chat_doc(project: str, fields: dict) -> None:
    """Write the chat document atomically, one Key: value line per field in the fixed order."""
    if set(fields) != set(KEYS):
        raise ValueError("chat document fields must be exactly: " + ", ".join(KEYS))
    lines = ["# Chat: " + project, ""] + ["%s: %s" % (k, fields[k]) for k in KEYS]
    atomic.write_text(doc_path(project), "\n".join(lines) + "\n")


def _parse(project: str, text: str) -> tuple[dict | None, str | None]:
    """Parse document text strictly into (fields, None) or (None, reason)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines or lines[0] != "# Chat: " + project:
        return None, "bad heading"
    fields: dict = {}
    for line in lines[1:]:
        key, sep, value = line.partition(": ")
        if not sep or key not in KEYS:
            return None, "unknown or malformed line: " + line[:40]
        if key in fields:
            return None, "duplicate key: " + key
        fields[key] = value
    missing = [k for k in KEYS if k not in fields]
    if missing:
        return None, "missing key: " + missing[0]
    return fields, _check(project, fields)


def _check(project: str, fields: dict) -> str | None:
    """The reason parsed fields are not acceptable, or None when they are."""
    bridge = fields["Conversation id"]
    if fields["Project"] != project:
        return "wrong project"
    if not agentlink.BRIDGE_RE.fullmatch(bridge):
        return "bad conversation id"
    if not agentlink.is_session_id(fields["Local session id"]):
        return "bad local session id"
    if fields["Desktop app link"] != DESKTOP_PREFIX + bridge:
        return "bad desktop app link"
    if fields["Web link"] != WEB_PREFIX + bridge:
        return "bad web link"
    for key in ("Created", "Last active"):
        if parse_time(fields[key]) is None:
            return "bad time in " + key
    return None


def read_chat_doc(project: str) -> tuple[dict | None, str | None]:
    """Read the chat document as (fields, None), or (None, reason) when missing or unreadable."""
    try:
        text = doc_path(project).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "no chat document"
    except (OSError, UnicodeDecodeError):
        return None, "cannot read the chat document"
    fields, reason = _parse(project, text)
    return (None, reason) if reason else (fields, None)


def sync_chat_doc(project: str, found: dict, now: float) -> bool:
    """Make the document match the live conversation; True when it wrote. Bad ids leave it alone."""
    bridge, sid = found.get("bridge_session_id"), found.get("session_id")
    if not (isinstance(bridge, str) and agentlink.BRIDGE_RE.fullmatch(bridge)) or not agentlink.is_session_id(sid):
        return False
    current, _ = read_chat_doc(project)
    if current is None or current["Conversation id"] != bridge or current["Local session id"] != sid:
        write_chat_doc(project, build_fields(project, bridge, sid, now, now))
        return True
    last = parse_time(current["Last active"]) or 0.0
    if now - last < THROTTLE_SECONDS:
        return False
    write_chat_doc(project, dict(current, **{"Last active": format_time(now)}))
    return True
