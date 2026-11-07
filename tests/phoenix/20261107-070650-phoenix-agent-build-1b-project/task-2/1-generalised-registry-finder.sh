#!/bin/sh
# python3 -m pytest -q tests/test_agentlink.py
# Behaviour check: find_in() for any project folder, bridge id and mtime, send_to(), and the agent's find() unchanged.
set -u
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$ROOT" || exit 1
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

python3 -m pytest -q tests/test_agentlink.py >"$TMP/pytest.out" 2>&1 \
    || { tail -30 "$TMP/pytest.out"; fail "pytest on tests/test_agentlink.py"; }

cat >"$TMP/check.py" <<'PY'
import json, os, socket, sys, threading
sys.path.insert(0, os.getcwd())
from phoenix9 import agentlink
from tests.fakes import FakeHost

HOME = "/root/.claude"
SA, SB = "/tmp/cc-socks-0/a.sock", "/tmp/cc-socks-0/b.sock"
SID_A = "0feb0729-478d-4dc7-879a-b3fe804f3466"
SID_B = "11111111-2222-4333-8444-555555555555"

def reg(h, pid, cwd, sock, sid, bridge=None, name="x", mtime=None, started=1):
    data = {"pid": pid, "cwd": cwd, "name": name, "status": "idle", "messagingSocketPath": sock,
            "kind": "interactive", "sessionId": sid, "startedAt": started}
    if bridge is not None:
        data["bridgeSessionId"] = bridge
    p = "%s/sessions/%d.json" % (HOME, pid)
    h.files[p] = json.dumps(data)
    if mtime is not None:
        h.stats[p] = {"mode": 0o600, "uid": 0, "mtime": mtime}
    h.pids.add(pid)
    h.files[sock] = ""

# two projects side by side
h = FakeHost()
reg(h, 10, "/srv/projects/alpha", SA, SID_A, bridge="session_AAA-1_x", mtime=1234.5)
reg(h, 11, "/srv/projects/beta", SB, SID_B, bridge="session_BBB", mtime=999)
a = agentlink.find_in("/srv/projects/alpha", HOME, h)
b = agentlink.find_in("/srv/projects/beta", HOME, h)
assert a and b, (a, b)
assert (a["pid"], a["session_id"], a["socket"], a["bridge_session_id"], a["mtime"]) == \
    (10, SID_A, SA, "session_AAA-1_x", 1234.5), a
assert (b["pid"], b["session_id"], b["socket"], b["bridge_session_id"], b["mtime"]) == \
    (11, SID_B, SB, "session_BBB", 999), b
assert a["transcript"] == agentlink.transcript_path(HOME, "/srv/projects/alpha", SID_A, h), a
assert agentlink.find_in("/srv/projects/gamma", HOME, h) is None

# symlinked folder
h = FakeHost()
h.realpaths["/srv/projects/alpha"] = "/data/real/alpha"
reg(h, 10, "/data/real/alpha", SA, SID_A, bridge="bridge1")
f = agentlink.find_in("/srv/projects/alpha", HOME, h)
assert f and f["pid"] == 10, f
assert f["transcript"].startswith("/root/.claude/projects/-data-real-alpha/"), f["transcript"]

# bad bridge ids are dropped
for bad in ["", "a b", "x" * 101, "../etc", "a/b", "a\nb", 5, None, "é"]:
    h = FakeHost()
    reg(h, 10, "/srv/projects/alpha", SA, SID_A)
    d = json.loads(h.files["%s/sessions/10.json" % HOME]); d["bridgeSessionId"] = bad
    h.files["%s/sessions/10.json" % HOME] = json.dumps(d)
    f = agentlink.find_in("/srv/projects/alpha", HOME, h)
    assert f is not None and f["pid"] == 10, bad
    assert f["bridge_session_id"] is None, (bad, f["bridge_session_id"])
h = FakeHost()
reg(h, 10, "/srv/projects/alpha", SA, SID_A, bridge="x" * 100)
assert agentlink.find_in("/srv/projects/alpha", HOME, h)["bridge_session_id"] == "x" * 100
h = FakeHost()
reg(h, 10, "/srv/projects/alpha", SA, SID_A)
assert agentlink.find_in("/srv/projects/alpha", HOME, h)["bridge_session_id"] is None

# dead pid / missing socket / bad socket path give None
h = FakeHost(); reg(h, 10, "/srv/projects/alpha", SA, SID_A); h.pids.clear()
assert agentlink.find_in("/srv/projects/alpha", HOME, h) is None
h = FakeHost(); reg(h, 10, "/srv/projects/alpha", SA, SID_A); del h.files[SA]
assert agentlink.find_in("/srv/projects/alpha", HOME, h) is None
h = FakeHost(); reg(h, 10, "/srv/projects/alpha", "/tmp/evil/a.sock", SID_A)
assert agentlink.find_in("/srv/projects/alpha", HOME, h) is None

# main_pid picks the unit's process (or its direct child) among several in one folder
h = FakeHost()
reg(h, 10, "/srv/projects/alpha", SA, SID_A, started=1)
reg(h, 20, "/srv/projects/alpha", SB, SID_B, started=2)
assert agentlink.find_in("/srv/projects/alpha", HOME, h, main_pid=20)["pid"] == 20
agentlink.forget()
h.parents[20] = 77
assert agentlink.find_in("/srv/projects/alpha", HOME, h, main_pid=77)["pid"] == 20
agentlink.forget()
assert agentlink.find_in("/srv/projects/alpha", HOME, h)["pid"] == 10

# the agent's find() is unchanged: same keys, no extras
from phoenix9 import settings
agent_folder = settings.agent_settings()["folder"]
h = FakeHost()
reg(h, 10, agent_folder, SA, SID_A, bridge="br", name="Phoenix agent")
got = agentlink.find(HOME, h)
assert set(got) == {"pid", "session_id", "name", "socket", "transcript", "status"}, set(got)
agentlink.forget()

# send_to posts to the given session's socket
sockpath = os.path.join(sys.argv[1], "s.sock")
srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); srv.bind(sockpath); srv.listen(1)
box = []
def serve():
    c, _ = srv.accept(); buf = b""
    while not buf.endswith(b"\n"):
        d = c.recv(65536)
        if not d: break
        buf += d
    box.append(buf); c.close()
t = threading.Thread(target=serve, daemon=True); t.start()
h = FakeHost()
found = {"pid": 10, "session_id": SID_A, "name": "x", "socket": sockpath, "transcript": None,
         "status": "idle", "bridge_session_id": "b", "mtime": 1}
agentlink.send_to(found, "hello chat", {}, "test", 5.0, h)
t.join(5)
assert box, "nothing arrived on the socket"
msg = json.loads(box[0])
assert "hello chat" in msg["message"]["content"], msg
assert msg["type"] == "user"
print("OK")
PY
mkdir -p "$TMP/phome" "$TMP/sock"
PHOENIX_HOME="$TMP/phome" python3 -I "$TMP/check.py" "$TMP/sock" || fail "find_in / send_to behaviour"
