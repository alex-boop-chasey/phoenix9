"""Tests for the chat API routes and the chat field on project rows (fakes only)."""
import pytest

from phoenix9 import projectchat
from phoenix9.ops import projects
from test_api_server import ORIGIN, POST_HEADERS, api, dist, make_project  # noqa: F401  (fixtures)

STATE = {"state": "awake", "bridge_session_id": "s1", "web_url": "w", "app_url": "a", "last_active": 5}


@pytest.fixture
def chats(api, monkeypatch):
    """A project called demo with projectchat functions faked; returns the list of calls."""
    make_project("demo")
    calls = []
    monkeypatch.setattr(projectchat, "state", lambda p, a: STATE)
    monkeypatch.setattr(projectchat, "open_", lambda p, a, who: calls.append(("open", p, who)) or
                        {"state": "awake", "web_url": "w", "app_url": "a", "bridge_session_id": "s1", "message": "ok",
                         "woke": True, "fresh": False})
    monkeypatch.setattr(projectchat, "sleep", lambda p, a, who: calls.append(("sleep", p, who)) or
                        {"state": "asleep", "changed": True, "message": "zzz"})
    monkeypatch.setattr(projectchat, "forget", lambda p, a, who: calls.append(("forget", p, who)) or
                        {"state": "none", "changed": True, "message": "bye"})
    return calls


def test_get_state(api, chats):
    """GET returns the state object."""
    status, body = api("/api/chat/demo")
    assert status == 200 and body["data"] == STATE


@pytest.mark.parametrize("route", ["open", "sleep", "forget"])
def test_posts_need_header_and_origin(api, chats, route):
    """A POST without X-Phoenix or with a bad Origin is refused and does nothing."""
    body = {"confirm": True}
    assert api(f"/api/chat/demo/{route}", "POST", {"Origin": ORIGIN}, body)[0] == 403
    assert api(f"/api/chat/demo/{route}", "POST", {**POST_HEADERS, "Origin": "http://evil.example"}, body)[0] == 403
    assert chats == []


def test_open_sleep_forget_replies(api, chats):
    """Each route returns its answer and runs as the dashboard."""
    assert api("/api/chat/demo/open", "POST", POST_HEADERS, {})[1]["data"]["message"] == "ok"
    assert api("/api/chat/demo/sleep", "POST", POST_HEADERS, {})[1]["data"] == {"state": "asleep", "changed": True, "message": "zzz"}
    assert api("/api/chat/demo/forget", "POST", POST_HEADERS, {"confirm": True})[1]["data"]["state"] == "none"
    assert chats == [("open", "demo", "dashboard"), ("sleep", "demo", "dashboard"), ("forget", "demo", "dashboard")]


def test_off_route_is_gone(api, chats):
    """The old off route no longer exists; forget replaced it."""
    assert api("/api/chat/demo/off", "POST", POST_HEADERS, {"confirm": True})[0] == 404
    assert chats == []


def test_no_request_time_limit_shorter_than_the_chat_wait():
    """Opening can take up to start_wait_seconds; the server must not cut a request off before that plus 10 s."""
    from phoenix9 import settings
    from phoenix9.api.server import Handler
    limit = Handler.timeout
    assert limit is None or limit >= settings.chat_settings()["start_wait_seconds"] + 10


def test_unknown_project_is_404(api, chats):
    """An unknown project is 404 on every route."""
    assert api("/api/chat/nope")[0] == 404
    for route in ("open", "sleep", "forget"):
        assert api(f"/api/chat/nope/{route}", "POST", POST_HEADERS, {"confirm": True})[0] == 404


def test_forget_needs_confirm(api, chats):
    """Forget without confirm is 400 with a plain message."""
    status, body = api("/api/chat/demo/forget", "POST", POST_HEADERS, {})
    assert status == 400 and "confirm" in body["message"] and chats == []


def test_start_timeout_is_503(api, chats, monkeypatch):
    """A start timeout is 503 with its message."""
    def slow(p, a, who):
        raise projectchat.NotReady("The chat didn't wake in 60 seconds. Press Chat again.")
    monkeypatch.setattr(projectchat, "open_", slow)
    status, body = api("/api/chat/demo/open", "POST", POST_HEADERS, {})
    assert status == 503 and body["message"] == "The chat didn't wake in 60 seconds. Press Chat again."


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
