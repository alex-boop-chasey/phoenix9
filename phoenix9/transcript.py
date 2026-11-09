"""Turn the agent's transcript lines (JSONL) into panel items; broken or unknown lines are only counted."""
import json
import re
from datetime import datetime

from phoenix9 import scrub

PANEL_NAME = "Alex (Phoenix panel)"
EXCERPT_LINES = 6
# Claude Code's bookkeeping lines: known, and never shown in the panel.
IGNORED_TYPES = frozenset({
    "attachment", "atis-latch", "last-prompt", "custom-title", "agent-name", "mode", "summary",
    "file-history-snapshot", "file-history-delta", "api-request", "api-request-blob", "api-request-shape",
    "pr-link", "bridge-session", "ai-title", "tools-used", "frame-link", "cost-state", "permission-mode",
    "artifact-autoreact-ledger", "artifact-comment-monitor"})
IGNORED_SYSTEM = frozenset({"stop_hook_summary", "turn_duration", "bridge_status"})
SYSTEM_WORDS = {"api_error": "The API returned an error."}


class Parser:
    """A transcript parser that keeps its state between calls, so a growing transcript is read once, line by line
    (the live stream feeds it only the lines added since the last tick)."""

    def __init__(self):
        """Start before line 1."""
        self.state = {"items": [], "actions": {}, "session": None, "last_at": None, "unknown": 0, "pending": []}
        self.line = 0

    @property
    def unknown(self) -> int:
        """Unknown or broken lines so far."""
        return self.state["unknown"]

    def feed(self, lines) -> tuple[list[dict], list[dict]]:
        """Parse the next lines; returns (the items they made, the earlier actions they finished)."""
        before = self.line
        self.state["items"], self.state["finished"] = [], []
        for raw in lines:
            self.line += 1
            _one(self.state, self.line, raw)
        updates = [i for i in self.state["finished"] if i["line"] <= before]
        return self.state["items"], updates


_PEER_HEAD = "Another Claude session sent a message:"
_WRAPPER = re.compile(r"<cross-session-message\b[^>]*>(.*?)(?:</cross-session-message>)?\Z", re.S)


def parse(lines) -> tuple[list[dict], int]:
    """Parse transcript lines into (panel items, number of unknown or broken lines)."""
    parser = Parser()
    items, _ = parser.feed(lines)
    return items, parser.unknown


def _one(state: dict, number: int, raw) -> None:
    """Parse one line; anything odd in it (a list as a tool id, mixed timestamps, deep nesting) only counts as
    unknown, and whatever that line had half-added is taken back."""
    kept = len(state["items"])
    kept_pending = len(state.setdefault("pending", []))
    state["added"] = []                     # action ids this line adds (taken back if it fails)
    try:
        obj = _load(raw)
        if obj is None:
            state["unknown"] += 1
            return
        _handle(state, number, obj)
    except Exception:
        del state["items"][kept:]
        for key in state["added"]:
            state["actions"].pop(key, None)
        del state["pending"][kept_pending:]
        state["unknown"] += 1


def _load(raw) -> dict | None:
    """Decode one line to a JSON object, or None when it is blank-broken or not an object."""
    try:
        obj = json.loads(raw)
    except (TypeError, ValueError, RecursionError):
        return None
    return obj if isinstance(obj, dict) else None


def _handle(state: dict, number: int, obj: dict) -> None:
    """Route one decoded line to the handler for its type."""
    kind = obj.get("type")
    handler = {"user": _user, "assistant": _assistant, "system": _system,
               "queue-operation": _queued}.get(kind)
    if kind in IGNORED_TYPES:
        return
    if handler is None or (kind in ("user", "assistant") and not isinstance(obj.get("message"), dict)):
        state["unknown"] += 1
        return
    if obj.get("isMeta") is True and kind == "user" and not _is_peer(obj):
        return              # Claude Code's own notes; messages from other sessions (the panel) are kept
    _session_divider(state, number, obj)
    at = obj.get("timestamp")
    handler(state, number, obj, at)
    if at:
        state["last_at"] = at


def _session_divider(state: dict, number: int, obj: dict) -> None:
    """Add a session divider item when the session id differs from the previous one."""
    sid = obj.get("sessionId")
    if not sid:
        return
    if state["session"] is not None and sid != state["session"]:
        state["items"].append({"type": "session", "session_id": sid, "line": number})
    state["session"] = sid


def _add(state: dict, number: int, item: dict) -> None:
    """Append an item stamped with its transcript line number."""
    item["line"] = number
    state["items"].append(item)


def _origin(obj: dict) -> str:
    """Name where a user message came from: panel, app, or peer:<name>."""
    origin = obj.get("origin")
    if not isinstance(origin, dict) or origin.get("kind") != "peer":
        return "app"
    name = str(origin.get("name") or "")
    return "panel" if name.startswith(PANEL_NAME) else "peer:" + name


def _is_peer(obj: dict) -> bool:
    """True when a line is a message another session (such as the Phoenix panel) sent in."""
    origin = obj.get("origin")
    return isinstance(origin, dict) and origin.get("kind") == "peer"


def _user(state: dict, number: int, obj: dict, at) -> None:
    """Handle a user line: a message, or tool results for earlier actions."""
    content = obj["message"].get("content")
    if obj.get("isCompactSummary") is True:
        _add(state, number, {"type": "notice", "text": "Earlier conversation summarised.", "at": at})
        return
    if isinstance(content, list):
        parts = []
        for block in content:
            kind = block.get("type") if isinstance(block, dict) else None
            if kind == "tool_result":
                _tool_result(state, block, number)
            elif kind == "text":
                parts.append(str(block.get("text", "")))
            elif kind == "image":
                parts.append("[image]")
            else:
                state["unknown"] += 1
        if not parts:
            return
        content = "\n".join(parts)
    if not isinstance(content, str):
        state["unknown"] += 1
        return
    origin = obj.get("origin")
    body = origin.get("body") if isinstance(origin, dict) else None
    text = body if isinstance(body, str) else content
    if _is_peer(obj):
        text = _unwrap(text)                # just what Alex typed: no wrapper or [Phoenix panel · ...] line
    _clear_delivered(state, [content, text])
    text, found = _harness(text)
    line = _command_line(found, text)
    if line:
        _add(state, number, {"type": "notice", "text": line, "at": at})
    elif text:
        _add(state, number, {"type": "user", "text": scrub.scrub(text), "origin": _origin(obj), "at": at})


def _unwrap(text: str) -> str:
    """The plain body of a message: no cross-session wrapper or envelope line, entities unescaped, trimmed."""
    text = text.strip()
    if text.startswith(_PEER_HEAD):        # how Claude Code writes a delivered cross-session message
        text = text[len(_PEER_HEAD):].strip()
    match = _WRAPPER.match(text)
    if match:
        text = match.group(1).strip()
    first, _, rest = text.partition("\n")
    if first.startswith("[Phoenix") and first.endswith("]"):
        text = rest
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").strip()


_HARNESS_TAGS = ("system-reminder", "local-command-stdout", "local-command-stderr", "local-command-caveat",
                 "task-notification", "command-name", "command-message", "command-args")
_LEAD = re.compile(r"\A\s*<(%s)\b[^>]*>(.*?)</\1>" % "|".join(_HARNESS_TAGS), re.S)
_TRAIL = re.compile(r"<(%s)\b[^>]*>(.*?)</\1>\s*\Z" % "|".join(_HARNESS_TAGS), re.S)


def _harness(text: str) -> tuple[str, dict]:
    """Remove whole leading and trailing harness blocks (system reminders, command output, slash-command markup);
    returns (what is left, the command name and args found). Tags inside the owner's own words stay."""
    found = {}
    for pattern in (_LEAD, _TRAIL):
        while True:
            match = pattern.search(text)
            if not match:
                break
            found.setdefault(match.group(1), match.group(2).strip())
            text = text[:match.start()] + text[match.end():] if pattern is _TRAIL else text[match.end():]
    return text.strip(), found


def _command_line(found: dict, text: str) -> str | None:
    """The system line for a slash command run in the Claude app, or None when this was not one."""
    name = found.get("command-name", "").strip()
    if not name or text:
        return None
    name = name if name.startswith("/") else "/" + name
    args = found.get("command-args", "")
    return scrub.scrub("%s%s was run in the Claude app" % (name, " " + args if args else ""))


_FROM_NAME = re.compile(r'<cross-session-message\b[^>]*\bfrom-name="([^"]*)"')


def _queued_origin(text: str) -> str:
    """Where a waiting message came from: panel (also when the wrapper is missing), app or peer:<name>."""
    match = _FROM_NAME.search(text)
    name = match.group(1).replace("&amp;", "&") if match else PANEL_NAME
    return "panel" if name.startswith(PANEL_NAME) else "peer:" + name


def _clear_delivered(state: dict, texts: list) -> None:
    """A user line carrying the text of a pending queued item means it was delivered: clear the oldest match."""
    pending = state.setdefault("pending", [])
    bodies = {_unwrap(t) for t in texts if isinstance(t, str)}
    for i, (queued, _) in enumerate(pending):
        if _unwrap(queued) in bodies:
            pending.pop(i)[1]["pending"] = False
            return


def _assistant(state: dict, number: int, obj: dict, at) -> None:
    """Handle an assistant line: text, tool calls and thinking blocks."""
    content = obj["message"].get("content")
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    if not isinstance(content, list):
        state["unknown"] += 1
        return
    for block in content:
        _assistant_block(state, number, block, at)


def _assistant_block(state: dict, number: int, block, at) -> None:
    """Turn one assistant content block into an item (thinking keeps only its duration)."""
    kind = block.get("type") if isinstance(block, dict) else None
    if kind == "text":
        _add(state, number, {"type": "agent", "markdown": scrub.scrub(str(block.get("text", ""))), "at": at})
    elif kind == "thinking":
        _add(state, number, {"type": "thinking", "duration_s": _seconds(state["last_at"], at), "at": at})
    elif kind == "tool_use":
        _tool_use(state, number, block)
    else:
        state["unknown"] += 1


def _seconds(start, end) -> float | None:
    """Seconds between two ISO timestamps, or None when either is missing or odd."""
    try:
        a = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        return max(0.0, (b - a).total_seconds())
    except (ValueError, TypeError):      # missing, odd, or one naive and one with a time zone
        return None


def _tool_use(state: dict, number: int, block: dict) -> None:
    """Add a running action item for a tool call and remember it by tool id."""
    tool = str(block.get("name") or "")
    tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
    summary = _input_summary(tool, tool_input)
    item = {"type": "action", "id": block.get("id"), "tool": tool, "title": summary,
            "input_summary": summary, "status": "running"}
    _add(state, number, item)
    if item["id"]:
        state["actions"][item["id"]] = item
        state.setdefault("added", []).append(item["id"])


def _input_summary(tool: str, data: dict) -> str:
    """A short, scrubbed, one-line description of a tool call."""
    if tool == "Bash":
        text = (str(data.get("command") or "").splitlines() or [""])[0]
    elif tool in ("Edit", "Write", "Read"):
        text = str(data.get("file_path") or data.get("path") or tool)
    elif tool == "SendMessage":
        text = "message to %s" % data.get("to", "")
    elif tool == "Agent":
        text = "helper: %s" % data.get("description", "")
    else:
        text = tool
    return scrub.scrub(text)


def _result_text(content) -> str:
    """Flatten a tool result's content (string or list of text blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in content)
    return "" if content is None else str(content)


def _tool_result(state: dict, block: dict, number: int) -> None:
    """Mark the matching action ok or error, note the line that finished it (done_line) and attach a scrubbed
    last-6-lines excerpt."""
    item = state["actions"].get(block.get("tool_use_id"))
    if item is None:
        state["unknown"] += 1
        return
    item["status"] = "error" if block.get("is_error") else "ok"
    item["done_line"] = number
    state.setdefault("finished", []).append(item)
    tail = scrub.scrub(_result_text(block.get("content"))).splitlines()[-EXCERPT_LINES:]
    item["excerpt"] = "\n".join(tail)


def _queued(state: dict, number: int, obj: dict, at) -> None:
    """enqueue adds a pending queued item; dequeue clears the oldest pending one, remove the one with the same
    text (else the oldest). Other operations count as unknown."""
    op, text = obj.get("operation"), obj.get("content")
    text = text if isinstance(text, str) else ""
    pending = state.setdefault("pending", [])
    if op == "enqueue":
        clean, _ = _harness(_unwrap(text))
        item = {"type": "queued", "text": scrub.scrub(clean), "pending": True, "origin": _queued_origin(text),
                "at": at}
        if clean:
            _add(state, number, item)       # harness-only text is left out (but still counted as pending)
        pending.append((text, item))
    elif op in ("dequeue", "remove"):
        if not pending:
            return
        index = next((i for i, (t, _) in enumerate(pending) if t == text), 0) if op == "remove" else 0
        pending.pop(index)[1]["pending"] = False
    else:
        state["unknown"] += 1


def _system(state: dict, number: int, obj: dict, at) -> None:
    """Handle a system line as a notice item (hook summaries and turn timings are left out)."""
    subtype = obj.get("subtype")
    if subtype in IGNORED_SYSTEM:
        return
    text = obj.get("content")
    if not isinstance(text, str):
        text = SYSTEM_WORDS.get(subtype) or str(subtype or "")
    _add(state, number, {"type": "notice", "text": scrub.scrub(text), "at": at})
