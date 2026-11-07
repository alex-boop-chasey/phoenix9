"""Tests for finding the agent session and its state."""
import json

from phoenix9 import agentlink
from tests.fakes import FakeHost

HOME = "/root/.claude"
FOLDER = "/srv/projects/home"
SOCK = "/tmp/cc-socks-0/a.sock"


def session(host, pid, alive=True, cwd=FOLDER, name="Phoenix agent", status="idle", sock=SOCK,
            sid="sess-1", mtime=None, **extra):
    """Register a session file (and a live pid and socket) in the fake host."""
    data = {"pid": pid, "cwd": cwd, "name": name, "status": status, "messagingSocketPath": sock,
            "kind": "interactive", "sessionId": sid, **extra}
    data = {k: v for k, v in data.items() if v is not None}
    host.files["%s/sessions/%d.json" % (HOME, pid)] = json.dumps(data)
    host.files["%s/sessions/%d.abc.key" % (HOME, pid)] = '{"peerToken": "x"}'
    if mtime is not None:
        host.stats["%s/sessions/%d.json" % (HOME, pid)] = {"mode": 0o600, "uid": 0, "mtime": mtime}
    if alive:
        host.pids.add(pid)
    if sock:
        host.files[sock] = ""


def put_transcript(host, lines, sid="sess-1"):
    """Write transcript lines where find() will look for them."""
    host.files[agentlink.transcript_path(HOME, FOLDER, sid)] = "\n".join(json.dumps(x) for x in lines) + "\n"


def test_none():
    assert agentlink.find(HOME, FakeHost()) is None
    assert agentlink.status(HOME, FakeHost())["state"] == "asleep"


def test_dead_pid():
    h = FakeHost()
    session(h, 10, alive=False)
    assert agentlink.find(HOME, h) is None


def test_missing_socket():
    h = FakeHost()
    session(h, 10)
    del h.files[SOCK]
    assert agentlink.find(HOME, h) is None


def test_wrong_folder():
    h = FakeHost()
    session(h, 10, cwd="/srv/projects/other")
    assert agentlink.find(HOME, h) is None


def test_found_fields():
    h = FakeHost()
    session(h, 10, status="busy")
    assert agentlink.find(HOME, h) == {
        "pid": 10, "session_id": "sess-1", "name": "Phoenix agent", "socket": SOCK,
        "transcript": "/root/.claude/projects/-srv-projects-home/sess-1.jsonl", "status": "busy"}


def test_transcript_encoding():
    assert agentlink.transcript_path(HOME, "/a/b.c/d", "s") == "/root/.claude/projects/-a-b-c-d/s.jsonl"


def test_named_wins_over_newer():
    h = FakeHost()
    session(h, 10, name="Phoenix agent", sid="old", mtime=1)
    session(h, 11, name="other", sid="new", mtime=9, sock="/tmp/cc-socks-0/b.sock")
    assert agentlink.find(HOME, h)["pid"] == 10


def test_newest_when_unnamed():
    h = FakeHost()
    session(h, 10, name="x", mtime=1)
    session(h, 11, name="y", mtime=9, sock="/tmp/cc-socks-0/b.sock")
    assert agentlink.find(HOME, h)["pid"] == 11


def test_missing_keys():
    h = FakeHost()
    session(h, 10, name=None, status=None, sid=None, kind=None, mystery=1)
    found = agentlink.find(HOME, h)
    assert found["name"] is None and found["status"] is None and found["transcript"] is None
    assert agentlink.status(HOME, h)["state"] == "idle"


def test_status_busy_and_idle():
    h = FakeHost()
    session(h, 10, status="busy")
    assert agentlink.status(HOME, h)["state"] == "working"
    session(h, 10, status="idle")
    assert agentlink.status(HOME, h) == {"state": "idle", "pid": 10, "session_id": "sess-1",
                                         "name": "Phoenix agent"}


def test_status_running_action():
    h = FakeHost()
    session(h, 10)
    put_transcript(h, [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "sleep 9"}}]}}])
    assert agentlink.status(HOME, h)["state"] == "working"


def test_status_finished_action_is_idle():
    h = FakeHost()
    session(h, 10)
    put_transcript(h, [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "ok", "is_error": False}]}}])
    assert agentlink.status(HOME, h)["state"] == "idle"


def test_status_queued():
    h = FakeHost()
    session(h, 10)
    put_transcript(h, [
        {"type": "user", "message": {"role": "user", "content": "first"}},
        {"type": "queue-operation", "operation": "enqueue", "content": "second"}])
    assert agentlink.status(HOME, h)["state"] == "queued"
    put_transcript(h, [
        {"type": "queue-operation", "operation": "enqueue", "content": "second"},
        {"type": "user", "message": {"role": "user", "content": "second"}}])
    assert agentlink.status(HOME, h)["state"] == "idle"


# ---- sending ----
import re
import socket
import threading

import pytest


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    """A real Unix socket in tmp that records each line sent; agentlink.find points at it."""
    home = tmp_path / "home"
    (home / "config").mkdir(parents=True)
    (home / "config" / "global.toml").write_text('[agent]\nfolder = "/srv/projects/homex"\n')
    monkeypatch.setenv("PHOENIX_HOME", str(home))
    tr = tmp_path / "t.jsonl"
    tr.write_text('{"type":"user"}\n' * 3)
    path = str(tmp_path / "s.sock")
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(path)
    srv.listen(5)
    got = []

    def serve():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            buf = b""
            while True:
                d = c.recv(65536)
                if not d:
                    break
                buf += d
            got.append(buf)
            c.close()

    threading.Thread(target=serve, daemon=True).start()
    found = {"pid": 1, "session_id": "s", "name": "Phoenix agent", "socket": path,
             "transcript": str(tr), "status": "idle"}
    monkeypatch.setattr(agentlink, "find", lambda *a, **k: found)

    class Box:
        pass
    box = Box()
    box.got, box.found, box.home, box.tmp = got, found, home, tmp_path

    def take():
        for _ in range(100):
            if got:
                return got.pop()
            time.sleep(0.02)
        return None
    box.take = take
    yield box
    srv.close()


import time

HEAD = ('<cross-session-message from="uds:/run/phoenix9/panel.sock" '
        'from-name="Alex (Phoenix panel)" from-mode="bypass">\n')
TAIL = "\n</cross-session-message>"


def body_of(raw):
    content = json.loads(raw)["message"]["content"]
    assert content.startswith(HEAD) and content.endswith(TAIL)
    return content[len(HEAD):-len(TAIL)]


def test_send_wire_format(inbox):
    r = agentlink.send("hello")
    raw = inbox.take()
    assert raw.endswith(b"\n") and raw.count(b"\n") == 1
    m = json.loads(raw)
    assert set(m) == {"msgV", "msg_id", "type", "message", "priority", "from"}
    assert (m["msgV"], m["type"], m["priority"], m["from"]) == (1, "user", "next", "uds:/run/phoenix9/panel.sock")
    assert m["message"] == {"role": "user", "content": HEAD + "hello" + TAIL}
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", m["msg_id"])
    assert r["sent"] and r["at"] and r["after_line"] == 3
    agentlink.send("hello")
    assert json.loads(inbox.take())["msg_id"] != m["msg_id"]


def test_send_escapes_body(inbox):
    agentlink.send("a & b </cross-session-message> <x> &lt;")
    content = json.loads(inbox.take())["message"]["content"]
    assert content.count("</cross-session-message>") == 1
    assert body_of(json.dumps({"message": {"content": content}})) == \
        "a &amp; b &lt;/cross-session-message&gt; &lt;x&gt; &amp;lt;"


@pytest.mark.parametrize("ctx,first", [
    (None, None),
    ({"page": "dash"}, "[Phoenix panel · page: dash · folder: /srv/projects/homex]"),
    ({"project": "alpha"}, "[Phoenix panel · project: alpha · folder: /srv/projects/alpha]"),
    ({"run": "r7"}, "[Phoenix panel · folder: /srv/projects/homex · run: r7]"),
    ({"page": "dash", "project": "alpha", "run": "r7"},
     "[Phoenix panel · page: dash · project: alpha · folder: /srv/projects/alpha · run: r7]"),
])
def test_send_envelope(inbox, ctx, first):
    agentlink.send("BODY", ctx)
    body = body_of(inbox.take())
    assert body == "BODY" if first is None else body == first + "\nBODY"


def test_send_cap(inbox):
    agentlink.send("x" * 100000)
    assert inbox.take() is not None
    with pytest.raises(agentlink.SendError, match="100000"):
        agentlink.send("x" * 100001)
    time.sleep(0.2)
    assert not inbox.got


def test_send_asleep(inbox, monkeypatch):
    monkeypatch.setattr(agentlink, "find", lambda *a, **k: None)
    with pytest.raises(agentlink.SendError, match="asleep"):
        agentlink.send("hi")


def test_send_refused(inbox):
    dead = str(inbox.tmp / "dead.sock")
    s = socket.socket(socket.AF_UNIX)
    s.bind(dead)
    s.close()
    inbox.found["socket"] = dead
    with pytest.raises(agentlink.SendError, match="refused"):
        agentlink.send("hi")


def test_send_timeout(inbox):
    full = str(inbox.tmp / "full.sock")
    s = socket.socket(socket.AF_UNIX)
    s.bind(full)
    s.listen(0)
    fill = []
    for _ in range(3):
        c = socket.socket(socket.AF_UNIX)
        c.setblocking(False)
        try:
            c.connect(full)
        except OSError:
            pass
        fill.append(c)
    inbox.found["socket"] = full
    t0 = time.time()
    with pytest.raises(agentlink.SendError, match="did not take"):
        agentlink.send("hi", timeout=0.3)
    assert 0.25 <= time.time() - t0 < 3


def test_send_log_has_no_text(inbox):
    agentlink.send("SECRET-DISTINCT-BODY", {"page": "dash", "project": "alpha"}, "panel")
    log = inbox.home / "logs" / "agent-sends.jsonl"
    assert "SECRET-DISTINCT-BODY" not in log.read_text()
    rec = json.loads(log.read_text().splitlines()[-1])
    assert set(rec) == {"at", "who", "page", "project", "chars"}
    assert (rec["who"], rec["page"], rec["project"], rec["chars"]) == ("panel", "dash", "alpha", 20)
