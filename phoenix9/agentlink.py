"""Find the running Phoenix agent chat session and report what state it is in."""
import json
import os

from phoenix9 import settings, transcript
from phoenix9.adapters import Host

CLAUDE_HOME = "/root/.claude"
AGENT_NAME = "Phoenix agent"
KEYS = ("pid", "cwd", "name", "status", "messagingSocketPath", "kind", "sessionId")


def transcript_path(home_dir, cwd: str, session_id: str) -> str:
    """Where Claude writes the transcript: projects/<cwd with / and . as ->/<session>.jsonl."""
    folder = cwd.replace("/", "-").replace(".", "-")
    return "%s/projects/%s/%s.jsonl" % (str(home_dir).rstrip("/"), folder, session_id)


def _entry(host, home: str, name: str) -> dict | None:
    """Read one sessions/<pid>.json file; None when it is not a usable registry entry."""
    if not name.endswith(".json") or not name[:-5].isdigit():
        return None
    path = "%s/sessions/%s" % (home, name)
    try:
        data = json.loads(host.read_text(path))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    entry = {k: data.get(k) for k in KEYS}
    entry["mtime"] = (host.stat(path) or {}).get("mtime") or 0
    return entry


def _is_live(host, entry: dict, folder: str) -> bool:
    """True when the entry is in the agent folder, its process is alive and its socket exists."""
    pid, cwd, sock = entry["pid"], entry["cwd"], entry["messagingSocketPath"]
    if not isinstance(pid, int) or not isinstance(cwd, str) or not isinstance(sock, str) or not sock:
        return False
    if os.path.realpath(cwd) != os.path.realpath(folder):
        return False
    return host.pid_alive(pid) and host.exists(sock)


def find(home_dir=CLAUDE_HOME, host=None) -> dict | None:
    """The live agent session as {pid, session_id, name, socket, transcript, status}, or None."""
    host = host or Host()
    home = str(home_dir).rstrip("/")
    folder = settings.agent_settings()["folder"]
    entries = (_entry(host, home, n) for n in sorted(host.list_dir(home + "/sessions")))
    live = [e for e in entries if e and _is_live(host, e, folder)]
    if not live:
        return None
    named = [e for e in live if e["name"] == AGENT_NAME]
    best = max(named or live, key=lambda e: (e["mtime"], e["pid"]))
    sid = best["sessionId"]
    path = transcript_path(home, best["cwd"], sid) if isinstance(sid, str) and sid else None
    return {"pid": best["pid"], "session_id": sid, "name": best["name"],
            "socket": best["messagingSocketPath"], "transcript": path, "status": best["status"]}


def _items(host, found: dict) -> list[dict]:
    """The panel items of the agent's transcript (empty when it is missing)."""
    if not found["transcript"]:
        return []
    return transcript.parse(host.read_lines(found["transcript"]))[0]


def _state(found: dict, items: list[dict]) -> str:
    """Pick working, queued or idle from the registry status and the transcript items."""
    if found["status"] == "busy" or (items and items[-1]["type"] == "action"
                                     and items[-1]["status"] == "running"):
        return "working"
    for item in reversed(items):
        if item["type"] == "user":
            break
        if item["type"] == "queued":
            return "queued"
    return "idle"


def status(home_dir=CLAUDE_HOME, host=None) -> dict:
    """The agent's {state: asleep|idle|working|queued, pid, session_id, name}."""
    host = host or Host()
    found = find(home_dir, host)
    if found is None:
        return {"state": "asleep", "pid": None, "session_id": None, "name": None}
    state = _state(found, _items(host, found))
    return {"state": state, "pid": found["pid"], "session_id": found["session_id"],
            "name": found["name"]}
