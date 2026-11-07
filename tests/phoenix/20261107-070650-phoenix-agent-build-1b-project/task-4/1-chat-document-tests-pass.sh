#!/bin/sh
# python3 -m pytest -q tests/test_projectchat.py
# Behaviour check: the chat document is written, parsed strictly, rewritten on a new id and throttled.
set -u
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$ROOT" || exit 1
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

[ -f tests/test_projectchat.py ] || fail "tests/test_projectchat.py missing"
python3 -m pytest -q tests/test_projectchat.py >"$TMP/pytest.out" 2>&1 \
    || { tail -30 "$TMP/pytest.out"; fail "pytest on tests/test_projectchat.py"; }

cat >"$TMP/check.py" <<'PY'
import os, sys, time
from pathlib import Path
sys.path.insert(0, os.getcwd())
from phoenix9 import projectchat as pc

root = Path(os.environ["PHOENIX_PROJECTS"])
(root / "alpha").mkdir()
(root / "alpha" / "CLAUDE.md").write_text("x")
doc = root / "alpha" / ".phoenix" / "chat.md"
SID = "0feb0729-478d-4dc7-879a-b3fe804f3466"
SID2 = "11111111-2222-4333-8444-555555555555"
B1, B2 = "session_AAA-1_x", "session_BBB_2"
KEYS = ["Project", "Desktop app link", "Web link", "Conversation id", "Local session id",
        "Created", "Last active"]

def found(bridge, sid):
    return {"pid": 10, "session_id": sid, "name": "alpha", "socket": "/tmp/cc-socks-0/a.sock",
            "transcript": None, "status": "idle", "bridge_session_id": bridge, "mtime": 1}

def fmt(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))

def read():
    r = pc.read_chat_doc("alpha")
    if isinstance(r, (tuple, list)) and len(r) == 2:
        return r
    return r, None

def lines():
    return doc.read_text().splitlines()

def kv():
    out = {}
    for ln in lines()[1:]:
        if ln.strip():
            k, v = ln.split(": ", 1)
            out[k] = v
    return out

T0 = 1_800_000_000.0
assert read()[0] is None            # missing document: None, no crash
pc.sync_chat_doc("alpha", found(B1, SID), T0)
assert doc.is_file()
L = lines()
assert L[0] == "# Chat: alpha", L[0]
body = [ln for ln in L[1:] if ln.strip()]
assert [ln.split(": ", 1)[0] for ln in body] == KEYS, body
d = kv()
assert d["Project"] == "alpha"
assert d["Desktop app link"] == "claude://claude.ai/code/" + B1, d
assert d["Web link"] == "https://claude.ai/code/" + B1, d
assert d["Conversation id"] == B1 and d["Local session id"] == SID
assert d["Created"] == fmt(T0), d["Created"]
import re
assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", d["Last active"]), d["Last active"]

# round trip
good, why = read()
assert good is not None, why
orig = doc.read_text()
pc.write_chat_doc("alpha", good)
assert doc.read_text() == orig, "round trip changed the document"
assert read()[0] == good

# strict parse failures
def broken(name, text):
    doc.write_text(text)
    r, why = read()
    assert r is None, name + ": accepted"
    if isinstance(pc.read_chat_doc("alpha"), (tuple, list)):
        assert isinstance(why, str) and why, name + ": no reason"
    doc.write_text(orig)
    assert read()[0] is not None

ls = orig.splitlines()
def drop(key):
    return "\n".join(x for x in ls if not x.startswith(key + ":")) + "\n"
broken("unknown key", orig + "Extra: 1\n")
for k in KEYS:
    broken("missing " + k, drop(k))
broken("duplicate", orig + "Created: " + fmt(T0) + "\n")
broken("bad id", orig.replace("Conversation id: " + B1, "Conversation id: a b"))
broken("bad id slash", orig.replace("Conversation id: " + B1, "Conversation id: ../x"))
broken("bad session id", orig.replace("Local session id: " + SID, "Local session id: nope"))
broken("web link", orig.replace("https://claude.ai/code/" + B1, "https://claude.ai/code/other"))
broken("desktop link", orig.replace("claude://claude.ai/code/" + B1, "https://claude.ai/code/" + B1))
broken("evil link", orig.replace("https://claude.ai/code/" + B1, "https://evil.example/code/" + B1))
broken("link suffix", orig.replace("https://claude.ai/code/" + B1, "https://claude.ai/code/" + B1 + "/x"))
for junk in ["", "garbage\x00\xff", "# Chat: alpha\n", "\n\n"]:
    broken("junk", junk)

# throttle: same conversation
before = doc.read_text()
pc.sync_chat_doc("alpha", found(B1, SID), T0 + 300)
assert doc.read_text() == before, "updated inside 10 minutes"
pc.sync_chat_doc("alpha", found(B1, SID), T0 + 601)
after = doc.read_text()
assert after != before, "not updated after 10 minutes"
a, b = dict(kv()), None
for k in KEYS:
    if k != "Last active":
        assert a[k] == d[k], k
assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", a["Last active"])
assert a["Last active"] != d["Last active"]
assert read()[0] is not None

# new conversation id: registry wins, Created becomes now (even inside the throttle window)
T1 = T0 + 700
pc.sync_chat_doc("alpha", found(B2, SID2), T1)
n = kv()
assert n["Conversation id"] == B2 and n["Local session id"] == SID2
assert n["Web link"] == "https://claude.ai/code/" + B2
assert n["Desktop app link"] == "claude://claude.ai/code/" + B2
assert n["Created"] == fmt(T1), n["Created"]
assert read()[0] is not None

# atomic: a failed swap leaves the old document whole and no temp files behind
keep = doc.read_text()
real = os.replace
def boom(*a, **k):
    raise OSError("boom")
os.replace = boom
try:
    try:
        pc.write_chat_doc("alpha", read()[0] | {}) if isinstance(read()[0], dict) else pc.sync_chat_doc("alpha", found(B1, SID), T1 + 5000)
    except Exception:
        pass
finally:
    os.replace = real
assert doc.read_text() == keep, "document changed by a failed write"
assert sorted(p.name for p in doc.parent.iterdir()) == ["chat.md"], list(doc.parent.iterdir())
print("OK")
PY
mkdir -p "$TMP/phome" "$TMP/projects"
PHOENIX_HOME="$TMP/phome" PHOENIX_PROJECTS="$TMP/projects" python3 -I "$TMP/check.py" || fail "chat document behaviour"
