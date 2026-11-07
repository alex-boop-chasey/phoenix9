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

from phoenix9 import agentlink  # noqa: E402
from tests.fakes import FakeHost, fake_adapters  # noqa: E402

HOME = "/root/.claude"


def make_adapters(tmp_path, unit, status=None, bridge=None, sid=SID, parent=100):
    agentlink.forget()
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
def test_state_off(listed, tmp_path, unit):
    assert pc.state("alpha", make_adapters(tmp_path, unit))["state"] == "off"


def test_state_starting(listed, tmp_path):
    assert pc.state("alpha", make_adapters(tmp_path, "activating"))["state"] == "starting"
    s = pc.state("alpha", make_adapters(tmp_path, "active"))
    assert s["state"] == "starting" and s["web_url"] is None and s["app_url"] is None


def test_state_sleeping(listed, tmp_path):
    put_doc()
    s = pc.state("alpha", make_adapters(tmp_path, "active"))
    assert s["state"] == "sleeping" and s["bridge_session_id"] == B2
    assert s["web_url"] == "https://claude.ai/code/" + B2
    assert s["app_url"] == "claude://claude.ai/code/" + B2
    assert s["last_active"] == T0


def test_state_live_and_working(listed, tmp_path):
    s = pc.state("alpha", make_adapters(tmp_path, "active", "idle", B1))
    assert s["state"] == "live" and s["bridge_session_id"] == B1
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
    s = pc.state("alpha", make_adapters(tmp_path, "active"))
    assert s["state"] == "starting" and s["bridge_session_id"] is None
    s = pc.state("alpha", make_adapters(tmp_path, "active", "idle", B1))
    assert s["state"] == "live" and pc.read_chat_doc("alpha")[0] is not None


def test_state_foreign_process_is_not_live(listed, tmp_path):
    s = pc.state("alpha", make_adapters(tmp_path, "active", "idle", B1, parent=999))
    assert s["state"] == "starting"


def test_state_unknown_project(listed, tmp_path):
    with pytest.raises(ValueError):
        pc.state("ghost", make_adapters(tmp_path, "active", "idle", B1))
