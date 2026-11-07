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


def changes(a):
    return [c for c in a.host.calls if c[:2] in (["systemctl", "disable"], ["systemctl", "stop"])]


def test_sleep_sends_wrap_up_then_stops_conversation(setup, sent):
    a = live(setup)
    code, out, _ = run("chat", "sleep", "alpha")
    assert code == 0 and len(sent) == 1 and "notes/sessions/" in sent[0]["text"]
    assert a.host.stopped == [10] and changes(a) == []
    assert pc.read_chat_doc("alpha")[0]["Conversation id"] == B2


def test_sleep_waits_for_busy_to_end(setup, sent):
    a = live(setup, status="busy", idle_after=3)
    assert run("chat", "sleep", "alpha")[0] == 0
    assert a.host.stopped == [10] and a.clock.n >= 3


def test_sleep_timeout_still_stops(setup, sent):
    a = live(setup, status="busy")
    assert run("chat", "sleep", "alpha")[0] == 0
    assert 180 <= a.clock.t - 1000.0 <= 200 and a.host.stopped == [10]


def test_sleep_without_wrap_up(setup, sent):
    a = live(setup)
    pc.sleep("alpha", a, "t", wrap_up=False)
    assert sent == [] and a.host.stopped == [10]


@pytest.mark.parametrize("unit,doc,word", [("active", B1, "sleeping"), ("inactive", None, "off")])
def test_sleep_when_not_live_says_so(setup, sent, unit, doc, word):
    a = setup(unit, doc=doc)
    code, out, _ = run("chat", "sleep", "alpha", "--json")
    data = json.loads(out)
    assert code == 0 and data["state"] == word and word in data["message"]
    assert sent == [] and a.host.stopped == []


def test_off_needs_yes(setup):
    a = setup("active", session_now=True)
    assert run("chat", "off", "alpha")[0] != 0
    assert changes(a) == []


def test_off_stops_and_disables(setup):
    a = setup("active", session_now=True)
    code, out, _ = run("chat", "off", "alpha", "--yes", "--json")
    assert code == 0 and json.loads(out)["state"] == "off"
    assert ["systemctl", "disable", "--now", "claude-rc-chat@alpha"] in a.host.calls


def test_sleep_and_off_events(setup, sent):
    live(setup)
    run("chat", "sleep", "alpha", "--who", "t1")
    run("chat", "off", "alpha", "--yes", "--who", "t2")
    cmds = [json.loads(x) for x in (paths.logs() / "commands.jsonl").read_text().splitlines()]
    assert any(c["who"] == "t1" and c["command"] == "chat sleep alpha" for c in cmds)
    assert any(c["who"] == "t2" and c["command"] == "chat off alpha" for c in cmds)


NAMES = ["alpha", "beta", "bad", "done", "phoenix9", "home"]


class Many(FakeHost):
    """A host with one chat unit per project; 'failing' projects refuse to start."""

    def __init__(self, failing):
        super().__init__()
        self.failing, self.units, self.added = set(failing), {}, set()

    @staticmethod
    def name(unit):
        return unit.split("@", 1)[1].split(".", 1)[0]

    def systemctl(self, *args):
        self.calls.append(["systemctl", *args])
        i = lambda n: NAMES.index(n)
        if args[0] == "is-active":
            st = self.units.get(self.name(args[-1]), "inactive")
            return (0 if st == "active" else 3), st + "\n", ""
        if args[0] == "show":
            n = self.name(args[-1])
            return 0, ("%d\n" % (100 + 10 * i(n)) if self.units.get(n) == "active" else "0\n"), ""
        if args[0] in ("enable", "start", "restart"):
            n = self.name(args[-1])
            if n in self.failing:
                return 1, "", "boom"
            self.units[n] = "active"
        return 0, "", ""

    def add_session(self, n):
        pid = 101 + 10 * NAMES.index(n)
        sock = "/tmp/cc-socks-0/%s.sock" % n
        data = {"pid": pid, "cwd": str(paths.projects() / n), "name": n, "status": "idle",
                "messagingSocketPath": sock, "kind": "interactive", "sessionId": SID, "startedAt": 1,
                "bridgeSessionId": "session_%s_1" % n.upper()}
        self.files["%s/sessions/%d.json" % (HOME, pid)] = json.dumps(data)
        self.files[sock] = ""
        self.pids.update({pid - 1, pid})
        self.parents[pid] = pid - 1
        self.added.add(n)


class ManyClock(FakeClock):
    """A clock whose sleeps let each started unit's conversation appear once."""

    def __init__(self, host):
        super().__init__()
        self.host = host

    def sleep(self, s):
        super().sleep(s)
        for n, st in list(self.host.units.items()):
            if st == "active" and n not in self.host.added:
                self.host.add_session(n)


@pytest.fixture
def world(monkeypatch, tmp_path, sent):
    """Six projects; 'done' has a chat document already."""
    for n in NAMES:
        (paths.projects() / n).mkdir()
        (paths.projects() / n / "CLAUDE.md").write_text("x")
    pc.write_chat_doc("done", pc.build_fields("done", "session_DONE_9", SID, 1_800_000_000.0, 1_800_000_000.0))

    def make(failing=()):
        h = Many(failing)
        a = fake_adapters(tmp_path)
        a.host, a.clock = h, ManyClock(h)
        monkeypatch.setattr(adapters_mod, "real", lambda: a)
        monkeypatch.setattr(common, "make_adapters", lambda: a)
        return a
    return make


def started(a):
    return sorted({Many.name(c[-1]) for c in a.host.calls if c[:2] == ["systemctl", "enable"]})


def test_catch_up_lists_without_all(world):
    a = world()
    code, out, err = run("chat", "catch-up")
    assert code == 0 and "--all" in out + err
    assert all(n in out + err for n in ("alpha", "beta", "bad"))
    assert started(a) == [] and pc.read_chat_doc("alpha")[0] is None


def test_catch_up_all_sets_up_each_and_skips_others(world):
    a = world()
    code, out, err = run("chat", "catch-up", "--all")
    assert code == 0, (out, err)
    assert started(a) == ["alpha", "bad", "beta"]
    for n in ("alpha", "beta", "bad"):
        assert pc.state(n, a)["state"] == "sleeping"
    for n in ("phoenix9", "home"):
        assert pc.read_chat_doc(n)[0] is None
    assert pc.read_chat_doc("done")[0]["Conversation id"] == "session_DONE_9"


def test_catch_up_failure_continues_and_exits_1(world):
    a = world(failing=["bad"])
    code, out, err = run("chat", "catch-up", "--all")
    assert code == 1 and "bad" in out + err
    for n in ("alpha", "beta"):
        assert pc.state(n, a)["state"] == "sleeping"
    assert pc.read_chat_doc("bad")[0] is None


def test_catch_up_json_shape_and_event(world):
    world(failing=["bad"])
    code, out, _ = run("chat", "catch-up", "--all", "--json", "--who", "t3")
    data = json.loads(out)
    assert code == 1 and data["todo"] == ["alpha", "bad", "beta"] and data["failed"] == 1
    assert {r["project"]: r["ok"] for r in data["results"]} == {"alpha": True, "beta": True, "bad": False}
    cmds = [json.loads(x) for x in (paths.logs() / "commands.jsonl").read_text().splitlines()]
    assert any(c["who"] == "t3" and "chat catch-up" in c["command"] for c in cmds)
