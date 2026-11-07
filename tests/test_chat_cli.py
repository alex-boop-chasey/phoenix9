"""Tests for `phoenix chat open` (fakes only): each starting state, timeout, --json shape, priming, command event."""
import contextlib
import io
import json

import pytest

from phoenix9 import adapters as adapters_mod, agentlink, paths, projectchat as pc
from phoenix9.__main__ import main
from phoenix9.ops import common
from tests.fakes import FakeClock, FakeHost, fake_adapters

HOME = "/root/.claude"
SOCK = "/tmp/cc-socks-0/a.sock"
SID = "0feb0729-478d-4dc7-879a-b3fe804f3466"
B1, B2 = "session_AAA-1_x", "session_BBB_2"
WEB = "https://claude.ai/code/"


class Host(FakeHost):
    """A host whose unit state and registry change as scripted."""

    def __init__(self, unit, status="idle"):
        super().__init__()
        self.unit, self.status = unit, status

    def systemctl(self, *args):
        self.calls.append(["systemctl", *args])
        if args[0] == "is-active":
            return (0 if self.unit == "active" else 3), self.unit + "\n", ""
        if args[0] == "show":
            return 0, ("100\n" if self.unit in ("active", "activating") else "0\n"), ""
        if args[0] == "enable" and self.unit in ("inactive", "failed"):
            self.unit = "active"
        return 0, "", ""

    def add_session(self):
        data = {"pid": 10, "cwd": str(paths.projects() / "alpha"), "name": "alpha", "status": self.status,
                "messagingSocketPath": SOCK, "kind": "interactive", "sessionId": SID, "startedAt": 1,
                "bridgeSessionId": B2}
        self.files["%s/sessions/10.json" % HOME] = json.dumps(data)
        self.files[SOCK] = ""
        self.pids.update({100, 10})
        self.parents[10] = 100
        self.unit = "active"


class Clock(FakeClock):
    """A clock whose sleeps make the registry entry appear after n of them."""

    def __init__(self, host, appear_after):
        super().__init__()
        self.host, self.appear_after, self.n = host, appear_after, 0

    def sleep(self, s):
        super().sleep(s)
        self.n += 1
        if self.appear_after is not None and self.n >= self.appear_after:
            self.host.add_session()


@pytest.fixture
def sent(monkeypatch):
    """Replace agentlink.send_to with a recorder."""
    box = []

    def fake(found, text, context=None, who="cli", timeout=5.0, host=None):
        box.append({"found": found, "text": text})
        return {"sent": True, "at": "x", "after_line": 0}
    monkeypatch.setattr(agentlink, "send_to", fake)
    return box


@pytest.fixture
def setup(monkeypatch, tmp_path):
    """Build a world: setup(unit, appear_after, ...) returns the adapters."""
    folder = paths.projects() / "alpha"
    folder.mkdir()
    (folder / "CLAUDE.md").write_text("x")

    def make(unit, appear_after=None, status="idle", session_now=False, doc=None, notes=False, wait=None):
        h = Host(unit, status)
        if session_now:
            h.add_session()
            h.unit = unit
        a = fake_adapters(tmp_path)
        a.host, a.clock = h, Clock(h, appear_after)
        monkeypatch.setattr(adapters_mod, "real", lambda: a)
        monkeypatch.setattr(common, "make_adapters", lambda: a)
        if doc:
            pc.write_chat_doc("alpha", pc.build_fields("alpha", doc, SID, 1_800_000_000.0, 1_800_000_000.0))
        if notes:
            (folder / "notes").mkdir(exist_ok=True)
        cfg = paths.home() / "config"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "global.toml").write_text("" if wait is None else "[chat]\nstart_wait_seconds = %d\n" % wait)
        return a
    return make


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def enabled(a):
    return [c for c in a.host.calls if c[:2] == ["systemctl", "enable"]]


def test_off_starts_waits_and_primes(setup, sent):
    a = setup("inactive", appear_after=3, doc=B1, notes=True)
    code, out, _ = run("chat", "open", "alpha", "--json")
    data = json.loads(out)
    assert code == 0 and set(data) == {"state", "web_url", "app_url", "bridge_session_id", "message"}
    assert data["bridge_session_id"] == B2 and data["web_url"] == WEB + B2
    assert len(enabled(a)) == 1 and len(sent) == 1
    assert "notes/NOW.md" in sent[0]["text"] and "notes/sessions" in sent[0]["text"]
    assert pc.read_chat_doc("alpha")[0]["Conversation id"] == B2


def test_off_without_notes_is_not_primed(setup, sent):
    setup("inactive", appear_after=1)
    assert run("chat", "open", "alpha")[0] == 0
    assert sent == []


def test_starting_waits_without_second_start(setup, sent):
    a = setup("activating", appear_after=2, notes=True)
    code, out, _ = run("chat", "open", "alpha", "--json")
    assert code == 0 and json.loads(out)["bridge_session_id"] == B2
    assert enabled(a) == [] and sent == []


def test_sleeping_returns_stored_links(setup, sent):
    a = setup("active", doc=B1, notes=True)
    code, out, _ = run("chat", "open", "alpha")
    assert code == 0 and "sleeping: it wakes when you write to it" in out
    assert WEB + B1 in out and "claude://claude.ai/code/" + B1 in out
    assert sent == [] and enabled(a) == []


@pytest.mark.parametrize("status,word", [("idle", "live"), ("busy", "working")])
def test_live_and_working(setup, sent, status, word):
    a = setup("active", session_now=True, status=status, notes=True)
    code, out, _ = run("chat", "open", "alpha", "--json")
    assert code == 0 and json.loads(out)["state"] == word
    assert sent == [] and enabled(a) == []


def test_timeout_and_other_wait(setup, sent):
    a = setup("inactive", notes=True)
    code, out, err = run("chat", "open", "alpha")
    assert code == 1 and "not ready after 60 s: press Chat again in a minute" in out + err
    assert 60 <= a.clock.t - 1000.0 <= 80 and sent == []
    a = setup("inactive", wait=5)
    code, out, err = run("chat", "open", "alpha")
    assert code == 1 and "not ready after 5 s" in out + err


def test_send_failure_still_returns_links(setup, monkeypatch):
    def refuse(*a, **k):
        raise agentlink.SendError("refused")
    monkeypatch.setattr(agentlink, "send_to", refuse)
    setup("inactive", appear_after=1, notes=True)
    code, out, _ = run("chat", "open", "alpha", "--json")
    data = json.loads(out)
    assert code == 0 and data["web_url"] == WEB + B2
    assert "could not be sent" in data["message"]


def test_unknown_project_refused(setup):
    setup("active", session_now=True)
    code, out, err = run("chat", "open", "ghost")
    assert code != 0 and "ghost" in out + err


def test_command_event(setup, sent):
    setup("active", session_now=True)
    code, _, _ = run("chat", "open", "alpha", "--who", "tester")
    lines = [json.loads(x) for x in (paths.logs() / "commands.jsonl").read_text().splitlines()]
    assert code == 0 and any(l["who"] == "tester" and l["command"] == "chat open alpha" for l in lines)
