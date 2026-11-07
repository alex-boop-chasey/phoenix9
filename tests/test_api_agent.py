"""Tests for the agent API routes and the live agent stream."""
import http.client
import json
import threading
import types

import pytest

from phoenix9 import agentlink, paths
from phoenix9.api import server
from phoenix9.ops import common
from fakes import FakeHost
from test_api_events import read_until
from test_api_server import POST_HEADERS, api, dist  # noqa: F401  (fixtures)

CH = "/root/.claude"
TDIR = CH + "/projects/-srv-projects-home"
S1 = "aaaaaaaa-1111-4111-8111-111111111111"
S0 = "bbbbbbbb-0000-4000-8000-000000000000"


def say(role, text, n, sid=S1):
    """One simple transcript line."""
    msg = {"role": "user", "content": text} if role == "user" else {"content": [{"type": "text", "text": text}]}
    return json.dumps({"type": role, "message": msg, "timestamp": "2026-11-06T10:00:0%dZ" % n, "sessionId": sid})


@pytest.fixture
def host(api, monkeypatch):
    """A fake host with a live agent session, wired into the ops and the agent link."""
    h = FakeHost()
    monkeypatch.setattr(common, "make_adapters", lambda: types.SimpleNamespace(host=h))
    monkeypatch.setattr(agentlink, "Host", lambda: h)
    h.files[CH + "/sessions/100.json"] = json.dumps({
        "pid": 100, "cwd": "/srv/projects/home", "name": "Phoenix agent", "status": "idle",
        "messagingSocketPath": "/tmp/cc-socks-0/x.sock", "kind": "interactive", "sessionId": S1})
    h.files["/tmp/cc-socks-0/x.sock"] = ""
    h.pids.add(100)
    h.files[TDIR + "/" + S1 + ".jsonl"] = "\n".join([say("user", "hi", 0), say("assistant", "yo", 1)]) + "\n"
    h.files[TDIR + "/" + S0 + ".jsonl"] = say("user", "old", 0, S0) + "\n"
    h.stats[TDIR + "/" + S1 + ".jsonl"] = {"mode": 0o600, "uid": 0, "mtime": 2000}
    h.stats[TDIR + "/" + S0 + ".jsonl"] = {"mode": 0o600, "uid": 0, "mtime": 1000}
    return h


@pytest.fixture
def sent(monkeypatch):
    """Capture what would be written to the inbox socket."""
    wrote = []
    monkeypatch.setattr(agentlink, "connect_and_write", lambda path, data, timeout=0: wrote.append((path, data)))
    return wrote


def test_agent_state(api, host):
    """GET /api/agent shows the state, and asleep once the process is gone."""
    status, body = api("/api/agent")
    assert status == 200 and body["data"]["state"] == "idle" and body["data"]["session_id"] == S1
    host.pids.clear()
    assert api("/api/agent")[1]["data"]["state"] == "asleep"


def test_messages_after_and_limit(api, host):
    """GET /api/agent/messages honours after and limit, and refuses odd numbers."""
    data = api("/api/agent/messages")[1]["data"]
    assert [i["line"] for i in data["items"]] == [1, 2] and data["last_line"] == 2
    assert [i["line"] for i in api("/api/agent/messages?after=1")[1]["data"]["items"]] == [2]
    assert len(api("/api/agent/messages?limit=1")[1]["data"]["items"]) == 1
    assert api("/api/agent/messages?after=x")[0] == 400
    assert api("/api/agent/messages?limit=-1")[0] == 400


def test_sessions_newest_first(api, host):
    """GET /api/agent/sessions lists earlier conversations."""
    data = api("/api/agent/sessions")[1]["data"]
    assert [s["session_id"] for s in data] == [S1, S0]


def test_send_posts_to_the_inbox(api, host, sent):
    """POST /api/agent/send writes one wire line to the agent's socket."""
    status, body = api("/api/agent/send", "POST", POST_HEADERS, {"text": "hello <b>", "context": {"page": "home"}})
    assert status == 200 and body["data"]["sent"] is True
    assert sent[0][0] == "/tmp/cc-socks-0/x.sock"
    assert "hello &lt;b&gt;" in json.loads(sent[0][1])["message"]["content"]


def test_send_refused_without_header_or_with_bad_origin(api, host, sent):
    """The write checks apply to send."""
    body = {"text": "hi"}
    assert api("/api/agent/send", "POST", {"Origin": POST_HEADERS["Origin"]}, body)[0] == 403
    assert api("/api/agent/send", "POST", {**POST_HEADERS, "Origin": "http://evil.test"}, body)[0] == 403
    assert api("/api/agent/send", "POST", {"X-Phoenix": "1"}, body)[0] == 403
    assert sent == []


def test_send_asleep_is_503_with_the_reason(api, host, sent):
    """An asleep agent gives 503 and the plain reason."""
    host.pids.clear()
    status, body = api("/api/agent/send", "POST", POST_HEADERS, {"text": "hi"})
    assert status == 503 and "asleep" in body["message"] and sent == []


def test_send_over_the_cap_is_400(api, host, sent):
    """A message over the cap gives 400 and nothing is sent."""
    text = "x" * (agentlink.MAX_CHARS + 1)
    status, body = api("/api/agent/send", "POST", POST_HEADERS, {"text": text})
    assert status == 400 and str(agentlink.MAX_CHARS) in body["message"] and sent == []


def test_send_bad_body_is_400(api, host, sent):
    """Empty text or a non-object context gives 400."""
    assert api("/api/agent/send", "POST", POST_HEADERS, {"text": " "})[0] == 400
    assert api("/api/agent/send", "POST", POST_HEADERS, {"text": "a", "context": 3})[0] == 400


# ---- the live stream ----

@pytest.fixture
def live(monkeypatch):
    """A running API server with fast tail/ping intervals; returns (httpd, port)."""
    monkeypatch.setenv("PHOENIX_API_TAIL_SECONDS", "0.05")
    monkeypatch.setenv("PHOENIX_API_PING_SECONDS", "0.3")
    httpd = server.make_server(0)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    yield httpd, httpd.server_address[1]
    httpd.stopping.set()
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def tmp_session(tmp_path, monkeypatch):
    """A tmp transcript folder and a find() that follows `state['id']`."""
    state = {"id": "a", "asleep": False}

    def path(sid):
        return tmp_path / (sid + ".jsonl")

    def find(*args, **kwargs):
        if state["asleep"]:
            return None
        return {"pid": 1, "session_id": state["id"], "name": "Phoenix agent", "socket": "x",
                "transcript": str(path(state["id"])), "status": "idle"}

    monkeypatch.setattr(agentlink, "find", find)
    state["path"] = path
    return state


def add(path, *lines):
    """Append transcript lines."""
    with open(path, "a") as f:
        for text in lines:
            f.write(text + "\n")


def open_stream(port, path="/api/agent/stream", headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    conn.request("GET", path, headers=headers or {})
    return conn, conn.getresponse()


def test_stream_sends_only_new_items(live, tmp_session):
    """A stream starts at the end and sends one frame per new item, id = line."""
    add(tmp_session["path"]("a"), say("user", "old", 0))
    conn, resp = open_stream(live[1])
    assert resp.status == 200 and resp.getheader("Content-Type") == "text/event-stream"
    read_until(resp, ": connected")
    add(tmp_session["path"]("a"), say("assistant", "fresh answer", 1))
    got = read_until(resp, "fresh answer")
    assert "id: 2\nevent: item" in got and "old" not in got
    conn.close()


def test_stream_resumes_after_a_line(live, tmp_session):
    """?after= replays what came after that line."""
    add(tmp_session["path"]("a"), say("user", "one", 0), say("assistant", "two", 1))
    conn, resp = open_stream(live[1], "/api/agent/stream?after=1")
    got = read_until(resp, "two")
    assert "id: 2" in got and "one" not in got
    conn.close()


def test_stream_session_change(live, tmp_session):
    """A new session id gives an event: session frame, then its items from line 1."""
    add(tmp_session["path"]("a"), say("user", "old", 0))
    conn, resp = open_stream(live[1])
    read_until(resp, ": ping")  # the loop has run, so the first session is known
    add(tmp_session["path"]("b"), say("user", "new session", 0, "b"))
    tmp_session["id"] = "b"
    got = read_until(resp, "new session")
    assert "event: session\ndata: {\"session_id\": \"b\"}" in got
    assert "id: 1\nevent: item" in got
    conn.close()


def test_stream_pings(live, tmp_session):
    """An idle stream sends pings."""
    tmp_session["asleep"] = True
    conn, resp = open_stream(live[1])
    assert ": ping" in read_until(resp, ": ping")
    conn.close()


def tool_use(tid, cmd, sid="a"):
    return json.dumps({"type": "assistant", "sessionId": sid, "message": {"content": [
        {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}]}})


def tool_result(tid, text, sid="a", error=False):
    return json.dumps({"type": "user", "sessionId": sid, "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": error}]}})


def frames(text, kind):
    """The data of every frame of one event kind."""
    out = []
    for block in text.split("\n\n"):
        lines = block.split("\n")
        if "event: %s" % kind in lines:
            out.append(json.loads(next(x for x in lines if x.startswith("data: "))[6:]))
    return out


def test_stream_sends_an_update_when_an_action_finishes(live, tmp_session):
    """An action sent while running gets an `update` frame (same action id) with its status and excerpt."""
    path = tmp_session["path"]("a")
    add(path, say("user", "go", 0, "a"))
    conn, resp = open_stream(live[1])
    read_until(resp, ": connected")
    add(path, tool_use("t1", "make build"))
    got = read_until(resp, "make build")
    assert frames(got, "item")[0]["status"] == "running"
    add(path, tool_result("t1", "line1\nall built"))
    got = read_until(resp, "all built")
    [update] = frames(got, "update")
    assert update == {"type": "update", "id": "t1", "line": 2, "status": "ok", "excerpt": "line1\nall built"}
    assert "event: item" not in got        # the action is not sent again as a new item
    conn.close()


def test_stream_resume_sends_updates_for_actions_finished_after_that_point(live, tmp_session):
    path = tmp_session["path"]("a")
    add(path, tool_use("t1", "slow job"), say("assistant", "waiting", 1, "a"), tool_result("t1", "finished", error=True))
    conn, resp = open_stream(live[1], "/api/agent/stream?after=2")
    got = read_until(resp, "finished")
    [update] = frames(got, "update")
    assert update["id"] == "t1" and update["status"] == "error" and update["excerpt"] == "finished"
    conn.close()
