"""Find the running Phoenix agent chat session and report what state it is in."""
import errno
import json
import os
import socket
import time
import uuid
from datetime import datetime, timezone

from phoenix9 import paths, scrub, settings, transcript
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


MAX_CHARS = 100_000
SEND_TIMEOUT = 5.0
PANEL_FROM = "uds:/run/phoenix9/panel.sock"
WRAP_HEAD = '<cross-session-message from="%s" from-name="Alex (Phoenix panel)" from-mode="bypass">' % PANEL_FROM


class SendError(Exception):
    """A message could not be delivered to the agent; the text says why in plain English."""


def _escape(text: str) -> str:
    """Escape & < > so the body cannot close the wrapper early."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def envelope(context: dict | None) -> str:
    """The first line telling the agent where in the panel the message came from ('' when empty)."""
    context = context or {}
    project, page, run = context.get("project"), context.get("page"), context.get("run")
    parts = []
    if page:
        parts.append("page: %s" % page)
    if project:
        parts.append("project: %s" % project)
    if project:
        parts.append("folder: /srv/projects/%s" % project)
    elif page or run:
        parts.append("folder: %s" % settings.agent_settings()["folder"])
    if run:
        parts.append("run: %s" % run)
    return "[Phoenix panel · %s]" % " · ".join(parts) if parts else ""


def wire_line(text: str, context: dict | None) -> str:
    """The exact one-line JSON the agent's inbox socket expects (with a fresh msg_id)."""
    first = envelope(context)
    body = _escape(("%s\n%s" % (first, text)) if first else text)
    content = "%s\n%s\n</cross-session-message>" % (WRAP_HEAD, body)
    msg = {"msgV": 1, "msg_id": str(uuid.uuid4()), "type": "user",
           "message": {"role": "user", "content": content}, "priority": "next", "from": PANEL_FROM}
    return json.dumps(msg, ensure_ascii=False) + "\n"


def connect_and_write(path: str, data: bytes, timeout: float = SEND_TIMEOUT) -> None:
    """Connect to the inbox socket and write data within the timeout (SendError otherwise)."""
    deadline = time.monotonic() + timeout
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        while True:
            try:
                sock.connect(path)
                break
            except (BlockingIOError, InterruptedError):
                if time.monotonic() >= deadline:
                    raise SendError("The agent did not take the message within %g seconds." % timeout)
                time.sleep(0.02)
            except socket.timeout:
                raise SendError("The agent did not take the message within %g seconds." % timeout)
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                    if time.monotonic() >= deadline:
                        raise SendError("The agent did not take the message within %g seconds." % timeout)
                    time.sleep(0.02)
                    continue
                raise SendError("The agent's inbox refused the message (%s). It may be restarting."
                                % (e.strerror or "connection failed"))
        sock.settimeout(max(0.01, deadline - time.monotonic()))
        try:
            sock.sendall(data)
        except socket.timeout:
            raise SendError("The agent did not take the message within %g seconds." % timeout)
        except OSError as e:
            raise SendError("The agent's inbox refused the message (%s)." % (e.strerror or "write failed"))
    finally:
        sock.close()


def _log_send(who: str, context: dict, chars: int) -> None:
    """Append {at, who, page, project, chars} (never the text) to logs/agent-sends.jsonl."""
    rec = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "who": who,
           "page": context.get("page"), "project": context.get("project"), "chars": chars}
    path = paths.home() / "logs" / "agent-sends.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(scrub.scrub(json.dumps(rec)) + "\n")


def send(text: str, context: dict | None = None, who: str = "cli", timeout: float = SEND_TIMEOUT,
         host=None) -> dict:
    """Post a message into the agent's inbox; returns {sent, at, after_line}."""
    context = context or {}
    if len(text) > MAX_CHARS:
        raise SendError("That message is %d characters long; the limit is %d. Nothing was sent."
                        % (len(text), MAX_CHARS))
    host = host or Host()
    found = find(host=host)
    if found is None:
        raise SendError("The Phoenix agent is asleep (no running session found). Nothing was sent.")
    after = len(host.read_lines(found["transcript"])) if found.get("transcript") else 0
    connect_and_write(found["socket"], wire_line(text, context).encode("utf-8"), timeout)
    _log_send(who, context, len(text))
    return {"sent": True, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "after_line": after}
