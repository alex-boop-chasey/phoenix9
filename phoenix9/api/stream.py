"""Live events for the dashboard: a server-sent stream that tails HOME/events.jsonl, and a polling fallback."""
import json
import os
import re
import time

from phoenix9 import agentlink, paths, transcript

MAX_STREAMS = 20
TOO_MANY = "Too many live views open."
TYPE_RE = re.compile(r"^[a-z.]+$")


def _seconds(name: str, default: float) -> float:
    """A positive number of seconds from the environment, else the default."""
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


def _tail_seconds() -> float:
    return _seconds("PHOENIX_API_TAIL_SECONDS", 0.5)


def _ping_seconds() -> float:
    return _seconds("PHOENIX_API_PING_SECONDS", 15.0)


def _size(path) -> int:
    try:
        return os.stat(path).st_size
    except OSError:
        return 0


def _read_from(path, offset: int) -> bytes:
    """The bytes of the file from offset on (b'' when the file is missing)."""
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            return f.read()
    except OSError:
        return b""


def position_after(path, line: int) -> tuple[int, int]:
    """(byte offset, line count) after the first `line` complete lines; the end of the file if it has fewer."""
    data = _read_from(path, 0)
    offset = count = 0
    while count < line:
        end = data.find(b"\n", offset)
        if end < 0:
            break
        offset, count = end + 1, count + 1
    return offset, count


def parse_line(raw: bytes):
    """The event dict in one line, or None when it is not a JSON object."""
    try:
        event = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return None
    return event if isinstance(event, dict) else None


def new_lines(path, offset: int, count: int) -> tuple[list, int, int]:
    """Complete lines after offset as [(line number, raw bytes)], with the new offset and line count.

    A file that shrank (rotated) starts again at line 0."""
    if _size(path) < offset:
        offset, count = 0, 0
    data = _read_from(path, offset)
    end = data.rfind(b"\n") + 1
    found = []
    for raw in data[:end].split(b"\n")[:-1]:
        count += 1
        found.append((count, raw))
    return found, offset + end, count


def wanted(event: dict, project) -> bool:
    """True when no project filter is set or the event belongs to that project."""
    return not project or event.get("project") == project


def frame(number: int, event: dict, raw: bytes) -> bytes:
    """One server-sent event: id = line number, name = event type, data = the JSON line."""
    kind = event.get("type")
    kind = kind if isinstance(kind, str) and TYPE_RE.match(kind) else "message"
    return b"id: %d\nevent: %s\ndata: %s\n\n" % (number, kind.encode(), raw)


def serve(handler, body=None) -> None:
    """Answer a live stream (default GET /api/events) until the client leaves or the server stops."""
    httpd = handler.server
    with httpd.streams_lock:
        if httpd.streams >= MAX_STREAMS:
            return handler.fail(503, TOO_MANY)
        httpd.streams += 1
    try:
        (body or stream)(handler)
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
        pass
    finally:
        with httpd.streams_lock:
            httpd.streams -= 1


def start(handler):
    """Send the stream headers and the first comment; returns the output file."""
    handler.status = 200
    handler.send_response(200)
    for key, value in (("Content-Type", "text/event-stream"), ("Cache-Control", "no-store"),
                       ("X-Accel-Buffering", "no"), ("Connection", "keep-alive")):
        handler.send_header(key, value)
    handler.end_headers()
    handler.close_connection = True
    out = handler.wfile
    out.write(b": connected\n\n")
    out.flush()
    return out


def stream(handler) -> None:
    """The body of one live stream."""
    path = paths.events()
    project = handler.query.get("project") or None
    last_id = handler.headers.get("Last-Event-ID", "").strip()
    if last_id.isdigit():
        offset, count = position_after(path, int(last_id))
    else:
        offset, count = position_after(path, 1 << 62)
    tail, ping = _tail_seconds(), _ping_seconds()
    out = start(handler)
    last_write = time.monotonic()
    stopping = handler.server.stopping
    while not stopping.is_set():
        lines, offset, count = new_lines(path, offset, count)
        for number, raw in lines:
            event = parse_line(raw)
            if event is not None and wanted(event, project):
                out.write(frame(number, event, raw))
                last_write = time.monotonic()
        if time.monotonic() - last_write >= ping:
            out.write(b": ping\n\n")
            last_write = time.monotonic()
        out.flush()
        stopping.wait(tail)


def recent(project, after, limit: int) -> dict:
    """{events: [{id, ...event}], next} for the polling fallback; without `after`, the last `limit` events."""
    lines, _, count = new_lines(paths.events(), 0, 0)
    found = []
    for number, raw in lines:
        event = parse_line(raw)
        if event is not None and wanted(event, project) and (after is None or number > after):
            found.append({"id": number, **event})
    return {"events": found[-limit:] if after is None else found[:limit], "next": count}


def _decoded(raws) -> list[str]:
    return [r.decode("utf-8", errors="replace") for r in raws]


def _tail_items(path, offset: int, count: int, parser):
    """(new frames, offset, count, parser) for the complete lines added to the transcript since last time; only
    those lines are parsed (the parser keeps its state). A file that shrank starts again with a fresh parser.

    A frame is ("item", item) for a new item, or ("update", item) for an action from an earlier tick that one of
    the new lines finished; frames come in line order."""
    lines, new_offset, new_count = new_lines(path, offset, count)
    if new_count < count or new_offset < offset:  # the file shrank and started again
        parser = transcript.Parser()
    if not lines:
        return [], new_offset, new_count, parser
    items, updates = parser.feed(_decoded(raw for _, raw in lines))
    found = [(i["line"], "item", i) for i in items] + [(i["done_line"], "update", i) for i in updates]
    found.sort(key=lambda f: f[0])
    return [(kind, item) for _, kind, item in found], new_offset, new_count, parser


def _primed(path, offset: int) -> "transcript.Parser":
    """A parser that has read the lines before offset (sent nothing), so later results find their actions."""
    parser = transcript.Parser()
    raws = _read_from(path, 0)[:offset].split(b"\n")[:-1] if offset else []
    parser.feed(_decoded(raws))
    return parser


def event_id(session, line: int) -> bytes:
    """The SSE id of a panel frame: <session id>:<transcript line>."""
    sid = str(session or "").replace("\n", "").replace("\r", "").replace(":", "")
    return ("%s:%d" % (sid, line)).encode()


def item_frame(item: dict, session=None) -> bytes:
    """One server-sent event for a panel item: id = <session>:<transcript line>, name = item."""
    return b"id: %s\nevent: item\ndata: %s\n\n" % (event_id(session, item["line"]), json.dumps(item).encode())


def update_frame(item: dict, session=None) -> bytes:
    """The server-sent event for an action, already sent, that has now finished: id = <session>:<the line that
    finished it>, name = update, data = {type: update, id: the action's tool id, line, status, excerpt}."""
    data = {"type": "update", "id": item["id"], "line": item["line"], "status": item["status"],
            "excerpt": item.get("excerpt", "")}
    return b"id: %s\nevent: update\ndata: %s\n\n" % (event_id(session, item["done_line"]), json.dumps(data).encode())


def session_frame(session_id) -> bytes:
    """The server-sent event telling the client the agent's session changed."""
    return b"event: session\ndata: %s\n\n" % json.dumps({"session_id": session_id}).encode()


def resume_line(handler, session) -> int | None:
    """The transcript line to resume after: ?after=<n> (this session), or a Last-Event-ID of <session>:<n> whose
    session is the current one; None means start at the end (no resume asked); -1 means the asked-for session is
    not this one, so start at line 0 with a session frame."""
    after = (handler.query.get("after") or "").strip()
    if after:
        return int(after) if after.isdigit() else None
    last = handler.headers.get("Last-Event-ID", "").strip()
    if not last:
        return None
    sid, _, line = last.rpartition(":")
    if sid and session and sid == str(session) and line.isdigit():
        return int(line)
    return -1


def agent_stream(handler) -> None:
    """The body of GET /api/agent/stream: panel items (and action updates) as the agent's transcript grows, a frame
    when the session changes."""
    found = agentlink.find()
    session = found["session_id"] if found else None
    path = found["transcript"] if found else None
    resume = resume_line(handler, session)
    offset = count = 0
    if path:
        offset, count = position_after(path, 1 << 62 if resume is None else max(resume, 0))
    parser = _primed(path, offset) if path else transcript.Parser()
    tail, ping = _tail_seconds(), _ping_seconds()
    out = start(handler)
    if resume == -1 and session is not None:
        out.write(session_frame(session))
    last_write = time.monotonic()
    stopping = handler.server.stopping
    while not stopping.is_set():
        found = agentlink.find()
        if found is not None and found["session_id"] != session:
            session, path = found["session_id"], found["transcript"]
            offset = count = 0
            parser = transcript.Parser()
            out.write(session_frame(session))
            last_write = time.monotonic()
        if path:
            found, offset, count, parser = _tail_items(path, offset, count, parser)
            for kind, item in found:
                out.write(item_frame(item, session) if kind == "item" else update_frame(item, session))
                last_write = time.monotonic()
        if time.monotonic() - last_write >= ping:
            out.write(b": ping\n\n")
            last_write = time.monotonic()
        out.flush()
        stopping.wait(tail)
