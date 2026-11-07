#!/bin/sh
# python3 -m pytest -q tests/test_projectchat.py tests/test_chat_cli.py
# Behaviour check: `phoenix chat sleep` (wrap-up, wait, stop the conversation only) and `phoenix chat off` (--yes, stop and disable).
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
B = "session_BBB_2"
OLD = 1_700_000_000.0


class Host(FakeHost):
    """A host with one unit and an optional conversation whose status is scripted."""
    def __init__(self, unit, session, status="idle"):
        super().__init__()
        self.unit, self.status = unit, status
        self.status_at_stop = []
        if session:
            self.write_session()
            self.pids.update({100, 10})
            self.parents[10] = 100

    def write_session(self):
        data = {"pid": 10, "cwd": str(folder), "name": "alpha", "status": self.status,
                "messagingSocketPath": SOCK, "kind": "interactive", "sessionId": SID, "startedAt": 1,
                "bridgeSessionId": B}
        self.files["%s/sessions/10.json" % HOME] = json.dumps(data)
        self.files[SOCK] = ""

    def systemctl(self, *args):
        self.calls.append(["systemctl", *args])
        if args[0] == "is-active":
            return (0 if self.unit == "active" else 3), self.unit + "\n", ""
        if args[0] == "show":
            return 0, ("100\n" if self.unit in ("active", "activating") else "0\n"), ""
        return 0, "", ""

    def stop_pid(self, pid):
        self.status_at_stop.append(self.status)
        super().stop_pid(pid)


class Clock(FakeClock):
    """A clock whose sleeps turn a busy conversation idle after n of them."""
    def __init__(self, host, idle_after):
        super().__init__()
        self.host, self.idle_after, self.n = host, idle_after, 0

    def sleep(self, s):
        super().sleep(s)
        self.n += 1
        if self.idle_after is not None and self.n >= self.idle_after and self.host.status == "busy":
            self.host.status = "idle"
            self.host.write_session()


sent = []
def fake_send_to(found, text, context=None, who="cli", timeout=5.0, host=None):
    sent.append({"found": found, "text": text, "at": len(a.host.status_at_stop)})
    return {"sent": True, "at": "x", "after_line": 0}
agentlink.send_to = fake_send_to


def setup(unit, session=False, status="idle", idle_after=None, doc=True, wrap=None):
    global a
    agentlink.forget()
    sent.clear()
    h = Host(unit, session, status)
    a = fake_adapters(str(phome))
    a.host, a.clock = h, Clock(h, idle_after)
    adapters_mod.real = lambda: a
    common.make_adapters = lambda: a
    d = folder / ".phoenix" / "chat.md"
    if d.exists():
        d.unlink()
    if doc:
        pc.write_chat_doc("alpha", pc.build_fields("alpha", B, SID, OLD, OLD))
    cfg = phome / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "global.toml").write_text("" if wrap is None else "[chat]\nwrap_up_minutes = %d\n" % wrap)
    return a


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def unit_changes(h):
    return [c for c in h.calls if c[:2] == ["systemctl", "disable"] or c[:2] == ["systemctl", "stop"]
            or c[:2] == ["systemctl", "enable"] or c[:2] == ["systemctl", "start"]
            or c[:2] == ["systemctl", "restart"]]


def check_wrap(msg):
    assert "Wrap up" in msg and "notes/NOW.md" in msg and "notes/sessions/" in msg, msg


# 1. live: wrap-up sent, then the conversation (only) is stopped, unit untouched, doc kept and updated
a = setup("active", session=True)
code, out, err = run("chat", "sleep", "alpha")
assert code == 0, (code, out, err)
assert len(sent) == 1, sent
check_wrap(sent[0]["text"])
assert sent[0]["found"]["socket"] == SOCK
assert sent[0]["at"] == 0, "message must be sent before the stop"
assert a.host.stopped == [10], a.host.stopped
assert unit_changes(a.host) == [], a.host.calls
d, why = pc.read_chat_doc("alpha")
assert d and d["Conversation id"] == B and d["Local session id"] == SID, (d, why)
assert pc.parse_time(d["Last active"]) != OLD, d

# 2. working: waits until not busy, then stops
a = setup("active", session=True, status="busy", idle_after=4)
code, out, err = run("chat", "sleep", "alpha")
assert code == 0, (code, out, err)
assert len(sent) == 1 and a.host.stopped == [10], (sent, a.host.stopped)
assert a.host.status_at_stop == ["idle"], a.host.status_at_stop
assert a.clock.n >= 4

# 3. timeout: stays busy; waits about wrap_up_minutes (default 3) of fake time, then stops anyway
a = setup("active", session=True, status="busy")
start = a.clock.t
code, out, err = run("chat", "sleep", "alpha")
assert code == 0, (code, out, err)
waited = a.clock.t - start
assert 175 <= waited <= 260, waited
assert a.host.stopped == [10] and unit_changes(a.host) == []
a = setup("active", session=True, status="busy", wrap=1)
start = a.clock.t
code, out, err = run("chat", "sleep", "alpha")
assert code == 0 and a.host.stopped == [10], (code, out, err)
assert 55 <= a.clock.t - start <= 100, a.clock.t - start

# 4. no wrap-up variant: nothing sent, conversation stopped
a = setup("active", session=True)
pc.sleep("alpha", a, "tester", wrap_up=False)
assert sent == [], sent
assert a.host.stopped == [10], a.host.stopped
assert unit_changes(a.host) == []

# 5. direct call with wrap-up sends the message
a = setup("active", session=True)
pc.sleep("alpha", a, "tester")
assert len(sent) == 1 and a.host.stopped == [10]
check_wrap(sent[0]["text"])

# 6. already sleeping and already off: say so, exit 0, nothing sent, stopped or changed
for unit, sess, word in (("active", False, "sleeping"), ("inactive", False, "off")):
    a = setup(unit, session=sess)
    code, out, err = run("chat", "sleep", "alpha")
    assert code == 0, (code, out, err)
    assert word in (out + err).lower(), (word, out, err)
    assert sent == [] and a.host.stopped == [] and unit_changes(a.host) == [], a.host.calls

# 7. --json for sleep (live and already-asleep) is one JSON object
a = setup("active", session=True)
code, out, err = run("chat", "sleep", "alpha", "--json")
assert code == 0 and isinstance(json.loads(out), dict), (code, out, err)
a = setup("active", session=False)
code, out, err = run("chat", "sleep", "alpha", "--json")
assert code == 0 and isinstance(json.loads(out), dict), (code, out, err)

# 8. off without --yes is refused and nothing is stopped
a = setup("active", session=True)
code, out, err = run("chat", "off", "alpha")
assert code != 0, (code, out, err)
assert unit_changes(a.host) == [] and a.host.stopped == [], a.host.calls
code, out, err = run("chat", "off", "alpha", "--json")
assert code != 0 and unit_changes(a.host) == [], (code, out, err)

# 9. off --yes stops and disables the unit
a = setup("active", session=True)
code, out, err = run("chat", "off", "alpha", "--yes")
assert code == 0, (code, out, err)
dis = [c for c in a.host.calls if c[:2] == ["systemctl", "disable"]]
assert len(dis) == 1 and "--now" in dis[0] and "claude-rc-chat@alpha" in dis[0], a.host.calls
a = setup("active", session=True)
code, out, err = run("chat", "off", "alpha", "--yes", "--json")
assert code == 0 and isinstance(json.loads(out), dict), (code, out, err)
a = setup("active", session=True)
pc.off("alpha", a, "tester")
assert any(c[:2] == ["systemctl", "disable"] for c in a.host.calls), a.host.calls

# 10. unknown project refused
code, out, err = run("chat", "sleep", "ghost")
assert code != 0
code, out, err = run("chat", "off", "ghost", "--yes")
assert code != 0

# 11. command events record who ran each command
a = setup("active", session=True)
(phome / "logs" / "commands.jsonl").unlink(missing_ok=True)
assert run("chat", "sleep", "alpha", "--who", "tester")[0] == 0
a = setup("active", session=True)
assert run("chat", "off", "alpha", "--yes", "--who", "tester2")[0] == 0
lines = [json.loads(x) for x in (phome / "logs" / "commands.jsonl").read_text().splitlines() if x.strip()]
assert any(l.get("who") == "tester" and "chat sleep" in l.get("command", "") for l in lines), lines
assert any(l.get("who") == "tester2" and "chat off" in l.get("command", "") for l in lines), lines
print("OK")
PY
mkdir -p "$TMP/phome" "$TMP/projects"
export PHOENIX_HOME="$TMP/phome" PHOENIX_PROJECTS="$TMP/projects" PHOENIX_INSTALL="$TMP/install"
export PHOENIX_NOTIFY_FILE="$TMP/notify.msg" PHOENIX_SYSTEMD_DIR="$TMP/systemd"
python3 -I "$TMP/check.py" || fail "chat sleep and chat off behaviour"
