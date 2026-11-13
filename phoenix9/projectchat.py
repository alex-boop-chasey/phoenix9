"""A project's chat: its document (.phoenix/chat.md) and its state (none, asleep, waking, awake, working)."""
import calendar
import os
import re
import time

from phoenix9 import atomic, chatlink, chat, paths, settings

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
    if not chatlink.BRIDGE_RE.fullmatch(bridge):
        return "bad conversation id"
    if not chatlink.is_session_id(fields["Local session id"]):
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
    if not (isinstance(bridge, str) and chatlink.BRIDGE_RE.fullmatch(bridge)) or not chatlink.is_session_id(sid):
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


def _session_process(host, project: str) -> dict | None:
    """The project's live conversation process (the unit's main process or its direct child), or None."""
    folder = str(paths.projects() / project)
    main = chat.unit_main_pid(host, project)
    found = chatlink.find_in(folder, chatlink.CLAUDE_HOME, host, main)
    if found is None or main is None:
        return None
    if found["pid"] != main and host.parent_pid(found["pid"]) != main:
        return None
    return found


def _newest(host, found: dict | None, fields: dict | None) -> float | None:
    """The newest of the registry mtime, transcript mtime and document Last active, or None."""
    times = []
    if found:
        times.append(found.get("mtime"))
        if found.get("transcript"):
            times.append((host.stat(found["transcript"]) or {}).get("mtime"))
    if fields:
        times.append(parse_time(fields["Last active"]))
    times = [t for t in times if isinstance(t, (int, float)) and t]
    return max(times) if times else None


def state(project: str, adapters) -> dict:
    """A project's chat as {state, bridge_session_id, web_url, app_url, last_active}; refuses unknown projects."""
    host = adapters.host
    unit = chat.unit_state(host, project)
    found = _session_process(host, project) if unit == "active" else None
    if found:
        sync_chat_doc(project, found, time.time())
    fields, _ = read_chat_doc(project)
    # A live conversation's own id only: the document may still hold an older conversation's id (found live:
    # the first press returned before Claude Code had written the new id). Otherwise the document's id.
    bridge = found.get("bridge_session_id") if found else (fields or {}).get("Conversation id")
    if unit in ("inactive", "failed"):
        word = "asleep" if fields else "none"
    elif found and found.get("bridge_session_id"):
        word = "working" if found.get("status") == "busy" else "awake"
    else:
        word = "waking"
    return {"state": word, "bridge_session_id": bridge,
            "web_url": WEB_PREFIX + bridge if bridge else None,
            "app_url": DESKTOP_PREFIX + bridge if bridge else None,
            "last_active": _newest(host, found, fields)}


LIVE = ("awake", "working")
AWAKE_WORDS = "The chat is awake."
PRIME_FAILED = "The chat is awake, but the notes message could not be sent."
PRIME_TEXT = ("This is a fresh conversation for this project. Before anything else, read notes/NOW.md "
              "and the files in notes/sessions/ so you know where things stand.")


class NotReady(Exception):
    """The chat did not come up within the start wait; the message says what to do."""


def _wait_ready(project: str, adapters, seconds: int) -> dict:
    """Poll until the chat is awake WITH its claude.ai conversation id (Claude Code writes the id a few seconds
    after the session appears), up to `seconds` on the adapter clock; NotReady if not."""
    clock = adapters.clock
    deadline = clock.now() + seconds
    while True:
        current = state(project, adapters)
        if current["state"] in LIVE and current.get("bridge_session_id"):
            return current
        if clock.now() >= deadline:
            raise NotReady("The chat didn't wake in %d seconds. Press Chat again." % seconds)
        clock.sleep(1)


def _prime(project: str, adapters, who: str) -> str | None:
    """Send the notes message to a fresh conversation when the project has notes/; a note when it failed."""
    if not (paths.projects() / project / "notes").is_dir():
        return None
    found = _session_process(adapters.host, project)
    try:
        if found is None:
            raise chatlink.SendError("no conversation to write to")
        chatlink.send_to(found, PRIME_TEXT, {"project": project}, "chat:%s" % project, host=adapters.host)
    except chatlink.SendError:
        return PRIME_FAILED
    return None


def _answer(current: dict, message: str, woke: bool, fresh: bool) -> dict:
    """The open answer: {state, web_url, app_url, bridge_session_id, message, woke, fresh}."""
    return {"state": current["state"], "web_url": current["web_url"], "app_url": current["app_url"],
            "bridge_session_id": current["bridge_session_id"], "message": message, "woke": woke, "fresh": fresh}


def _saved_id(project: str) -> str | None:
    """The conversation id the chat document holds, or None."""
    fields, _ = read_chat_doc(project)
    return fields["Conversation id"] if fields else None


def open_(project: str, adapters, who: str = "cli") -> dict:
    """Open a project's chat: wake its unit when needed (the same conversation), wait, and return its links."""
    current = state(project, adapters)
    if current["state"] in LIVE:
        return _answer(current, AWAKE_WORDS, woke=False, fresh=False)
    before, saved = current["state"], _saved_id(project)
    if chat.unit_state(adapters.host, project) not in ("active", "activating"):
        chat.start_unit(adapters.host, project)
    current = _wait_ready(project, adapters, settings.chat_settings()["start_wait_seconds"])
    # Only a brand-new conversation gets the notes message; a woken one already knows where things stand.
    fresh = before == "none" or current["bridge_session_id"] != saved
    note = _prime(project, adapters, who) if fresh else None
    return _answer(current, note or AWAKE_WORDS, woke=True, fresh=fresh)


WRAP_UP_TEXT = "Wrap up: write a short summary of this conversation into notes/NOW.md and notes/sessions/"
WRAP_UP_STEP = 2
ASLEEP_WORDS = "The chat is asleep. Press Chat to wake it."
UNCHANGED_WORDS = {"asleep": "The chat is already asleep.", "none": "There is no chat yet.",
                   "waking": "The chat is still waking."}


def _wait_not_busy(project: str, adapters, seconds: float) -> None:
    """Wait on the adapter clock until the conversation is not busy (or is gone), up to `seconds`."""
    clock = adapters.clock
    deadline = clock.now() + seconds
    clock.sleep(WRAP_UP_STEP)
    while clock.now() < deadline:
        found = _session_process(adapters.host, project)
        if found is None or found.get("status") != "busy":
            return
        clock.sleep(WRAP_UP_STEP)


def _touch_doc(project: str, now: float) -> None:
    """Set the document's Last active to now, keeping the conversation id."""
    fields, _ = read_chat_doc(project)
    if fields:
        write_chat_doc(project, dict(fields, **{"Last active": format_time(now)}))


def sleep(project: str, adapters, who: str = "cli", wrap_up: bool = True) -> dict:
    """Put an awake chat to sleep: ask for a wrap-up, wait, then stop its whole unit; {state, changed, message}."""
    current = state(project, adapters)
    if current["state"] not in LIVE:
        word = current["state"]
        return {"state": word, "changed": False, "message": UNCHANGED_WORDS.get(word, "The chat is " + word + ".")}
    host = adapters.host
    found = _session_process(host, project)
    if found is not None and wrap_up:
        try:
            chatlink.send_to(found, WRAP_UP_TEXT, {"project": project}, "chat:%s" % project, host=host)
            _wait_not_busy(project, adapters, settings.chat_settings()["wrap_up_minutes"] * 60)
        except chatlink.SendError:
            pass
    chat.stop_unit(host, project)
    _touch_doc(project, time.time())
    return {"state": "asleep", "changed": True, "message": ASLEEP_WORDS}


def forget(project: str, adapters, who: str = "cli") -> dict:
    """Stop the chat unit and set the saved chat aside (chat.md becomes chat.old.md); {state, changed, message}."""
    chat.stop_unit(adapters.host, project)
    path = doc_path(project)
    if path.exists():
        os.replace(path, path.with_name("chat.old.md"))
    return {"state": "none", "changed": True,
            "message": "The saved chat is forgotten. Press Chat to start a fresh one."}

