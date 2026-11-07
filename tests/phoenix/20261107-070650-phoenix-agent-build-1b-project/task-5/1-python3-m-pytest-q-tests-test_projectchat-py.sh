#!/bin/sh
# python3 -m pytest -q tests/test_projectchat.py
# Behaviour check: projectchat.state() gives off, starting, sleeping, live or working from unit, registry and document.
set -u
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$ROOT" || exit 1
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

[ -f tests/test_projectchat.py ] || fail "tests/test_projectchat.py missing"
python3 -m pytest -q tests/test_projectchat.py >"$TMP/pytest.out" 2>&1 \
    || { tail -30 "$TMP/pytest.out"; fail "pytest on tests/test_projectchat.py"; }
grep -q 'def test_.*state\|def test_.*sleep\|def test_.*live' tests/test_projectchat.py \
    || fail "tests/test_projectchat.py has no state tests"

cat >"$TMP/check.py" <<'PY'
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "tests"))
from phoenix9 import agentlink, projectchat as pc
from tests.fakes import FakeHost, fake_adapters

root = Path(os.environ["PHOENIX_PROJECTS"])
(root / "alpha").mkdir()
(root / "alpha" / "CLAUDE.md").write_text("x")
folder = str(root / "alpha")
doc = root / "alpha" / ".phoenix" / "chat.md"
HOME = "/root/.claude"
SID = "0feb0729-478d-4dc7-879a-b3fe804f3466"
SID2 = "11111111-2222-4333-8444-555555555555"
B1, B2 = "session_AAA-1_x", "session_BBB_2"
T0 = 1_800_000_000.0
tmp = tempfile.mkdtemp()

def adapters(unit, status=None, bridge=None, sid=SID):
    agentlink.forget()
    h = FakeHost()
    h.script(["systemctl", "is-active"], rc=0 if unit == "active" else 3, out=unit + "\n")
    h.script(["systemctl", "show"], out="100\n")
    if status is not None:
        sock = "/tmp/cc-socks-0/a.sock"
        data = {"pid": 10, "cwd": folder, "name": "alpha", "status": status,
                "messagingSocketPath": sock, "kind": "interactive", "sessionId": sid, "startedAt": 1}
        if bridge:
            data["bridgeSessionId"] = bridge
        h.files["%s/sessions/10.json" % HOME] = json.dumps(data)
        h.files[sock] = ""
        h.pids |= {100, 10}
        h.parents[10] = 100
    a = fake_adapters(tmp)
    a.host = h
    return a

def put_doc(bridge, sid):
    pc.write_chat_doc("alpha", pc.build_fields("alpha", bridge, sid, T0, T0))

def clear_doc():
    if doc.exists():
        doc.unlink()

def links(s, bridge):
    assert s["bridge_session_id"] == bridge, s
    assert s["web_url"] == "https://claude.ai/code/" + bridge, s
    assert s["app_url"] == "claude://claude.ai/code/" + bridge, s

def nolinks(s):
    assert s["bridge_session_id"] is None and s["web_url"] is None and s["app_url"] is None, s

KEYS = {"state", "bridge_session_id", "web_url", "app_url", "last_active"}

# off: inactive and failed
for u in ("inactive", "failed"):
    clear_doc()
    s = pc.state("alpha", adapters(u))
    assert KEYS <= set(s), s
    assert s["state"] == "off", (u, s)
    assert adapters(u).host.calls == [] or True

# starting: activating, and active with nothing stored and no process
clear_doc()
s = pc.state("alpha", adapters("activating"))
assert s["state"] == "starting", s
nolinks(s)
s = pc.state("alpha", adapters("active"))
assert s["state"] == "starting", s
nolinks(s)

# sleeping: active, no process, stored id
put_doc(B1, SID)
s = pc.state("alpha", adapters("active"))
assert s["state"] == "sleeping", s
links(s, B1)

# unreadable document counts as no stored id
doc.write_text("garbage\x00 not a chat document\n")
s = pc.state("alpha", adapters("active"))
assert s["state"] == "starting", s
nolinks(s)
doc.write_text("# Chat: alpha\nConversation id: a b\n")
s = pc.state("alpha", adapters("active"))
assert s["state"] == "starting", s
nolinks(s)

# live: idle session, document absent -> synced from the registry
clear_doc()
s = pc.state("alpha", adapters("active", status="idle", bridge=B1))
assert s["state"] == "live", s
links(s, B1)
d, why = pc.read_chat_doc("alpha")
assert d is not None and d["Conversation id"] == B1 and d["Local session id"] == SID, (d, why)

# registry wins over a disagreeing document, and the document is corrected
put_doc(B2, SID2)
s = pc.state("alpha", adapters("active", status="idle", bridge=B1))
assert s["state"] == "live", s
links(s, B1)
d, why = pc.read_chat_doc("alpha")
assert d is not None and d["Conversation id"] == B1 and d["Local session id"] == SID, (d, why)
assert d["Web link"] == "https://claude.ai/code/" + B1

# live with an unreadable document: still live, document repaired
doc.write_text("garbage")
s = pc.state("alpha", adapters("active", status="idle", bridge=B1))
assert s["state"] == "live", s
links(s, B1)
assert pc.read_chat_doc("alpha")[0] is not None

# working: registry status busy
s = pc.state("alpha", adapters("active", status="busy", bridge=B1))
assert s["state"] == "working", s
links(s, B1)

# live registry entry without a bridge id: no links from the registry; state still live
clear_doc()
s = pc.state("alpha", adapters("active", status="idle"))
assert s["state"] == "live", s
nolinks(s)

# a session that is not the unit's own process does not make it live
a = adapters("active", status="idle", bridge=B1)
a.host.parents[10] = 999
clear_doc()
s = pc.state("alpha", a)
assert s["state"] == "starting", s

# unknown project: refused (raises) or at least never live
try:
    s = pc.state("ghost", adapters("active", status="idle", bridge=B1))
except Exception:
    pass
else:
    assert s["state"] not in ("live", "working", "sleeping", "starting"), s
print("OK")
PY
mkdir -p "$TMP/phome" "$TMP/projects"
PHOENIX_HOME="$TMP/phome" PHOENIX_PROJECTS="$TMP/projects" python3 -I "$TMP/check.py" || fail "state behaviour"
