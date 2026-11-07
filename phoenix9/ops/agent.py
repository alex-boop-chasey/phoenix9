"""Ops for the Phoenix agent chat: its state, panel messages, sending, and earlier conversations."""
import json
from datetime import datetime, timezone

from phoenix9 import agentlink, scrub, settings, transcript
from phoenix9.ops import common


def _host():
    """The host adapter used for every read."""
    return common.make_adapters().host


def status() -> dict:
    """The agent's {state, pid, session_id, name}."""
    return agentlink.status(host=_host())


def messages(after: int = 0, limit: int = 100) -> dict:
    """Panel items after a line number (at most limit) plus {unknown, last_line, session_id}."""
    host = _host()
    found = agentlink.find(host=host)
    if found is None or not found.get("transcript"):
        return {"items": [], "unknown": 0, "last_line": 0,
                "session_id": found["session_id"] if found else None}
    lines = host.read_lines(found["transcript"])
    items, unknown = transcript.parse(lines)
    wanted = [i for i in items if i["line"] > after][:max(0, limit)]
    return {"items": wanted, "unknown": unknown, "last_line": len(lines),
            "session_id": found["session_id"]}


def send(text: str, context: dict | None = None, who: str = "cli") -> dict:
    """Post a message to the agent and record who sent it; OpsError with the reason on failure."""
    try:
        result = agentlink.send(text, context, who)
    except agentlink.SendError as e:
        raise common.OpsError(scrub.scrub(str(e)))
    common.record_command(who, "agent send")
    return result


def _first_time(lines) -> str | None:
    """The first timestamp found in a transcript's lines."""
    for raw in lines:
        try:
            at = json.loads(raw).get("timestamp")
        except (ValueError, AttributeError):
            continue
        if isinstance(at, str) and at:
            return at
    return None


def _session(host, folder: str, name: str) -> dict:
    """One earlier conversation: {session_id, started, lines} (plus its file time for sorting)."""
    path = "%s/%s" % (folder, name)
    lines = host.read_lines(path)
    mtime = (host.stat(path) or {}).get("mtime") or 0
    started = _first_time(lines) or datetime.fromtimestamp(mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"session_id": name[:-len(".jsonl")], "started": started, "lines": len(lines), "_m": mtime}


def sessions() -> list[dict]:
    """Earlier conversations in the agent folder's transcript directory, newest first."""
    host = _host()
    cwd = settings.agent_settings()["folder"]
    folder = agentlink.transcript_path(agentlink.CLAUDE_HOME, cwd, "x").rsplit("/", 1)[0]
    names = [n for n in host.list_dir(folder) if n.endswith(".jsonl")]
    found = [_session(host, folder, n) for n in names]
    found.sort(key=lambda s: (s["started"], s["_m"]), reverse=True)
    return [{k: v for k, v in s.items() if k != "_m"} for s in found]
