#!/bin/sh
# python3 -m pytest -q tests/test_projectchat.py tests/test_project_new.py tests/test_project_remove_import.py
# Behaviour check: project new and import open then sleep the chat (wrap_up=False); any failure still makes the project with "chat not set up yet".
set -u
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$ROOT" || exit 1
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

grep -q "not set up yet" tests/test_project_new.py || fail "tests/test_project_new.py has no test for 'not set up yet'"
grep -q "not set up yet" tests/test_project_remove_import.py || fail "tests/test_project_remove_import.py has no test for 'not set up yet'"
python3 -m pytest -q tests/test_projectchat.py tests/test_project_new.py tests/test_project_remove_import.py >"$TMP/pytest.out" 2>&1 \
    || { tail -30 "$TMP/pytest.out"; fail "pytest on projectchat, project new and import tests"; }

cat >"$TMP/check.py" <<'PY'
import json, os, sys
from pathlib import Path
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "tests"))
from phoenix9 import agentlink, projectchat as pc, project, project_removal
from fakes import FakeHost, FakeClock, fake_adapters

root = Path(os.environ["PHOENIX_PROJECTS"])
phome = Path(os.environ["PHOENIX_HOME"])
CLAUDE_JSON = os.environ["PHOENIX_CLAUDE_JSON"]
HOME = "/root/.claude"
SOCK = "/tmp/cc-socks-0/a.sock"
SID = "0feb0729-478d-4dc7-879a-b3fe804f3466"
B = "session_BBB_2"
WORDS = "chat not set up yet: press Chat to try again"


class Host(FakeHost):
    """A host whose unit starts on enable (or refuses to) and whose conversation appears when scripted."""
    def __init__(self, mode, folder):
        super().__init__()
        self.mode, self.folder, self.unit = mode, folder, "inactive"
        self.files[CLAUDE_JSON] = json.dumps({"projects": {}})

    def systemctl(self, *args):
        self.calls.append(["systemctl", *args])
        if args[0] == "is-active":
            return (0 if self.unit == "active" else 3), self.unit + "\n", ""
        if args[0] == "show":
            return 0, ("100\n" if self.unit == "active" else "0\n"), ""
        if args[0] in ("enable", "start", "restart"):
            if self.mode == "fail":
                return 1, "", "boom"
            self.unit = "active"
        return 0, "", ""

    def add_session(self):
        data = {"pid": 10, "cwd": str(self.folder), "name": "x", "status": "idle",
                "messagingSocketPath": SOCK, "kind": "interactive", "sessionId": SID, "startedAt": 1,
                "bridgeSessionId": B}
        self.files["%s/sessions/10.json" % HOME] = json.dumps(data)
        self.files[SOCK] = ""
        self.pids.update({100, 10})
        self.parents[10] = 100


class Clock(FakeClock):
    """A clock whose first sleep makes the conversation appear (when the host works)."""
    def __init__(self, host):
        super().__init__()
        self.host = host

    def sleep(self, s):
        super().sleep(s)
        if self.host.mode == "ok":
            self.host.add_session()


sent = []
def fake_send_to(found, text, context=None, who="cli", timeout=5.0, host=None):
    sent.append(text)
    return {"sent": True, "at": "x", "after_line": 0}
agentlink.send_to = fake_send_to


def adapters_for(mode, folder):
    agentlink.forget()
    sent.clear()
    h = Host(mode, folder)
    a = fake_adapters(str(phome))
    a.host, a.clock = h, Clock(h)
    return a


def enables(h):
    return [c for c in h.calls if c[:2] == ["systemctl", "enable"]]


def check_ok(result, name, a):
    assert result.get("chat") == "sleeping", result
    assert WORDS not in json.dumps(result), result
    assert len(enables(a.host)) == 1 and "claude-rc-chat@" + name in enables(a.host)[0], a.host.calls
    assert a.host.stopped == [10], a.host.stopped
    assert not [c for c in a.host.calls if c[:2] == ["systemctl", "disable"]], a.host.calls
    assert not any("Wrap up" in t for t in sent), sent
    d, why = pc.read_chat_doc(name)
    assert d and d["Conversation id"] == B, (d, why)
    assert pc.state(name, a)["state"] == "sleeping"


def check_failed(result, name, folder, lines):
    assert result.get("chat") == "not set up yet", result
    assert WORDS in json.dumps(result), result
    assert any(WORDS in l for l in lines), lines
    assert folder.is_dir() and (folder / "CLAUDE.md").is_file()


def make_opts(name):
    return {"name": name, "description": "A demo thing.", "no_new_repo": True, "profile": "python-script"}


# project new: success
folder = root / "okproj"
a = adapters_for("ok", folder)
lines = []
r = project.create(make_opts("okproj"), a, "tester", progress=lines.append)
assert r["name"] == "okproj" and (folder / "CLAUDE.md").is_file(), r
check_ok(r, "okproj", a)
assert not any(WORDS in l for l in lines), lines

# project new: systemctl failing still creates the project
folder = root / "badunit"
a = adapters_for("fail", folder)
lines = []
r = project.create(make_opts("badunit"), a, "tester", progress=lines.append)
assert r["name"] == "badunit", r
check_failed(r, "badunit", folder, lines)

# project new: the chat never comes up (timeout) still creates the project
folder = root / "slowproj"
a = adapters_for("never", folder)
lines = []
r = project.create(make_opts("slowproj"), a, "tester", progress=lines.append)
check_failed(r, "slowproj", folder, lines)


def unlisted(name):
    f = root / name
    (f / "notes").mkdir(parents=True)
    (f / "code").mkdir()
    (f / "code" / "main.py").write_text("print(1)\n")
    return f


# import: success
folder = unlisted("impok")
a = adapters_for("ok", folder)
r = project_removal.import_("impok", "tester", a)
assert r["name"] == "impok" and (folder / "CLAUDE.md").is_file(), r
check_ok(r, "impok", a)

# import: failing systemctl still imports
folder = unlisted("impbad")
a = adapters_for("fail", folder)
r = project_removal.import_("impbad", "tester", a)
assert r["name"] == "impbad", r
check_failed(r, "impbad", folder, [json.dumps(r)])

# import: timeout still imports
folder = unlisted("impslow")
a = adapters_for("never", folder)
r = project_removal.import_("impslow", "tester", a)
check_failed(r, "impslow", folder, [json.dumps(r)])
print("OK")
PY
mkdir -p "$TMP/phome" "$TMP/projects"
export PHOENIX_HOME="$TMP/phome" PHOENIX_PROJECTS="$TMP/projects" PHOENIX_INSTALL="$TMP/install"
export PHOENIX_NOTIFY_FILE="$TMP/notify.msg" PHOENIX_SYSTEMD_DIR="$TMP/systemd" PHOENIX_CLAUDE_JSON="$TMP/claude.json"
python3 -I "$TMP/check.py" || fail "project creation and import set up the chat"
