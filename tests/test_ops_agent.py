"""Tests for the agent ops: status, messages, send and sessions."""
import json
import types

import pytest

from phoenix9 import agentlink, events, paths
from phoenix9.ops import agent, common
from tests.fakes import FakeHost

CH = "/root/.claude"
TDIR = CH + "/projects/-srv-projects-home"


def line(o):
    """One transcript line."""
    return json.dumps(o)


def say(role, text, n, sid="s1"):
    """A simple transcript line."""
    if role == "user":
        msg = {"role": "user", "content": text}
    else:
        msg = {"content": [{"type": "text", "text": text}]}
    return line({"type": role, "message": msg, "timestamp": "2026-11-06T10:00:0%dZ" % n, "sessionId": sid})


@pytest.fixture
def host(monkeypatch, tmp_path):
    """A fake host with a live agent session and two transcripts."""
    monkeypatch.setenv("PHOENIX_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    h = FakeHost()
    monkeypatch.setattr(common, "make_adapters", lambda: types.SimpleNamespace(host=h))
    h.files[CH + "/sessions/100.json"] = json.dumps({
        "pid": 100, "cwd": "/srv/projects/home", "name": "Phoenix agent", "status": "idle",
        "messagingSocketPath": "/tmp/cc-socks-0/x.sock", "kind": "interactive", "sessionId": "s1"})
    h.files["/tmp/cc-socks-0/x.sock"] = ""
    h.pids.add(100)
    h.files[TDIR + "/s1.jsonl"] = "\n".join([say("user", "hi", 0), say("assistant", "yo", 1), "{bad",
                                             say("user", "q", 2), say("assistant", "a", 3)]) + "\n"
    h.files[TDIR + "/s0.jsonl"] = say("user", "old", 0, "s0") + "\n"
    h.stats[TDIR + "/s1.jsonl"] = {"mode": 0o600, "uid": 0, "mtime": 2000}
    h.stats[TDIR + "/s0.jsonl"] = {"mode": 0o600, "uid": 0, "mtime": 1000}
    return h


def test_status_awake_and_asleep(host):
    """Status shows the session, and asleep once it is gone."""
    assert agent.status()["state"] == "idle"
    host.pids.clear()
    assert agent.status()["state"] == "asleep"


def test_messages_after_and_limit(host):
    """Messages honour after and limit and report unknown and last_line."""
    r = agent.messages(0, 100)
    assert r["last_line"] == 5 and r["unknown"] == 1 and r["session_id"] == "s1"
    nums = [i["line"] for i in r["items"]]
    assert nums == sorted(nums) and len(nums) == 4
    assert [i["line"] for i in agent.messages(2, 100)["items"]] == [l for l in nums if l > 2]
    assert [i["line"] for i in agent.messages(0, 1)["items"]] == nums[:1]


def test_messages_asleep(host):
    """Asleep gives no items."""
    host.pids.clear()
    assert agent.messages(0, 10)["items"] == []


def test_sessions_newest_first(host):
    """Earlier conversations list newest first with line counts."""
    got = agent.sessions()
    assert [s["session_id"] for s in got] == ["s1", "s0"]
    assert [s["lines"] for s in got] == [5, 1]
    assert all(s["started"] for s in got)


def test_send_records_and_wraps_errors(host, monkeypatch):
    """Send records a command event and turns SendError into OpsError."""
    monkeypatch.setattr(agentlink, "send", lambda t, c=None, w="cli": {"sent": True})
    assert agent.send("go", None, "alex") == {"sent": True}
    assert "alex" in json.dumps([e for e in events.read(paths.events()) if e["type"] == "command"])

    def bad(*a, **k):
        raise agentlink.SendError("The agent is asleep.")
    monkeypatch.setattr(agentlink, "send", bad)
    with pytest.raises(common.OpsError, match="asleep"):
        agent.send("x")
