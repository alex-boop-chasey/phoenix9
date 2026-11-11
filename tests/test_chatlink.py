"""The project-chat paths (find, send, sleep check) work through phoenix9.chatlink, with fakes only."""
import json

import pytest

from phoenix9 import chat, chatlink, paths, projectchat as pc
from tests.fakes import FakeHost
from tests.fakes.chathost import HOME, SID, SOCK, chat_adapters

FOLDER = "/srv/projects/alpha"


@pytest.fixture(autouse=True)
def _reset():
    chatlink.forget()


def registry_host(folder=FOLDER):
    """A fake host with one live session working in folder."""
    h = FakeHost()
    data = {"pid": 10, "cwd": folder, "name": "alpha", "status": "idle", "messagingSocketPath": SOCK,
            "kind": "interactive", "sessionId": SID, "startedAt": 1, "bridgeSessionId": "session_B_1"}
    h.files["%s/sessions/10.json" % HOME] = json.dumps(data)
    h.files[SOCK] = ""
    h.pids.add(10)
    return h


def test_find_in_a_project_folder():
    found = chatlink.find_in(FOLDER, HOME, registry_host())
    assert found["pid"] == 10 and found["session_id"] == SID and found["bridge_session_id"] == "session_B_1"
    assert chatlink.find_in("/srv/projects/beta", HOME, registry_host()) is None


def test_find_ignores_a_socket_outside_the_socket_folder():
    h = registry_host()
    h.files["%s/sessions/10.json" % HOME] = h.files["%s/sessions/10.json" % HOME].replace(SOCK, "/tmp/other/a.sock")
    assert chatlink.find_in(FOLDER, HOME, h) is None


def test_send_to_writes_one_wire_line(monkeypatch, tmp_path):
    monkeypatch.setenv("PHOENIX9_HOME", str(tmp_path))
    wrote = []
    monkeypatch.setattr(chatlink, "connect_and_write", lambda path, data, timeout=0: wrote.append((path, data)))
    found = chatlink.find_in(FOLDER, HOME, registry_host())
    out = chatlink.send_to(found, "hello", {"page": "home"}, "chat:alpha", host=registry_host())
    assert out["sent"] is True and wrote[0][0] == SOCK
    msg = json.loads(wrote[0][1].decode())
    assert msg["type"] == "user" and "hello" in msg["message"]["content"] and "Phoenix (chat:alpha)" in msg["message"]["content"]


def test_send_to_refuses_a_message_that_is_too_long():
    with pytest.raises(chatlink.TooLong):
        chatlink.send_to({"socket": SOCK}, "x" * (chatlink.MAX_CHARS + 1))


def test_sleep_check_stops_only_a_conversation_of_the_project(tmp_path):
    (paths.projects() / "alpha").mkdir()
    (paths.projects() / "alpha" / "CLAUDE.md").write_text("x")
    a = chat_adapters(tmp_path, "ok", paths.projects() / "alpha", tmp_path / "claude.json")
    a.host.add_session()
    chat.stop_conversation(a.host, "alpha", 10)
    with pytest.raises(ValueError):
        chat.stop_conversation(a.host, "alpha", 999)


def test_projectchat_uses_chatlink_not_agentlink():
    src = open(pc.__file__).read() + open(chat.__file__).read()
    assert "agentlink" not in src.replace("`failmodes.escalate`", "")
