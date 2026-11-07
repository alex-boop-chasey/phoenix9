#!/bin/sh
# python3 -m pytest -q tests/test_projectchat.py tests/test_chat_cli.py tests/test_project_new.py
# Behaviour check: `phoenix chat catch-up` lists without --all, sets up each project without a chat document with --all, skips phoenix9, home and projects with a document, continues after a failure and exits 1, --json, command event.
set -u
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$ROOT" || exit 1
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

grep -q "catch-up" tests/test_chat_cli.py || fail "tests/test_chat_cli.py has no tests for chat catch-up"
python3 -m pytest -q tests/test_projectchat.py tests/test_chat_cli.py tests/test_project_new.py >"$TMP/pytest.out" 2>&1 \
    || { tail -30 "$TMP/pytest.out"; fail "pytest on projectchat, chat cli and project new tests"; }

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
HOME = "/root/.claude"
NAMES = ["alpha", "beta", "bad", "done", "phoenix9", "home"]
for n in NAMES:
    (root / n).mkdir()
    (root / n / "CLAUDE.md").write_text("x")
IDX = {n: i for i, n in enumerate(NAMES)}


def main_pid(n): return 100 + 10 * IDX[n]
def sess_pid(n): return main_pid(n) + 1
def sid(n): return "0feb0729-478d-4dc7-879a-b3fe804f%04d" % IDX[n]
def bridge(n): return "session_%s_1" % n.upper()


class Host(FakeHost):
    """A host with one chat unit per project; 'failing' projects refuse to start."""
    def __init__(self, failing):
        super().__init__()
        self.failing, self.units, self.added = set(failing), {}, set()

    @staticmethod
    def name(unit):
        return unit.split("@", 1)[1].split(".", 1)[0]

    def systemctl(self, *args):
        self.calls.append(["systemctl", *args])
        if args[0] == "is-active":
            st = self.units.get(self.name(args[-1]), "inactive")
            return (0 if st == "active" else 3), st + "\n", ""
        if args[0] == "show":
            n = self.name(args[-1])
            return 0, ("%d\n" % main_pid(n) if self.units.get(n) == "active" else "0\n"), ""
        if args[0] in ("enable", "start", "restart"):
            n = self.name(args[-1])
            if n in self.failing:
                return 1, "", "boom"
            self.units[n] = "active"
        return 0, "", ""

    def add_session(self, n):
        sock = "/tmp/cc-socks-0/%s.sock" % n
        data = {"pid": sess_pid(n), "cwd": str(root / n), "name": n, "status": "idle",
                "messagingSocketPath": sock, "kind": "interactive", "sessionId": sid(n), "startedAt": 1,
                "bridgeSessionId": bridge(n)}
        self.files["%s/sessions/%d.json" % (HOME, sess_pid(n))] = json.dumps(data)
        self.files[sock] = ""
        self.pids.update({main_pid(n), sess_pid(n)})
        self.parents[sess_pid(n)] = main_pid(n)
        self.added.add(n)


class Clock(FakeClock):
    """A clock whose sleeps let each started unit's conversation appear once."""
    def __init__(self, host):
        super().__init__()
        self.host = host

    def sleep(self, s):
        super().sleep(s)
        for n, st in list(self.host.units.items()):
            if st == "active" and n not in self.host.added:
                self.host.add_session(n)


sent = []
def fake_send_to(found, text, context=None, who="cli", timeout=5.0, host=None):
    sent.append(text)
    return {"sent": True, "at": "x", "after_line": 0}
agentlink.send_to = fake_send_to


def setup(failing=()):
    agentlink.forget()
    sent.clear()
    for n in NAMES:
        d = root / n / ".phoenix" / "chat.md"
        if d.exists():
            d.unlink()
    pc.write_chat_doc("done", pc.build_fields("done", "session_DONE_9", sid("done"), 1_800_000_000.0, 1_800_000_000.0))
    h = Host(failing)
    a = fake_adapters(str(phome))
    a.host, a.clock = h, Clock(h)
    adapters_mod.real = lambda: a
    common.make_adapters = lambda: a
    return a


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def enabled(a):
    return sorted({Host.name(c[-1]) for c in a.host.calls if c[:2] == ["systemctl", "enable"]})


def touched(a):
    return sorted({Host.name(c[-1]) for c in a.host.calls
                   if c[0] == "systemctl" and c[1] in ("enable", "start", "restart", "disable", "stop")})


def doc(n):
    return pc.read_chat_doc(n)[0]


# 1. without --all: lists what it would do, asks for --all, exit 0, nothing started
a = setup()
code, out, err = run("chat", "catch-up")
text = out + err
assert code == 0, (code, out, err)
assert "--all" in text, text
for n in ("alpha", "beta", "bad"):
    assert n in text, (n, text)
assert touched(a) == [] and a.host.stopped == [] and sent == [], a.host.calls
assert doc("alpha") is None and doc("beta") is None

# 2. --all with everything working: sets up alpha, beta and bad; skips done, phoenix9, home
a = setup()
code, out, err = run("chat", "catch-up", "--all")
assert code == 0, (code, out, err)
assert touched(a) == ["alpha", "bad", "beta"], a.host.calls
for n in ("alpha", "beta", "bad"):
    d = doc(n)
    assert d and d["Conversation id"] == bridge(n), (n, d)
    assert pc.state(n, a)["state"] == "sleeping", (n, pc.state(n, a))
assert sorted(a.host.stopped) == sorted(sess_pid(n) for n in ("alpha", "beta", "bad")), a.host.stopped
assert not any("Wrap up" in t for t in sent), sent
assert doc("done")["Conversation id"] == "session_DONE_9"
for n in ("phoenix9", "home"):
    assert doc(n) is None
text = out + err
for n in ("alpha", "beta", "bad"):
    assert n in text, (n, text)

# 3. a second run finds nothing to do
before = len(a.host.calls)
code, out, err = run("chat", "catch-up", "--all")
assert code == 0, (code, out, err)
assert [c for c in a.host.calls[before:] if c[:2] in (["systemctl", "enable"], ["systemctl", "start"])] == []

# 4. one failure: reported, the rest continue, exit 1
a = setup(failing=["bad"])
code, out, err = run("chat", "catch-up", "--all")
assert code == 1, (code, out, err)
text = out + err
assert "bad" in text, text
assert "alpha" in text and "beta" in text, text
for n in ("alpha", "beta"):
    d = doc(n)
    assert d and d["Conversation id"] == bridge(n), (n, d)
    assert pc.state(n, a)["state"] == "sleeping", (n, pc.state(n, a))
assert doc("bad") is None
assert set(touched(a)) <= {"alpha", "beta", "bad"} and {"alpha", "beta"} <= set(touched(a)), a.host.calls
assert sorted(a.host.stopped) == [sess_pid("alpha"), sess_pid("beta")], a.host.stopped

# 5. --json: one JSON document naming each project; exit code still 1 with a failure, 0 without
a = setup(failing=["bad"])
code, out, err = run("chat", "catch-up", "--all", "--json")
assert code == 1, (code, out, err)
data = json.loads(out)
assert isinstance(data, (dict, list)), data
dump = json.dumps(data)
for n in ("alpha", "beta", "bad"):
    assert n in dump, (n, data)
a = setup()
code, out, err = run("chat", "catch-up", "--all", "--json")
assert code == 0, (code, out, err)
dump = json.dumps(json.loads(out))
for n in ("alpha", "beta", "bad"):
    assert n in dump, (n, dump)
a = setup()
code, out, err = run("chat", "catch-up", "--json")
assert code == 0 and touched(a) == [], (code, out, err)
dump = json.dumps(json.loads(out))
for n in ("alpha", "beta", "bad"):
    assert n in dump, (n, dump)

# 6. a command event records who ran it
a = setup()
(phome / "logs" / "commands.jsonl").unlink(missing_ok=True)
code, out, err = run("chat", "catch-up", "--all", "--who", "tester")
assert code == 0, (code, out, err)
lines = [json.loads(x) for x in (phome / "logs" / "commands.jsonl").read_text().splitlines() if x.strip()]
assert any(l.get("who") == "tester" and "chat catch-up" in l.get("command", "") for l in lines), lines
print("OK")
PY
mkdir -p "$TMP/phome" "$TMP/projects"
export PHOENIX_HOME="$TMP/phome" PHOENIX_PROJECTS="$TMP/projects" PHOENIX_INSTALL="$TMP/install"
export PHOENIX_NOTIFY_FILE="$TMP/notify.msg" PHOENIX_SYSTEMD_DIR="$TMP/systemd"
python3 -I "$TMP/check.py" || fail "chat catch-up behaviour"
