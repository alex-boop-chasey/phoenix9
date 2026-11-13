"""Tests for `phoenix chat` status/open/sleep/forget (fakes only): each state, timeout, --json shape, priming, events."""
import contextlib
import io
import json

import pytest

from phoenix9 import adapters as adapters_mod, chatlink, paths, projectchat as pc
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

    def __init__(self, unit, status="idle", running=""):
        super().__init__()
        self.unit, self.status, self.running = unit, status, running

    def systemctl(self, *args):
        self.calls.append(["systemctl", *args])
        if args[0] == "is-active":
            return (0 if self.unit == "active" else 3), self.unit + "\n", ""
        if args[0] == "show":
            return 0, ("100\n" if self.unit in ("active", "activating") else "0\n"), ""
        if args[0] == "start" and self.unit in ("inactive", "failed"):
            self.unit = "active"
        if args[0] == "stop" or args[:2] == ("disable", "--now"):
            self.unit = "inactive"
            self.files.pop("%s/sessions/10.json" % HOME, None)
            self.pids.difference_update({100, 10})
        if args[0] == "list-units":
            return 0, self.running, ""
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
    """Replace chatlink.send_to with a recorder."""
    box = []

    def fake(found, text, context=None, who="cli", timeout=5.0, host=None):
        box.append({"found": found, "text": text})
        return {"sent": True, "at": "x", "after_line": 0}
    monkeypatch.setattr(chatlink, "send_to", fake)
    return box


@pytest.fixture
def setup(monkeypatch, tmp_path):
    """Build a world: setup(unit, appear_after, ...) returns the adapters."""
    folder = paths.projects() / "alpha"
    folder.mkdir()
    (folder / "CLAUDE.md").write_text("x")

    def make(unit, appear_after=None, status="idle", session_now=False, doc=None, notes=False, wait=None,
             running=""):
        h = Host(unit, status, running)
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


def started(a):
    return [c for c in a.host.calls if c[:2] == ["systemctl", "start"]]


def test_none_starts_waits_and_primes(setup, sent):
    """No chat yet: the unit is started (never enabled), Phoenix waits, and the new conversation is primed."""
    a = setup("inactive", appear_after=3, notes=True)
    code, out, _ = run("chat", "open", "alpha", "--json")
    data = json.loads(out)
    assert code == 0 and set(data) == {"state", "web_url", "app_url", "bridge_session_id", "message", "woke", "fresh"}
    assert data["bridge_session_id"] == B2 and data["web_url"] == WEB + B2 and data["fresh"] and data["woke"]
    assert len(started(a)) == 1 and len(sent) == 1
    assert not [c for c in a.host.calls if c[:2] == ["systemctl", "enable"]]
    assert "notes/NOW.md" in sent[0]["text"] and "notes/sessions" in sent[0]["text"]
    assert pc.read_chat_doc("alpha")[0]["Conversation id"] == B2


def test_none_without_notes_is_not_primed(setup, sent):
    setup("inactive", appear_after=1)
    assert run("chat", "open", "alpha")[0] == 0
    assert sent == []


def test_asleep_wakes_the_same_conversation_without_priming(setup, sent):
    """Asleep: the unit is started and the SAME saved conversation comes back; it is not primed."""
    a = setup("inactive", appear_after=1, doc=B2, notes=True)
    code, out, _ = run("chat", "open", "alpha", "--json")
    data = json.loads(out)
    assert code == 0 and data["state"] == "awake" and data["bridge_session_id"] == B2
    assert data["woke"] and not data["fresh"] and len(started(a)) == 1 and sent == []


def test_asleep_woken_as_a_different_conversation_is_primed(setup, sent):
    """The saved conversation could not be re-attached (the launcher made a new one): prime it, save its id."""
    a = setup("inactive", appear_after=1, doc=B1, notes=True)
    data = json.loads(run("chat", "open", "alpha", "--json")[1])
    assert data["bridge_session_id"] == B2 and data["fresh"] and len(sent) == 1 and len(started(a)) == 1
    assert pc.read_chat_doc("alpha")[0]["Conversation id"] == B2


def test_waking_waits_without_second_start(setup, sent):
    a = setup("activating", appear_after=2, doc=B2, notes=True)
    code, out, _ = run("chat", "open", "alpha", "--json")
    assert code == 0 and json.loads(out)["bridge_session_id"] == B2
    assert started(a) == [] and sent == []


@pytest.mark.parametrize("status,word", [("idle", "awake"), ("busy", "working")])
def test_awake_and_working(setup, sent, status, word):
    a = setup("active", session_now=True, status=status, notes=True)
    code, out, _ = run("chat", "open", "alpha", "--json")
    data = json.loads(out)
    assert code == 0 and data["state"] == word and data["message"] == "The chat is awake." and not data["woke"]
    assert sent == [] and started(a) == []


def test_timeout_and_other_wait(setup, sent):
    a = setup("inactive", notes=True)
    code, out, err = run("chat", "open", "alpha")
    assert code == 1 and "The chat didn't wake in 60 seconds. Press Chat again." in out + err
    assert 60 <= a.clock.t - 1000.0 <= 80 and sent == []
    a = setup("inactive", wait=5)
    code, out, err = run("chat", "open", "alpha")
    assert code == 1 and "didn't wake in 5 seconds" in out + err


def test_send_failure_still_returns_links(setup, monkeypatch):
    def refuse(*a, **k):
        raise chatlink.SendError("refused")
    monkeypatch.setattr(chatlink, "send_to", refuse)
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


class SleepClock(Clock):
    """A clock whose sleeps turn a busy conversation idle after n of them."""

    def __init__(self, host, idle_after):
        super().__init__(host, None)
        self.idle_after = idle_after

    def sleep(self, s):
        super().sleep(s)
        if self.idle_after is not None and self.n >= self.idle_after and self.host.status == "busy":
            self.host.status = "idle"
            self.host.add_session()


def live(setup, status="idle", idle_after=None, **kw):
    a = setup("active", session_now=True, status=status, doc=B2, **kw)
    a.clock = SleepClock(a.host, idle_after)
    return a


STOP = ["systemctl", "disable", "--now", "claude-rc-chat@alpha"]


def changes(a):
    return [c for c in a.host.calls if c[:2] in (["systemctl", "disable"], ["systemctl", "stop"])]


def test_sleep_sends_wrap_up_then_stops_the_unit(setup, sent):
    a = live(setup)
    code, out, _ = run("chat", "sleep", "alpha", "--json")
    data = json.loads(out)
    assert code == 0 and len(sent) == 1 and "notes/sessions/" in sent[0]["text"]
    assert data["state"] == "asleep" and data["message"] == "The chat is asleep. Press Chat to wake it."
    assert a.host.stopped == [] and changes(a) == [STOP]
    assert pc.read_chat_doc("alpha")[0]["Conversation id"] == B2
    assert pc.state("alpha", a)["state"] == "asleep"


def test_sleep_waits_for_busy_to_end(setup, sent):
    a = live(setup, status="busy", idle_after=3)
    assert run("chat", "sleep", "alpha")[0] == 0
    assert changes(a) == [STOP] and a.clock.n >= 3


def test_sleep_timeout_still_stops(setup, sent):
    a = live(setup, status="busy")
    assert run("chat", "sleep", "alpha")[0] == 0
    assert 180 <= a.clock.t - 1000.0 <= 200 and changes(a) == [STOP]


def test_sleep_without_wrap_up(setup, sent):
    a = live(setup)
    pc.sleep("alpha", a, "t", wrap_up=False)
    assert sent == [] and changes(a) == [STOP]


@pytest.mark.parametrize("unit,doc,word,words", [("inactive", B1, "asleep", "The chat is already asleep."),
                                                 ("inactive", None, "none", "There is no chat yet.")])
def test_sleep_when_not_awake_says_so(setup, sent, unit, doc, word, words):
    a = setup(unit, doc=doc)
    code, out, _ = run("chat", "sleep", "alpha", "--json")
    data = json.loads(out)
    assert code == 0 and data["state"] == word and data["message"] == words and not data["changed"]
    assert sent == [] and changes(a) == []


def test_forget_needs_yes(setup):
    a = setup("active", session_now=True, doc=B2)
    code, out, err = run("chat", "forget", "alpha")
    assert code != 0 and "--yes" in out + err
    assert changes(a) == [] and pc.doc_path("alpha").exists()


def test_forget_stops_and_sets_the_document_aside(setup):
    a = setup("active", session_now=True, doc=B2)
    code, out, _ = run("chat", "forget", "alpha", "--yes", "--json")
    data = json.loads(out)
    assert code == 0 and data["state"] == "none" and "forgotten" in data["message"]
    assert STOP in a.host.calls and not pc.doc_path("alpha").exists()
    assert pc.doc_path("alpha").with_name("chat.old.md").exists()


def test_off_is_a_hidden_alias_for_sleep(setup, sent):
    a = live(setup)
    code, out, err = run("chat", "off", "alpha", "--yes")
    assert code == 0 and "off is now: phoenix chat sleep" in err and "asleep" in out
    assert changes(a) == [STOP] and pc.doc_path("alpha").exists()
    code, out, _ = run("chat", "--help")
    assert code == 0 and " off " not in out


def test_help_lists_the_new_commands():
    code, out, _ = run("chat", "--help")
    for word in ("status", "open", "sleep", "forget"):
        assert word in out
    assert "catch-up" not in out


def test_sleep_forget_and_off_events(setup, sent):
    live(setup)
    run("chat", "sleep", "alpha", "--who", "t1")
    run("chat", "forget", "alpha", "--yes", "--who", "t2")
    run("chat", "off", "alpha", "--who", "t3")
    cmds = [json.loads(x) for x in (paths.logs() / "commands.jsonl").read_text().splitlines()]
    assert any(c["who"] == "t1" and c["command"] == "chat sleep alpha" for c in cmds)
    assert any(c["who"] == "t2" and c["command"] == "chat forget alpha" for c in cmds)
    assert any(c["who"] == "t3" and c["command"] == "chat sleep alpha" for c in cmds)


def test_status_of_one_project(setup, sent):
    setup("active", session_now=True)
    code, out, _ = run("chat", "status", "alpha")
    assert code == 0 and out.startswith("alpha: Awake") and "last active" in out
    assert WEB + B2 in out and "claude://claude.ai/code/" + B2 in out
    data = json.loads(run("chat", "status", "alpha", "--json")[1])
    assert data["state"] == "awake" and data["bridge_session_id"] == B2


def test_status_of_one_project_without_a_chat_has_no_links(setup):
    setup("inactive")
    code, out, _ = run("chat", "status", "alpha")
    assert code == 0 and out.strip() == "alpha: No chat yet · last active never"


def test_status_of_all_lists_unlisted_running_chats(setup):
    a = setup("inactive", doc=B1, running="claude-rc-chat@alpha.service loaded active running Chat alpha\n"
                                        "claude-rc-chat@gone.service loaded active running Chat gone\n")
    code, out, _ = run("chat", "status")
    assert code == 0 and "alpha" in out and "Asleep" in out
    assert "Chats running for projects that are not listed:" in out and "claude-rc-chat@gone" in out
    assert ["systemctl", "list-units", "claude-rc-chat@*", "--state=active", "--plain", "--no-legend"] in a.host.calls
    data = json.loads(run("chat", "status", "--json")[1])
    assert data["unlisted"] == ["gone"] and data["projects"][0]["name"] == "alpha"
    assert data["projects"][0]["state"] == "asleep"


def test_status_of_all_without_strays_has_no_section(setup):
    setup("inactive")
    code, out, _ = run("chat", "status")
    assert code == 0 and "not listed" not in out and "No chat yet" in out


def test_ago_words():
    from phoenix9.cli.chatcmd import ago
    assert ago(None) == "never" and ago(1000, 1030) == "just now"
    assert ago(0.5, 0.5 + 300) == "5 min ago" and ago(1, 1 + 7300) == "2 h ago"
    assert ago(1, 1 + 86400) == "1 day ago" and ago(1, 1 + 3 * 86400) == "3 days ago"


NAMES = ["alpha", "beta", "bad", "done", "phoenix9", "home"]


def test_catch_up_is_gone():
    """Creation no longer sets up a chat, so there is nothing to catch up."""
    from phoenix9.ops import chat as chat_ops
    code, _out, err = run("chat", "catch-up")
    assert code == 2 and "invalid choice" in err
    assert not hasattr(chat_ops, "catch_up") and not hasattr(pc, "set_up")


def test_open_waits_for_the_conversation_id_not_just_the_session(setup, sent):
    """Found live: the session appeared before Claude Code wrote its claude.ai id, and the first press
    returned "live" with no links (or the old document's link). Wait until the live id is there."""
    a = setup("inactive", appear_after=1, doc=B1, notes=False)
    real_add = a.host.add_session
    tries = {"n": 0}

    def add_without_id_first():
        real_add()
        tries["n"] += 1
        if tries["n"] < 4:                        # the first few looks: no bridgeSessionId yet
            key = "%s/sessions/10.json" % HOME
            data = json.loads(a.host.files[key])
            data.pop("bridgeSessionId", None)
            a.host.files[key] = json.dumps(data)
    a.host.add_session = add_without_id_first
    a.clock.host = a.host
    code, out, _ = run("chat", "open", "alpha", "--json")
    data = json.loads(out)
    assert code == 0 and data["bridge_session_id"] == B2, data      # the new id, never the stale B1
    assert pc.read_chat_doc("alpha")[0]["Conversation id"] == B2
