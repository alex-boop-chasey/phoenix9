"""Tests for /api/agent-next: phoenix-api passes the browser's calls to the agent service, adding the token."""
import json
import threading
import urllib.request

from phoenix9 import paths
from phoenix9.ops import common
from test_api_server import POST_HEADERS, api, dist  # noqa: F401  (fixtures)

TOKEN = "fake-agent-token-0123456789"


def agent(api):
    """The fake agent service the api fixture's server is using."""
    return common.make_adapters().agentnext


def test_json_call_is_passed_through(api):
    fake = agent(api)
    fake.chunks = [b'{"running": true, "key_present": false}']
    status, resp, content = api("/api/agent-next/status?x=1", raw=True)
    assert status == 200 and json.loads(content) == {"running": True, "key_present": False,
                                       "message": "The new agent has no API key yet. See deploy/agentkit/README.md."}
    assert resp.headers["Content-Type"] == "application/json"
    call = fake.calls[0]
    assert call["method"] == "GET" and call["url"] == "http://agent.invalid/status?x=1"


def test_post_is_passed_through_with_its_body(api):
    fake = agent(api)
    fake.status, fake.chunks = 201, [b'{"id": "t1"}']
    status, body = api("/api/agent-next/threads/t1/runs", "POST", POST_HEADERS, {"message": "hi"})
    assert status == 201 and body == {"id": "t1"}
    call = fake.calls[0]
    assert call["method"] == "POST" and call["url"] == "http://agent.invalid/threads/t1/runs"
    assert json.loads(call["body"]) == {"message": "hi"}


def test_upstream_errors_keep_their_status(api):
    fake = agent(api)
    fake.status, fake.chunks = 404, [b'{"detail": "no such thread"}']
    assert api("/api/agent-next/threads/zzz")[0] == 404


def test_stream_is_passed_chunk_by_chunk(api):
    fake = agent(api)
    fake.content_type = "text/event-stream"
    fake.chunks = [b"data: one\n\n", b"data: two\n\n"]
    first_seen = threading.Event()
    fake.gate = lambda i: assert_first_arrived(first_seen)
    resp = urllib.request.urlopen(urllib.request.Request(api.base + "/api/agent-next/threads/t1/stream",
                                                         headers={"Last-Event-ID": "4"}))
    assert resp.headers["Content-Type"].startswith("text/event-stream")
    assert resp.readline() == b"data: one\n"
    first_seen.set()   # the second chunk is only sent after the first one reached the browser
    assert resp.readline() == b"\n"
    assert resp.readline() == b"data: two\n"
    resp.close()
    assert fake.calls[0]["headers"]["Last-Event-ID"] == "4"


def assert_first_arrived(event):
    """Block the fake's second chunk until the test has read the first (fails the stream if it never does)."""
    assert event.wait(10), "the first chunk was held back"


def test_token_is_added_but_never_echoed(api):
    fake = agent(api)
    fake.chunks = [b'{"ok": true}']
    status, resp, content = api("/api/agent-next/status", raw=True, headers={"Authorization": "Bearer browser-own"})
    assert status == 200
    assert fake.calls[0]["headers"]["Authorization"] == "Bearer " + TOKEN
    assert "browser-own" not in fake.calls[0]["headers"]["Authorization"]
    assert TOKEN.encode() not in content
    assert TOKEN not in str(resp.headers)
    api("/api/agent-next/threads", "POST", POST_HEADERS, {})
    assert TOKEN not in (paths.logs() / "api.log").read_text()


def test_missing_token_file_is_a_plain_503(api):
    fake = agent(api)
    fake.token_file = "/nonexistent/token"
    status, body = api("/api/agent-next/status")
    assert status == 503 and "isn't set up" in body["message"] and fake.calls == []


def test_write_without_the_phoenix_header_is_refused(api):
    fake = agent(api)
    status, body = api("/api/agent-next/threads", "POST", {"Origin": POST_HEADERS["Origin"]}, {})
    assert status == 403 and body["ok"] is False
    status, _ = api("/api/agent-next/threads", "POST", {"X-Phoenix": "1"}, {})
    assert status == 403
    assert fake.calls == []


def test_odd_paths_are_not_passed(api):
    fake = agent(api)
    assert api("/api/agent-next")[0] == 404
    assert api("/api/agent-next/../health")[0] == 404
    assert api("/api/agent-nextx/status")[0] == 404
    assert api("/api/agent-next/a/../status")[0] == 404
    assert fake.calls == []


ROUTES = [("GET", "/status"), ("GET", "/threads"), ("POST", "/threads"), ("GET", "/threads/t1"),
          ("POST", "/threads/t1/runs"), ("GET", "/threads/t1/stream?after=3"), ("POST", "/threads/t1/stop"),
          ("POST", "/approvals/a1"), ("POST", "/browser-results/b1"), ("GET", "/spend")]


def test_every_agent_route_is_passed_through(api):
    fake = agent(api)
    for method, path in ROUTES:
        fake.calls.clear()
        fake.chunks = [b'{"ok": true}']
        status, _ = api("/api/agent-next" + path, method, POST_HEADERS if method == "POST" else None,
                        {"message": "hi"} if method == "POST" else None)
        assert status == 200, path
        assert fake.calls[0]["method"] == method and fake.calls[0]["url"] == "http://agent.invalid" + path


def test_service_down_is_a_plain_503(api):
    fake = agent(api)
    fake.down = True
    status, body = api("/api/agent-next/threads")
    assert status == 503
    assert body["message"] == "The new agent isn't running. Start phoenix-agentkit (see deploy/agentkit/README.md)."
    assert TOKEN not in json.dumps(body)


def test_no_key_message_is_added_to_status(api):
    fake = agent(api)
    fake.chunks = [b'{"running": true, "key_present": false, "pack": "phoenix", "model": "m"}']
    status, body = api("/api/agent-next/status")
    assert status == 200 and body["message"] == "The new agent has no API key yet. See deploy/agentkit/README.md."
    fake.chunks = [b'{"running": true, "key_present": true}']
    assert "message" not in api("/api/agent-next/status")[1]


def test_token_is_not_in_any_log_line_even_when_down(api):
    fake = agent(api)
    fake.down = True
    api("/api/agent-next/status")
    log = paths.logs() / "api.log"
    assert TOKEN not in (log.read_text() if log.exists() else "")


def test_handoffs_is_refused(api):
    fake = agent(api)
    for path in ("/handoffs", "/handoffs/", "/Handoffs", "/%68andoffs", "/handoffs?x=1"):
        status, body = api("/api/agent-next" + path, "POST", POST_HEADERS,
                           {"run_id": "r", "task": 1, "gate_id": "r.1", "project": "p"})
        assert status == 404 and body["message"] == "Not found.", path
    assert api("/api/agent-next/handoffs")[0] == 404
    assert fake.calls == []
