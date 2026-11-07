#!/bin/sh
# python3 -m pytest -q tests/test_projectchat.py tests/test_chat_cli.py
# Behaviour check: `phoenix chat open` for off, starting, sleeping, live and working chats, the timeout, --json shape, and priming only after off.
set -u
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$ROOT" || exit 1
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

[ -f tests/test_chat_cli.py ] || fail "tests/test_chat_cli.py missing"
python3 -m pytest -q tests/test_projectchat.py tests/test_chat_cli.py >"$TMP/pytest.out" 2>&1 \
    || { tail -30 "$TMP/pytest.out"; fail "pytest on projectchat and chat cli tests"; }

cat >"$TMP/check.py" <<'PY'
import contextlib, io, json, os, sys
from pathlib import Path
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "tests"))
from phoenix9 import adapters as adapters_mod, agentlink, projectchat as pc
from phoenix9.__main__ import main
from phoenix9.ops import common
from fakes import FakeHost, FakeClock, fake_adapters

root = Path(os.environ["PHOENIX_PROJECTS"])
phome = Path(os.environ["PHOENIX_HOME"])
folder = root / "alpha"
folder.mkdir()
(folder / "CLAUDE.md").write_text("x")
HOME = "/root/.claude"
SOCK = "/tmp/cc-socks-0/a.sock"
SID = "0feb0729-478d-4dc7-879a-b3fe804f3466"
B1, B2 = "session_AAA-1_x", "session_BBB_2"
T0 = 1_800_000_000.0


class Host(FakeHost):
    """A host whose unit state and registry change as scripted."""
    def __init__(self, unit, status="idle", bridge=B2):
        super().__init__()
        self.unit, self.status, self.bridge = unit, status, bridge

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
        data = {"pid": 10, "cwd": str(folder), "name": "alpha", "status": self.status,
                "messagingSocketPath": SOCK, "kind": "interactive", "sessionId": SID, "startedAt": 1,
                "bridgeSessionId": self.bridge}
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


sent = []
def fake_send_to(found, text, context=None, who="cli", timeout=5.0, host=None):
    sent.append({"found": found, "text": text})
    return {"sent": True, "at": "x", "after_line": 0}
agentlink.send_to = fake_send_to


def setup(unit, appear_after=None, status="idle", session_now=False, doc=None, notes=False, wait=None):
    agentlink.forget()
    sent.clear()
    h = Host(unit, status)
    if session_now:
        h.add_session()
        h.unit = unit
    a = fake_adapters(str(phome))
    a.host, a.clock = h, Clock(h, appear_after)
    adapters_mod.real = lambda: a
    common.make_adapters = lambda: a
    d = folder / ".phoenix" / "chat.md"
    if d.exists():
        d.unlink()
    if doc:
        pc.write_chat_doc("alpha", pc.build_fields("alpha", doc, SID, T0, T0))
    nd = folder / "notes"
    if notes:
        (nd / "sessions").mkdir(parents=True, exist_ok=True)
        (nd / "NOW.md").write_text("now")
    elif nd.exists():
        import shutil; shutil.rmtree(nd)
    cfg = phome / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "global.toml").write_text("" if wait is None else "[chat]\nstart_wait_seconds = %d\n" % wait)
    return a


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def enabled(a):
    return [c for c in a.host.calls if c[:2] == ["systemctl", "enable"]]


def jopen(a_expect_code=0):
    code, out, err = run("chat", "open", "alpha", "--json")
    assert code == a_expect_code, (code, out, err)
    return json.loads(out)


WEB, APP = "https://claude.ai/code/", "claude://claude.ai/code/"
KEYS = {"state", "web_url", "app_url", "bridge_session_id", "message"}

# 1. off, stale document from the old conversation, notes present: starts, waits, new links, primed once
a = setup("inactive", appear_after=3, doc=B1, notes=True)
data = jopen()
assert set(data) == KEYS, data
assert data["state"] in ("live", "working"), data
assert data["bridge_session_id"] == B2 and data["web_url"] == WEB + B2 and data["app_url"] == APP + B2, data
assert isinstance(data["message"], str)
assert len(enabled(a)) == 1 and "claude-rc-chat@alpha" in enabled(a)[0], a.host.calls
assert len(sent) == 1, sent
assert "notes/NOW.md" in sent[0]["text"] and "notes/sessions" in sent[0]["text"], sent[0]["text"]
assert sent[0]["found"]["socket"] == SOCK, sent[0]["found"]
d, why = pc.read_chat_doc("alpha")
assert d and d["Conversation id"] == B2, (d, why)
assert a.clock.n >= 3

# 2. off, no notes folder: started, no priming
a = setup("inactive", appear_after=1, notes=False)
data = jopen()
assert data["bridge_session_id"] == B2 and len(enabled(a)) == 1, data
assert sent == [], sent

# 3. off, registry appears after one wait, notes: still primed
a = setup("inactive", appear_after=1, notes=True)
jopen()
assert len(sent) == 1, sent

# 4. starting (unit activating): keeps waiting, does not start again, no priming
a = setup("activating", appear_after=2, notes=True)
data = jopen()
assert data["state"] in ("live", "working") and data["bridge_session_id"] == B2, data
assert enabled(a) == [], a.host.calls
assert sent == [], sent

# 5. sleeping: stored links, the sleeping words, nothing sent, nothing started
a = setup("active", doc=B1, notes=True)
data = jopen()
assert set(data) == KEYS, data
assert data["state"] == "sleeping", data
assert data["bridge_session_id"] == B1 and data["web_url"] == WEB + B1 and data["app_url"] == APP + B1, data
assert "sleeping: it wakes when you write to it" in data["message"], data
assert sent == [] and enabled(a) == [], (sent, a.host.calls)
assert a.host.stopped == []
code, out, err = run("chat", "open", "alpha")
assert code == 0, (code, out, err)
assert "sleeping: it wakes when you write to it" in out + err, out
assert WEB + B1 in out and APP + B1 in out, out

# 6. live and working: the links, nothing sent, nothing started
for status, word in (("idle", "live"), ("busy", "working")):
    a = setup("active", session_now=True, status=status, notes=True)
    data = jopen()
    assert data["state"] == word, data
    assert data["bridge_session_id"] == B2 and data["web_url"] == WEB + B2 and data["app_url"] == APP + B2, data
    assert sent == [] and enabled(a) == [], (word, sent, a.host.calls)
    code, out, err = run("chat", "open", "alpha")
    assert code == 0 and WEB + B2 in out and APP + B2 in out, (out, err)

# 7. timeout: never appears; exit 1, the words, about 60 seconds of fake waiting, no real waiting
a = setup("inactive", appear_after=None, notes=True)
start = a.clock.t
code, out, err = run("chat", "open", "alpha")
assert code == 1, (code, out, err)
text = out + err
assert "not ready after 60 s" in text and "press Chat again in a minute" in text, text
assert 60 <= a.clock.t - start <= 80, a.clock.t - start
assert sent == [], sent
# a different wait setting is honoured
a = setup("inactive", appear_after=None, wait=5)
start = a.clock.t
code, out, err = run("chat", "open", "alpha")
assert code == 1 and "not ready after 5 s" in out + err, (code, out, err)
assert 5 <= a.clock.t - start <= 15, a.clock.t - start

# 8. starting that never becomes ready also times out
a = setup("activating", appear_after=None)
code, out, err = run("chat", "open", "alpha")
assert code == 1 and "not ready after 60 s" in out + err, (code, out, err)

# 9. direct call does not raise for a live chat; unknown project is refused
a = setup("active", session_now=True)
pc.open_("alpha", a, "tester")
code, out, err = run("chat", "open", "ghost")
assert code != 0, (code, out, err)

# 10. a command event records who ran it
a = setup("active", session_now=True)
(phome / "logs" / "commands.jsonl").unlink(missing_ok=True)
code, out, err = run("chat", "open", "alpha", "--who", "tester")
assert code == 0, (out, err)
lines = [json.loads(x) for x in (phome / "logs" / "commands.jsonl").read_text().splitlines() if x.strip()]
assert any(l.get("who") == "tester" and "chat open" in l.get("command", "") for l in lines), lines
print("OK")
PY
mkdir -p "$TMP/phome" "$TMP/projects"
export PHOENIX_HOME="$TMP/phome" PHOENIX_PROJECTS="$TMP/projects" PHOENIX_INSTALL="$TMP/install"
export PHOENIX_NOTIFY_FILE="$TMP/notify.msg" PHOENIX_SYSTEMD_DIR="$TMP/systemd"
python3 -I "$TMP/check.py" || fail "chat open behaviour"
