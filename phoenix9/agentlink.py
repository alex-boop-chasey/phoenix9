"""Find the running Phoenix agent chat session and report what state it is in."""
import errno
import json
import re
import socket
import time
import uuid
from datetime import datetime, timezone

from phoenix9 import paths, scrub, settings, transcript
from phoenix9.adapters import Host

CLAUDE_HOME = "/root/.claude"
AGENT_NAME = "Phoenix agent"
SOCKET_FOLDER = "/tmp/cc-socks-0"          # where Claude Code (run as root) puts each session's inbox socket
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
KEYS = ("pid", "cwd", "name", "status", "messagingSocketPath", "kind", "sessionId", "startedAt", "bridgeSessionId")
BRIDGE_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$", re.ASCII)
_chosen: dict = {}       # (Claude home, folder) -> the pid find() picked last time (kept while it stays live)


def forget() -> None:
    """Drop the remembered choice (tests)."""
    _chosen.clear()


def encode_folder(real_cwd: str) -> str:
    """Claude Code's folder name for a working folder: every character that is not a letter or digit becomes '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", real_cwd)


def transcript_dir(home_dir, cwd: str, host=None) -> str:
    """The folder holding the transcripts of sessions started in cwd (named after cwd's real path)."""
    real = (host or Host()).realpath(cwd)
    return "%s/projects/%s" % (str(home_dir).rstrip("/"), encode_folder(real))


def transcript_path(home_dir, cwd: str, session_id: str, host=None) -> str:
    """Where Claude writes a session's transcript: projects/<encoded real cwd>/<session>.jsonl."""
    return "%s/%s.jsonl" % (transcript_dir(home_dir, cwd, host), session_id)


def is_session_id(value) -> bool:
    """True for a Claude Code session id (a lowercase UUID), the only kind used in a path."""
    return isinstance(value, str) and bool(UUID_RE.fullmatch(value))


def socket_ok(path) -> bool:
    """True when the socket sits directly in the messaging socket folder (no '..', no sub-folder)."""
    if not isinstance(path, str) or not path.startswith("/") or "\0" in path:
        return False
    return path.rsplit("/", 1)[0] == SOCKET_FOLDER and ".." not in path.split("/") and path.endswith(".sock")


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
    if not isinstance(pid, int) or not isinstance(cwd, str) or not socket_ok(sock):
        return False
    if host.realpath(cwd) != host.realpath(folder):
        return False
    return host.pid_alive(pid) and host.exists(sock)


def _main_pid(host) -> int | None:
    """The agent unit's main process id (claude remote-control), or None when the unit is not running."""
    rc, out, _ = host.systemctl("show", "-p", "MainPID", "--value", settings.agent_settings()["unit"])
    try:
        pid = int(out.strip()) if rc == 0 else 0
    except ValueError:
        pid = 0
    return pid or None


def _started(e: dict) -> tuple:
    """Sort key: when the session started (registry startedAt), then its pid."""
    at = e.get("startedAt")
    return (at if isinstance(at, (int, float)) and not isinstance(at, bool) else float("inf"), e["pid"])


def _choose(host, key, pool: list[dict], main_pid=None) -> dict:
    """One session, chosen the same way every time: the unit's main process (or its direct child), else the
    one picked last time while it is still live, else the oldest; it never flips between two live sessions.
    main_pid may be a number, None, or a function that looks it up (only called when there is a choice)."""
    if len(pool) == 1:
        _chosen[key] = pool[0]["pid"]
        return pool[0]
    main = main_pid() if callable(main_pid) else main_pid
    if main is not None:
        mine = [e for e in pool if e["pid"] == main or host.parent_pid(e["pid"]) == main]
        pool = mine or pool
    kept = [e for e in pool if e["pid"] == _chosen.get(key)]
    best = kept[0] if kept else min(pool, key=_started)
    _chosen[key] = best["pid"]
    return best


def _bridge_id(value) -> str | None:
    """The registry bridgeSessionId when it is a plain id (letters, digits, _ -; at most 100), else None."""
    return value if isinstance(value, str) and BRIDGE_RE.fullmatch(value) else None


def _live_in(host, home: str, folder: str) -> list[dict]:
    """All live registry entries whose cwd resolves to folder."""
    entries = (_entry(host, home, n) for n in sorted(host.list_dir(home + "/sessions")))
    return [e for e in entries if e and _is_live(host, e, folder)]


def _shape(host, home: str, best: dict) -> dict:
    """The found-session dict for one registry entry (without bridge id and mtime)."""
    sid = best["sessionId"]
    path = transcript_path(home, best["cwd"], sid, host) if is_session_id(sid) else None
    return {"pid": best["pid"], "session_id": sid, "name": best["name"],
            "socket": best["messagingSocketPath"], "transcript": path, "status": best["status"]}


def find_in(folder, home_dir=CLAUDE_HOME, host=None, main_pid=None) -> dict | None:
    """The live session working in folder as {pid, session_id, name, socket, transcript, status,
    bridge_session_id, mtime}, or None."""
    host = host or Host()
    home = str(home_dir).rstrip("/")
    live = _live_in(host, home, str(folder))
    if not live:
        return None
    best = _choose(host, (home, host.realpath(str(folder))), live, main_pid)
    found = _shape(host, home, best)
    found["bridge_session_id"] = _bridge_id(best["bridgeSessionId"])
    found["mtime"] = best["mtime"]
    return found


def find(home_dir=CLAUDE_HOME, host=None) -> dict | None:
    """The live agent session as {pid, session_id, name, socket, transcript, status}, or None."""
    host = host or Host()
    home = str(home_dir).rstrip("/")
    folder = settings.agent_settings()["folder"]
    live = _live_in(host, home, folder)
    if not live:
        return None
    named = [e for e in live if e["name"] == AGENT_NAME]
    best = _choose(host, (home, host.realpath(folder)), named or live, lambda: _main_pid(host))
    return _shape(host, home, best)


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
        if item["type"] == "queued" and item.get("pending", True):
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


class TooLong(SendError):
    """The message is over the length limit (a caller mistake, not an outage)."""


def _escape(text: str) -> str:
    """Escape & < > so the body cannot close the wrapper early."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


CONTEXT_RE = re.compile(r"^[A-Za-z0-9/_.-]{1,80}$")


def clean_context(context) -> dict:
    """Only the context values the agent may be told: newlines stripped from each; `project` kept only when it is
    a listed project, `page` and `run` only when they match [A-Za-z0-9/_.-] (at most 80); anything else dropped."""
    from phoenix9 import project as project_mod
    context = context if isinstance(context, dict) else {}
    out = {}
    for key in ("page", "project", "run"):
        value = context.get(key)
        if not isinstance(value, str):
            continue
        value = value.replace("\r", "").replace("\n", "")
        if not CONTEXT_RE.fullmatch(value):
            continue
        if key == "project" and value not in project_mod.project_names():
            continue
        out[key] = value
    return out


def envelope(context: dict | None) -> str:
    """The first line telling the agent where in the panel the message came from ('' when empty). The folder is
    only ever /srv/projects/<listed project> or the agent folder."""
    context = clean_context(context)
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


def send_to(found: dict, text: str, context: dict | None = None, who: str = "cli",
            timeout: float = SEND_TIMEOUT, host=None) -> dict:
    """Post a message into the given session's inbox; returns {sent, at, after_line}."""
    context = context or {}
    if len(text) > MAX_CHARS:
        raise TooLong("That message is %d characters long; the limit is %d. Nothing was sent."
                      % (len(text), MAX_CHARS))
    context = clean_context(context)
    host = host or Host()
    after = len(host.read_lines(found["transcript"])) if found.get("transcript") else 0
    connect_and_write(found["socket"], wire_line(text, context).encode("utf-8"), timeout)
    _log_send(who, context, len(text))
    return {"sent": True, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "after_line": after}


def send(text: str, context: dict | None = None, who: str = "cli", timeout: float = SEND_TIMEOUT,
         host=None) -> dict:
    """Post a message into the agent's inbox; returns {sent, at, after_line}."""
    host = host or Host()
    if len(text) > MAX_CHARS:
        raise TooLong("That message is %d characters long; the limit is %d. Nothing was sent."
                      % (len(text), MAX_CHARS))
    found = find(host=host)
    if found is None:
        raise SendError("The Phoenix agent is asleep (no running session found). Nothing was sent.")
    return send_to(found, text, context, who, timeout, host)
