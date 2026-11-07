#!/bin/sh
# python3 -m pytest -q tests/test_api_chat.py tests/test_api_guard.py tests/test_ops_dashboard_reads.py
# Behaviour check: the chat API routes (state, open, sleep, off), their guards, 404/400/503, and the chat field on project rows.
set -u
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$ROOT" || exit 1
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

[ -f tests/test_api_chat.py ] || fail "tests/test_api_chat.py missing"
python3 -m pytest -q tests/test_api_chat.py tests/test_api_guard.py tests/test_ops_dashboard_reads.py >"$TMP/pytest.out" 2>&1 \
    || { tail -30 "$TMP/pytest.out"; fail "pytest on api chat, api guard and dashboard reads tests"; }

cat >"$TMP/check.py" <<'PY'
import json, os, sys, threading, urllib.error, urllib.request
from pathlib import Path
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "tests"))
from phoenix9 import adapters as adapters_mod, agentlink, projectchat as pc, settings
from phoenix9.api import server
from phoenix9.ops import common
from fakes import FakeHost, FakeClock, fake_adapters

root = Path(os.environ["PHOENIX_PROJECTS"])
phome = Path(os.environ["PHOENIX_HOME"])
HOME = "/root/.claude"
SOCK = "/tmp/cc-socks-0/a.sock"
SID = "0feb0729-478d-4dc7-879a-b3fe804f3466"
B1, B2 = "session_AAA-1_x", "session_BBB_2"
T0 = 1_800_000_000.0
ORIGIN = "https://phoenix.rebirthwebdesign.com.au"
HDR = {"X-Phoenix": "1", "Origin": ORIGIN, "Content-Type": "application/json"}
WEB, APP = "https://claude.ai/code/", "claude://claude.ai/code/"


def make_project(name):
    folder = root / name
    (folder / "notes").mkdir(parents=True)
    (folder / "CLAUDE.md").write_text("# %s\n\nAbout %s.\n\n- Profile: python-script\n- Repo: (none yet)\n" % (name, name))
    settings.save_project(folder, {"profile": "python-script"})
    return folder


alpha = make_project("alpha")
make_project("beta")


class Host(FakeHost):
    """A host whose unit state is scripted; the registry entry can be added."""
    def __init__(self, unit, session=False, status="idle"):
        super().__init__()
        self.unit, self.status = unit, status
        if session:
            self.add_session()

    def add_session(self):
        data = {"pid": 10, "cwd": str(alpha), "name": "alpha", "status": self.status,
                "messagingSocketPath": SOCK, "kind": "interactive", "sessionId": SID, "startedAt": 1,
                "bridgeSessionId": B2}
        self.files["%s/sessions/10.json" % HOME] = json.dumps(data)
        self.files[SOCK] = ""
        self.pids.update({100, 10})
        self.parents[10] = 100

    def systemctl(self, *args):
        self.calls.append(["systemctl", *args])
        if args[0] == "is-active":
            return (0 if self.unit == "active" else 3), self.unit + "\n", ""
        if args[0] == "show":
            return 0, ("100\n" if self.unit in ("active", "activating") else "0\n"), ""
        if args[0] == "enable" and self.unit in ("inactive", "failed"):
            self.unit = "active"
            self.add_session()
        return 0, "", ""


sent = []
def fake_send_to(found, text, context=None, who="cli", timeout=5.0, host=None):
    sent.append(text)
    return {"sent": True, "at": "x", "after_line": 0}
agentlink.send_to = fake_send_to

dist = Path(os.environ["TMPDIR_CHECK"]) / "dist"
(dist / "assets").mkdir(parents=True)
(dist / "index.html").write_text("<html></html>")
current = {}


def setup(unit, session=False, status="idle", doc=None, wait=None):
    agentlink.forget()
    sent.clear()
    h = Host(unit, session, status)
    a = fake_adapters(str(phome))
    a.host, a.clock = h, FakeClock()
    adapters_mod.real = lambda: a
    common.make_adapters = lambda: a
    d = alpha / ".phoenix" / "chat.md"
    if d.exists():
        d.unlink()
    if doc:
        pc.write_chat_doc("alpha", pc.build_fields("alpha", doc, SID, T0, T0))
    cfg = phome / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "global.toml").write_text("" if wait is None else "[chat]\nstart_wait_seconds = %d\n" % wait)
    current["a"] = a
    return a


setup("inactive")
httpd = server.make_server(0, web_dist=dist)
threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
BASE = "http://127.0.0.1:%d" % httpd.server_address[1]


def call(path, method="GET", headers=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers or {})
    try:
        resp = urllib.request.urlopen(req)
    except urllib.error.HTTPError as err:
        resp = err
    raw = resp.read()
    resp.close()
    return resp.status, json.loads(raw)


def post(path, body=None):
    return call(path, "POST", HDR, {} if body is None else body)


def changes(a):
    return [c for c in a.host.calls if c[:2] in (["systemctl", "enable"], ["systemctl", "disable"],
                                                 ["systemctl", "stop"], ["systemctl", "start"])]


STATE_KEYS = {"state", "bridge_session_id", "web_url", "app_url", "last_active"}
OPEN_KEYS = {"state", "web_url", "app_url", "bridge_session_id", "message"}

# 1. unknown project: 404 on every route
setup("inactive")
for method, path in (("GET", "/api/chat/ghost"), ("POST", "/api/chat/ghost/open"),
                     ("POST", "/api/chat/ghost/sleep"), ("POST", "/api/chat/ghost/off")):
    st, body = (call(path) if method == "GET" else post(path, {"confirm": True}))
    assert st == 404 and body["ok"] is False, (path, st, body)

# 2. guards: writes need X-Phoenix and an allowed Origin; peer must be root
a = setup("active", session=True)
for path in ("/api/chat/alpha/open", "/api/chat/alpha/sleep", "/api/chat/alpha/off"):
    for hdr in ({"Origin": ORIGIN, "Content-Type": "application/json"},
                {"X-Phoenix": "1", "Content-Type": "application/json"},
                {"X-Phoenix": "1", "Origin": "https://evil.example", "Content-Type": "application/json"}):
        st, body = call(path, "POST", hdr, {"confirm": True})
        assert st == 403 and body["ok"] is False, (path, hdr, st, body)
assert changes(a) == [] and a.host.stopped == [] and sent == [], (a.host.calls, sent)
a.host.peer_uid = 4242
assert call("/api/chat/alpha")[0] == 403
assert post("/api/chat/alpha/open")[0] == 403
assert post("/api/chat/alpha/sleep")[0] == 403
assert post("/api/chat/alpha/off", {"confirm": True})[0] == 403
assert call("/api/projects")[0] == 403
assert changes(a) == [] and a.host.stopped == [], a.host.calls

# 3. GET state: off, sleeping, live, working
setup("inactive")
st, body = call("/api/chat/alpha")
assert st == 200 and body["ok"] is True and set(body["data"]) == STATE_KEYS and body["data"]["state"] == "off", (st, body)
setup("active", doc=B1)
st, body = call("/api/chat/alpha")
d = body["data"]
assert st == 200 and set(d) == STATE_KEYS and d["state"] == "sleeping", body
assert d["bridge_session_id"] == B1 and d["web_url"] == WEB + B1 and d["app_url"] == APP + B1, d
for status, word in (("idle", "live"), ("busy", "working")):
    setup("active", session=True, status=status)
    st, body = call("/api/chat/alpha")
    d = body["data"]
    assert st == 200 and d["state"] == word and d["bridge_session_id"] == B2 and d["web_url"] == WEB + B2, body

# 4. POST open: off starts it; live opens without starting
a = setup("inactive")
st, body = post("/api/chat/alpha/open")
d = body["data"]
assert st == 200 and body["ok"] is True and set(d) == OPEN_KEYS, (st, body)
assert d["state"] in ("live", "working") and d["bridge_session_id"] == B2, d
assert d["web_url"] == WEB + B2 and d["app_url"] == APP + B2 and isinstance(d["message"], str), d
assert len([c for c in a.host.calls if c[:2] == ["systemctl", "enable"]]) == 1, a.host.calls
a = setup("active", session=True)
st, body = post("/api/chat/alpha/open")
assert st == 200 and body["data"]["state"] == "live" and body["data"]["web_url"] == WEB + B2, body
assert changes(a) == [] and sent == [], (a.host.calls, sent)

# 5. start timeout: 503 with the plain message
class NeverHost(Host):
    def systemctl(self, *args):
        r = super().systemctl(*args)
        if args[0] == "enable":
            self.files.pop("%s/sessions/10.json" % HOME, None)
        return r
a = setup("inactive", wait=5)
a.host.__class__ = NeverHost
st, body = post("/api/chat/alpha/open")
assert st == 503 and body["ok"] is False, (st, body)
assert "not ready after 5 s" in body["message"] and "press Chat again in a minute" in body["message"], body

# 6. POST sleep: live is wrapped up and stopped, unit untouched
a = setup("active", session=True)
st, body = post("/api/chat/alpha/sleep")
assert st == 200 and body["ok"] is True and isinstance(body["data"], dict), (st, body)
assert a.host.stopped == [10] and len(sent) == 1 and "Wrap up" in sent[0], (a.host.stopped, sent)
assert changes(a) == [], a.host.calls

# 7. POST off: needs confirm true
a = setup("active", session=True)
for payload in ({}, {"confirm": False}, {"confirm": "yes"}):
    st, body = post("/api/chat/alpha/off", payload)
    assert st == 400 and body["ok"] is False, (payload, st, body)
assert changes(a) == [] and a.host.stopped == [], a.host.calls
st, body = post("/api/chat/alpha/off", {"confirm": True})
assert st == 200 and body["ok"] is True, (st, body)
dis = [c for c in a.host.calls if c[:2] == ["systemctl", "disable"]]
assert len(dis) == 1 and "--now" in dis[0] and "claude-rc-chat@alpha" in dis[0], a.host.calls

# 8. project rows carry the chat state object
setup("active", doc=B1)
st, body = call("/api/projects")
rows = {r["name"]: r for r in body["data"]}
assert st == 200 and set(rows) == {"alpha", "beta"}, body
assert set(rows["alpha"]["chat"]) == STATE_KEYS and rows["alpha"]["chat"]["state"] == "sleeping", rows["alpha"]
assert rows["alpha"]["chat"]["web_url"] == WEB + B1, rows["alpha"]["chat"]
assert rows["beta"]["chat"]["state"] in ("sleeping", "off"), rows["beta"]
# filtered lists keep the field where rows are returned flat
# 9. one project's chat failing gives chat null, the list still works
real_state = pc.state
def broken(project, adapters, *a, **k):
    if project == "beta":
        raise RuntimeError("boom")
    return real_state(project, adapters, *a, **k)
pc.state = broken
st, body = call("/api/projects")
rows = {r["name"]: r for r in body["data"]}
assert st == 200 and set(rows) == {"alpha", "beta"}, (st, body)
assert "chat" in rows["beta"] and rows["beta"]["chat"] is None, rows["beta"]
assert rows["alpha"]["chat"]["state"] == "sleeping", rows["alpha"]
pc.state = real_state
httpd.shutdown()
print("OK")
PY
mkdir -p "$TMP/phome" "$TMP/projects"
export PHOENIX_HOME="$TMP/phome" PHOENIX_PROJECTS="$TMP/projects" PHOENIX_INSTALL="$TMP/install"
export PHOENIX_NOTIFY_FILE="$TMP/notify.msg" PHOENIX_SYSTEMD_DIR="$TMP/systemd"
export PHOENIX_CLAUDE_JSON="$TMP/claude.json" TMPDIR_CHECK="$TMP"
echo '{"projects": {}}' >"$TMP/claude.json"
python3 -I "$TMP/check.py" || fail "chat api behaviour"
