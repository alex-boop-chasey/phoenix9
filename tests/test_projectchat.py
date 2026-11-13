"""Tests for the chat document: round trip, strict parsing, rewrite on a new id, throttle, atomic write."""
import os

import pytest

from phoenix9 import paths, projectchat as pc

SID = "0feb0729-478d-4dc7-879a-b3fe804f3466"
SID2 = "11111111-2222-4333-8444-555555555555"
B1, B2 = "session_AAA-1_x", "session_BBB_2"
T0 = 1_800_000_000.0


def found(bridge=B1, sid=SID):
    return {"pid": 10, "session_id": sid, "name": "alpha", "bridge_session_id": bridge}


def doc():
    return paths.projects() / "alpha" / ".phoenix" / "chat.md"


@pytest.fixture
def project():
    (paths.projects() / "alpha").mkdir()


def test_round_trip(project):
    assert pc.read_chat_doc("alpha")[0] is None
    assert pc.sync_chat_doc("alpha", found(), T0)
    fields, why = pc.read_chat_doc("alpha")
    assert why is None and fields["Web link"] == "https://claude.ai/code/" + B1
    text = doc().read_text()
    assert text.startswith("# Chat: alpha\n")
    pc.write_chat_doc("alpha", fields)
    assert doc().read_text() == text


def mutate(project, old, new):
    pc.sync_chat_doc("alpha", found(), T0)
    doc().write_text(doc().read_text().replace(old, new))
    return pc.read_chat_doc("alpha")


@pytest.mark.parametrize("old,new", [
    ("Conversation id: " + B1, "Conversation id: a b"),
    ("Local session id: " + SID, "Local session id: nope"),
    ("https://claude.ai/code/" + B1, "https://claude.ai/code/other"),
    ("claude://claude.ai/code/" + B1, "https://claude.ai/code/" + B1),
    ("Project: alpha", "Project: beta"),
    ("Created: ", "Created: x"),
])
def test_bad_values_unreadable(project, old, new):
    fields, why = mutate(project, old, new)
    assert fields is None and why


def test_unknown_missing_duplicate_keys(project):
    pc.sync_chat_doc("alpha", found(), T0)
    text = doc().read_text()
    for bad in (text + "Extra: 1\n", text + "Created: " + pc.format_time(T0) + "\n", "", "\x00",
                "\n".join(x for x in text.splitlines() if not x.startswith("Web link")) + "\n"):
        doc().write_text(bad)
        fields, why = pc.read_chat_doc("alpha")
        assert fields is None and why
    doc().write_bytes(b"\xff\xfe")
    assert pc.read_chat_doc("alpha")[0] is None


def test_throttle_and_new_id(project):
    pc.sync_chat_doc("alpha", found(), T0)
    before = doc().read_text()
    assert not pc.sync_chat_doc("alpha", found(), T0 + 300)
    assert doc().read_text() == before
    assert pc.sync_chat_doc("alpha", found(), T0 + 601)
    fields = pc.read_chat_doc("alpha")[0]
    assert fields["Created"] == pc.format_time(T0)
    assert fields["Last active"] == pc.format_time(T0 + 601)
    assert pc.sync_chat_doc("alpha", found(B2, SID2), T0 + 700)
    fields = pc.read_chat_doc("alpha")[0]
    assert fields["Conversation id"] == B2 and fields["Created"] == pc.format_time(T0 + 700)


@pytest.mark.parametrize("bridge,sid", [(None, SID), ("a b", SID), (B1, "nope"), (B1, None)])
def test_bad_found_writes_nothing(project, bridge, sid):
    assert pc.sync_chat_doc("alpha", found(bridge, sid), T0) is False
    assert not doc().exists()
    pc.sync_chat_doc("alpha", found(), T0)
    before = doc().read_text()
    assert pc.sync_chat_doc("alpha", found(bridge, sid), T0 + 5000) is False
    assert doc().read_text() == before


def test_atomic_write(project, monkeypatch):
    pc.sync_chat_doc("alpha", found(), T0)
    keep = doc().read_text()

    def boom(*a, **k):
        raise OSError("boom")
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        pc.sync_chat_doc("alpha", found(B2, SID2), T0 + 5000)
    assert doc().read_text() == keep
    assert [p.name for p in doc().parent.iterdir()] == ["chat.md"]


# ---- state ----
import json  # noqa: E402

from phoenix9 import chatlink  # noqa: E402
from tests.fakes import FakeHost, fake_adapters  # noqa: E402

HOME = "/root/.claude"


def make_adapters(tmp_path, unit, status=None, bridge=None, sid=SID, parent=100):
    chatlink.forget()
    host = FakeHost()
    host.script(["systemctl", "is-active"], rc=0 if unit == "active" else 3, out=unit + "\n")
    host.script(["systemctl", "show"], out="100\n")
    if status is not None:
        sock = "/tmp/cc-socks-0/a.sock"
        data = {"pid": 10, "cwd": str(paths.projects() / "alpha"), "name": "alpha", "status": status,
                "messagingSocketPath": sock, "kind": "interactive", "sessionId": sid, "startedAt": 1}
        if bridge:
            data["bridgeSessionId"] = bridge
        host.files["%s/sessions/10.json" % HOME] = json.dumps(data)
        host.files[sock] = ""
        host.pids |= {100, 10}
        host.parents[10] = parent
    adapters = fake_adapters(tmp_path)
    adapters.host = host
    return adapters


def put_doc():
    pc.write_chat_doc("alpha", pc.build_fields("alpha", B2, SID2, T0, T0))


@pytest.fixture
def listed(project):
    (paths.projects() / "alpha" / "CLAUDE.md").write_text("x")


@pytest.mark.parametrize("unit", ["inactive", "failed"])
def test_state_none_and_asleep(listed, tmp_path, unit):
    assert pc.state("alpha", make_adapters(tmp_path, unit))["state"] == "none"
    put_doc()
    s = pc.state("alpha", make_adapters(tmp_path, unit))
    assert s["state"] == "asleep" and s["bridge_session_id"] == B2
    assert s["web_url"] == "https://claude.ai/code/" + B2
    assert s["app_url"] == "claude://claude.ai/code/" + B2
    assert s["last_active"] == T0


def test_state_waking(listed, tmp_path):
    assert pc.state("alpha", make_adapters(tmp_path, "activating"))["state"] == "waking"
    s = pc.state("alpha", make_adapters(tmp_path, "active"))
    assert s["state"] == "waking" and s["web_url"] is None and s["app_url"] is None
    # The conversation is up but Claude Code has not written its claude.ai id yet.
    assert pc.state("alpha", make_adapters(tmp_path, "active", "idle"))["state"] == "waking"


def test_state_awake_and_working(listed, tmp_path):
    s = pc.state("alpha", make_adapters(tmp_path, "active", "idle", B1))
    assert s["state"] == "awake" and s["bridge_session_id"] == B1
    assert pc.read_chat_doc("alpha")[0]["Conversation id"] == B1
    assert pc.state("alpha", make_adapters(tmp_path, "active", "busy", B1))["state"] == "working"


def test_state_registry_beats_document(listed, tmp_path):
    put_doc()
    s = pc.state("alpha", make_adapters(tmp_path, "active", "idle", B1))
    assert s["bridge_session_id"] == B1
    fields, _ = pc.read_chat_doc("alpha")
    assert fields["Conversation id"] == B1 and fields["Local session id"] == SID


def test_state_unreadable_document(listed, tmp_path):
    doc().parent.mkdir(exist_ok=True)
    doc().write_text("garbage\x00")
    assert pc.state("alpha", make_adapters(tmp_path, "inactive"))["state"] == "none"
    s = pc.state("alpha", make_adapters(tmp_path, "active"))
    assert s["state"] == "waking" and s["bridge_session_id"] is None
    s = pc.state("alpha", make_adapters(tmp_path, "active", "idle", B1))
    assert s["state"] == "awake" and pc.read_chat_doc("alpha")[0] is not None


def test_state_foreign_process_is_not_live(listed, tmp_path):
    s = pc.state("alpha", make_adapters(tmp_path, "active", "idle", B1, parent=999))
    assert s["state"] == "waking"


def test_state_unknown_project(listed, tmp_path):
    with pytest.raises(ValueError):
        pc.state("ghost", make_adapters(tmp_path, "active", "idle", B1))


# ---- open, sleep, forget ----
from tests.fakes import FakeClock  # noqa: E402
from tests.fakes.chathost import chat_adapters  # noqa: E402

U = "claude-rc-chat@alpha"


@pytest.fixture
def sent(monkeypatch):
    """Messages sent into the chat, recorded instead of written to a socket."""
    out = []
    monkeypatch.setattr(chatlink, "send_to", lambda found, text, *a, **k: out.append(text) or {"sent": True})
    return out


def woken(tmp_path, bridge=B2):
    """Adapters whose chat unit starts on `systemctl start` and then shows a conversation with this id."""
    chatlink.forget()
    a = chat_adapters(tmp_path, "ok", paths.projects() / "alpha", tmp_path / "claude.json")
    a.host.bridge = bridge
    (paths.projects() / "alpha" / "notes").mkdir(exist_ok=True)
    return a


def saved(bridge=B2):
    pc.write_chat_doc("alpha", pc.build_fields("alpha", bridge, SID, T0, T0))


def test_open_asleep_wakes_the_same_conversation_without_priming(listed, tmp_path, sent):
    saved()
    a = woken(tmp_path)
    assert pc.state("alpha", a)["state"] == "asleep"
    r = pc.open_("alpha", a, "alex")
    assert r["state"] == "awake" and r["bridge_session_id"] == B2 and r["web_url"] == pc.WEB_PREFIX + B2
    assert r["woke"] is True and r["fresh"] is False and r["message"] == "The chat is awake."
    assert ["systemctl", "start", U] in a.host.calls
    assert not [c for c in a.host.calls if c[1] == "enable"]
    assert sent == []
    assert pc.read_chat_doc("alpha")[0]["Conversation id"] == B2


def test_open_none_starts_a_fresh_primed_conversation(listed, tmp_path, sent):
    a = woken(tmp_path)
    assert pc.state("alpha", a)["state"] == "none"
    r = pc.open_("alpha", a, "alex")
    assert r["state"] == "awake" and r["woke"] is True and r["fresh"] is True
    assert sent == [pc.PRIME_TEXT]
    assert pc.read_chat_doc("alpha")[0]["Conversation id"] == B2


def test_open_primes_when_the_woken_id_differs(listed, tmp_path, sent):
    saved(B1)
    a = woken(tmp_path, B2)
    r = pc.open_("alpha", a, "alex")
    assert r["bridge_session_id"] == B2 and r["fresh"] is True
    assert sent == [pc.PRIME_TEXT]
    assert pc.read_chat_doc("alpha")[0]["Conversation id"] == B2


def test_open_awake_returns_links_at_once(listed, tmp_path, sent):
    saved()
    a = woken(tmp_path)
    a.host.unit = "active"
    a.host.add_session()
    r = pc.open_("alpha", a, "alex")
    assert r == {"state": "awake", "web_url": pc.WEB_PREFIX + B2, "app_url": pc.DESKTOP_PREFIX + B2,
                 "bridge_session_id": B2, "message": "The chat is awake.", "woke": False, "fresh": False}
    assert not [c for c in a.host.calls if c[1] in ("start", "enable")] and sent == []


def test_open_waking_does_not_start_again(listed, tmp_path, sent):
    saved()
    a = woken(tmp_path)
    a.host.unit = "active"
    r = pc.open_("alpha", a, "alex")
    assert r["state"] == "awake" and r["fresh"] is False and sent == []
    assert not [c for c in a.host.calls if c[1] in ("start", "enable")]


def test_open_not_ready_and_refused(listed, tmp_path, sent):
    saved()
    a = woken(tmp_path)
    a.clock = FakeClock()          # the conversation never appears
    with pytest.raises(pc.NotReady) as e:
        pc.open_("alpha", a, "alex")
    assert str(e.value) == "The chat didn't wake in 60 seconds. Press Chat again."
    a = chat_adapters(tmp_path, "fail", paths.projects() / "alpha", tmp_path / "claude.json")
    with pytest.raises(pc.NotReady) as e:
        pc.open_("alpha", a, "alex")
    assert "couldn't start the chat service" in str(e.value)


def test_sleep_stops_the_unit_and_reads_asleep(listed, tmp_path, sent):
    saved()
    a = woken(tmp_path)
    pc.open_("alpha", a, "alex")
    r = pc.sleep("alpha", a, "alex")
    assert r == {"state": "asleep", "changed": True, "message": "The chat is asleep. Press Chat to wake it."}
    assert sent == [pc.WRAP_UP_TEXT]
    assert ["systemctl", "disable", "--now", U] in a.host.calls
    assert a.host.stopped == []    # the whole unit stops, not just the conversation process
    assert pc.state("alpha", a)["state"] == "asleep"
    assert pc.read_chat_doc("alpha")[0]["Conversation id"] == B2
    again = pc.sleep("alpha", a, "alex")
    assert again["changed"] is False and again["state"] == "asleep"


def test_sleep_without_a_chat_changes_nothing(listed, tmp_path, sent):
    a = woken(tmp_path)
    r = pc.sleep("alpha", a, "alex")
    assert r["state"] == "none" and r["changed"] is False
    assert not [c for c in a.host.calls if c[1] in ("stop", "disable")] and sent == []


def test_forget_moves_the_document(listed, tmp_path, sent):
    saved()
    a = woken(tmp_path)
    pc.open_("alpha", a, "alex")
    r = pc.forget("alpha", a, "alex")
    assert r["state"] == "none" and r["message"] == "The saved chat is forgotten. Press Chat to start a fresh one."
    assert not doc().exists() and (doc().parent / "chat.old.md").is_file()
    assert pc.state("alpha", a)["state"] == "none"
    r = pc.open_("alpha", a, "alex")
    assert r["fresh"] is True and sent == [pc.PRIME_TEXT]
