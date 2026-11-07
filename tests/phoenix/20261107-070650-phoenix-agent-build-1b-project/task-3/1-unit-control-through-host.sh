#!/bin/sh
# python3 -m pytest -q tests/test_chat_units.py tests/test_adapters.py
# Behaviour check: chat unit helpers go through the Host adapter, refuse unlisted names, and only stop their own processes.
set -u
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$ROOT" || exit 1
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

[ -f tests/test_chat_units.py ] || fail "tests/test_chat_units.py missing"
python3 -m pytest -q tests/test_chat_units.py tests/test_adapters.py >"$TMP/pytest.out" 2>&1 \
    || { tail -30 "$TMP/pytest.out"; fail "pytest on chat unit and adapter tests"; }

cat >"$TMP/check.py" <<'PY'
import json, os, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "tests"))
from phoenix9 import chat, paths, agentlink
from phoenix9.adapters import Host
from tests.fakes import FakeHost

root = Path(os.environ["PHOENIX_PROJECTS"])
for n in ("alpha", "beta"):
    (root / n).mkdir()
    (root / n / "CLAUDE.md").write_text("x")
(root / "nofile").mkdir()          # a folder without CLAUDE.md is not a listed project

# chat_unit
assert chat.chat_unit("alpha") == "claude-rc-chat@alpha"
for bad in ["nofile", "ghost", "", "../alpha", "alpha/../beta", "alpha beta", "alpha@x", "-alpha", "alpha;ls"]:
    try:
        got = chat.chat_unit(bad)
    except Exception:
        continue
    raise AssertionError("accepted %r -> %r" % (bad, got))

# unit_state
U = "claude-rc-chat@alpha"
for out, rc, want in [("active\n", 0, "active"), ("activating\n", 3, "activating"),
                      ("inactive\n", 3, "inactive"), ("failed\n", 3, "failed")]:
    h = FakeHost(); h.script(["systemctl", "is-active", U], rc=rc, out=out)
    assert chat.unit_state(h, "alpha") == want, (out, chat.unit_state(h, "alpha"))
    assert ["systemctl", "is-active", U] in [c[:3] for c in h.calls], h.calls
h = FakeHost()
try:
    chat.unit_state(h, "ghost"); raise AssertionError("unlisted name accepted")
except AssertionError:
    raise
except Exception:
    pass
assert not h.calls, h.calls

# unit_main_pid
h = FakeHost(); h.script(["systemctl", "show"], out="4321\n")
assert chat.unit_main_pid(h, "alpha") == 4321
show = [c for c in h.calls if c[:2] == ["systemctl", "show"]]
assert show and U in show[0] and "MainPID" in " ".join(show[0]), h.calls
h = FakeHost(); h.script(["systemctl", "show"], out="0\n")
assert not chat.unit_main_pid(h, "alpha")

# start / stop
h = FakeHost(); chat.start_unit(h, "alpha")
c = [x for x in h.calls if x[:1] == ["systemctl"]]
assert len(c) == 1 and c[0][1] == "enable" and "--now" in c[0] and c[0][-1] == U, h.calls
h = FakeHost(); chat.stop_unit(h, "alpha")
c = [x for x in h.calls if x[:1] == ["systemctl"]]
assert len(c) == 1 and c[0][1] == "disable" and "--now" in c[0] and c[0][-1] == U, h.calls
for fn in (chat.start_unit, chat.stop_unit):
    h = FakeHost()
    try:
        fn(h, "ghost"); raise AssertionError("unlisted accepted")
    except AssertionError:
        raise
    except Exception:
        pass
    assert not h.calls

# stop_conversation
class Rec(FakeHost):
    def __init__(self):
        super().__init__(); self.stopped = []
    def stop_pid(self, pid):
        self.stopped.append(pid)

assert hasattr(FakeHost, "stop_pid") and hasattr(Host, "stop_pid")
HOME = "/root/.claude"
folder = str(root / "alpha")
def reg(h, pid, cwd, n):
    sock = "/tmp/cc-socks-0/s%d.sock" % n
    h.files["%s/sessions/%d.json" % (HOME, pid)] = json.dumps(
        {"pid": pid, "cwd": cwd, "name": "x", "status": "idle", "messagingSocketPath": sock,
         "kind": "interactive", "sessionId": "0feb0729-478d-4dc7-879a-b3fe804f3466", "startedAt": n})
    h.files[sock] = ""; h.pids.add(pid)

# direct child of the unit's MainPID
h = Rec(); h.pids |= {100, 200}; h.parents[200] = 100
h.script(["systemctl", "show"], out="100\n")
chat.stop_conversation(h, "alpha", 200)
assert h.stopped == [200], h.stopped
# unrelated pid: refused (nothing signalled)
h = Rec(); h.pids |= {100, 300}; h.parents[300] = 1
h.script(["systemctl", "show"], out="100\n")
try:
    chat.stop_conversation(h, "alpha", 300)
except Exception:
    pass
assert h.stopped == [], h.stopped
# a grandchild is not a direct child
h = Rec(); h.pids |= {100, 200, 201}; h.parents[200] = 100; h.parents[201] = 200
h.script(["systemctl", "show"], out="100\n")
try:
    chat.stop_conversation(h, "alpha", 201)
except Exception:
    pass
assert h.stopped == [], h.stopped
# registry entry for the project
agentlink.forget()
h = Rec(); reg(h, 500, folder, 1); h.script(["systemctl", "show"], out="0\n")
chat.stop_conversation(h, "alpha", 500)
assert h.stopped == [500], h.stopped
# registry entry of another project is refused
agentlink.forget()
h = Rec(); reg(h, 501, str(root / "beta"), 2); h.script(["systemctl", "show"], out="0\n")
try:
    chat.stop_conversation(h, "alpha", 501)
except Exception:
    pass
assert h.stopped == [], h.stopped

# real Host.stop_pid sends SIGTERM (only to a throwaway child of this test)
p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
try:
    Host().stop_pid(p.pid)
    p.wait(timeout=10)
    assert p.returncode == -15, p.returncode
finally:
    if p.poll() is None:
        p.kill()
print("OK")
PY
mkdir -p "$TMP/phome" "$TMP/projects"
PHOENIX_HOME="$TMP/phome" PHOENIX_PROJECTS="$TMP/projects" python3 -I "$TMP/check.py" || fail "unit helpers behaviour"
