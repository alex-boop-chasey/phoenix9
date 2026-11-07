"""Tests for the chat API routes and the chat field on project rows (fakes only)."""
import pytest

from phoenix9 import projectchat
from phoenix9.ops import projects
from test_api_server import ORIGIN, POST_HEADERS, api, dist, make_project  # noqa: F401  (fixtures)

STATE = {"state": "live", "bridge_session_id": "s1", "web_url": "w", "app_url": "a", "last_active": 5}


@pytest.fixture
def chats(api, monkeypatch):
    """A project called demo with projectchat functions faked; returns the list of calls."""
    make_project("demo")
    calls = []
    monkeypatch.setattr(projectchat, "state", lambda p, a: STATE)
    monkeypatch.setattr(projectchat, "open_", lambda p, a, who: calls.append(("open", p, who)) or
                        {"state": "live", "web_url": "w", "app_url": "a", "bridge_session_id": "s1", "message": "ok"})
    monkeypatch.setattr(projectchat, "sleep", lambda p, a, who: calls.append(("sleep", p, who)) or
                        {"state": "sleeping", "changed": True, "message": "zzz"})
    monkeypatch.setattr(projectchat, "off", lambda p, a, who: calls.append(("off", p, who)) or
                        {"state": "off", "changed": True, "message": "bye"})
    return calls


def test_get_state(api, chats):
    """GET returns the state object."""
    status, body = api("/api/chat/demo")
    assert status == 200 and body["data"] == STATE


@pytest.mark.parametrize("route", ["open", "sleep", "off"])
def test_posts_need_header_and_origin(api, chats, route):
    """A POST without X-Phoenix or with a bad Origin is refused and does nothing."""
    body = {"confirm": True}
    assert api(f"/api/chat/demo/{route}", "POST", {"Origin": ORIGIN}, body)[0] == 403
    assert api(f"/api/chat/demo/{route}", "POST", {**POST_HEADERS, "Origin": "http://evil.example"}, body)[0] == 403
    assert chats == []


def test_open_sleep_off_replies(api, chats):
    """Each route returns its answer and runs as the dashboard."""
    assert api("/api/chat/demo/open", "POST", POST_HEADERS, {})[1]["data"]["message"] == "ok"
    assert api("/api/chat/demo/sleep", "POST", POST_HEADERS, {})[1]["data"] == {"state": "sleeping", "changed": True, "message": "zzz"}
    assert api("/api/chat/demo/off", "POST", POST_HEADERS, {"confirm": True})[1]["data"]["state"] == "off"
    assert chats == [("open", "demo", "dashboard"), ("sleep", "demo", "dashboard"), ("off", "demo", "dashboard")]


def test_unknown_project_is_404(api, chats):
    """An unknown project is 404 on every route."""
    assert api("/api/chat/nope")[0] == 404
    for route in ("open", "sleep", "off"):
        assert api(f"/api/chat/nope/{route}", "POST", POST_HEADERS, {"confirm": True})[0] == 404


def test_off_needs_confirm(api, chats):
    """Off without confirm is 400 with a plain message."""
    status, body = api("/api/chat/demo/off", "POST", POST_HEADERS, {})
    assert status == 400 and "confirm" in body["message"] and chats == []


def test_start_timeout_is_503(api, chats, monkeypatch):
    """A start timeout is 503 with its message."""
    def slow(p, a, who):
        raise projectchat.NotReady("The chat is still starting.")
    monkeypatch.setattr(projectchat, "open_", slow)
    status, body = api("/api/chat/demo/open", "POST", POST_HEADERS, {})
    assert status == 503 and body["message"] == "The chat is still starting."


def test_rows_have_chat(api, chats):
    """Rows and query rows carry the chat state."""
    assert [r["chat"] for r in projects.rows()] == [STATE]
    assert projects.query()["rest"][0]["chat"] == STATE


def test_row_chat_null_when_state_fails(api, chats, monkeypatch):
    """One project's failure gives chat None while the others keep theirs."""
    make_project("other")

    def state(p, a):
        if p == "demo":
            raise RuntimeError("boom")
        return STATE
    monkeypatch.setattr(projectchat, "state", state)
    got = {r["name"]: r["chat"] for r in projects.rows()}
    assert got == {"demo": None, "other": STATE}
