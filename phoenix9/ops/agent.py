"""Ops for the Phoenix agent chat: its state, panel messages, sending, and earlier conversations."""
import json
from datetime import datetime, timezone

from phoenix9 import __version__, agentlink, scrub, settings, transcript
from phoenix9.ops import common, projects, update


MAX_CHARS = agentlink.MAX_CHARS


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
    except agentlink.TooLong as e:
        raise common.OpsError(scrub.scrub(str(e)))
    except agentlink.SendError as e:
        raise common.Unavailable(scrub.scrub(str(e)))
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


LINE_MAX = 120
NOW_LINES = 20


def _state_words(row: dict) -> str:
    """A project's state in the brief's words."""
    run = row.get("run")
    if row.get("needs_you"):
        return "waiting for you (%d)" % row["needs_you"]
    if run and run.get("status") == "paused-limit":
        return "paused"
    if run and run.get("task") is not None:
        profile = (row.get("profile") or "").strip()
        tail = ", %s" % profile.capitalize() if profile else ""
        return "build running (task %s/%s%s)" % (run["task"], run.get("tasks"), tail)
    if run:
        return "build running"
    return "idle"


def _project_line(row: dict) -> str:
    """One project as '<name> · <state> · <repo or no repo>', cut to 120 characters."""
    line = "%s · %s · %s" % (row["name"], _state_words(row), row.get("repo") or "no repo")
    return scrub.scrub(line.replace("\n", " "))[:LINE_MAX]


def _now_notes(host) -> list[str]:
    """Up to 20 lines of the agent folder's notes/NOW.md (none when it is missing)."""
    path = "%s/notes/NOW.md" % settings.agent_settings()["folder"].rstrip("/")
    lines = [scrub.scrub(raw.rstrip("\n")) for raw in host.read_lines(path)]
    return [x for x in lines if x.strip()][:NOW_LINES]


def _update_line() -> str:
    """The Phoenix version, with 'update available' when the updater knows of one."""
    try:
        newer = bool(update.status().get("update_available"))
    except Exception:
        newer = False
    return "Phoenix %s%s" % (__version__, " · update available" if newer else "")


def brief() -> dict:
    """The agent's start-up brief: {projects: [lines], now: [lines], version, text}."""
    host = _host()
    lines = [_project_line(r) for r in projects.rows()]
    notes = _now_notes(host)
    version = _update_line()
    parts = lines + (["", "NOW.md:"] + notes if notes else []) + ["", version]
    return {"projects": lines, "now": notes, "version": version, "text": "\n".join(parts)}
