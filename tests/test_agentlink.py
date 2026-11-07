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
