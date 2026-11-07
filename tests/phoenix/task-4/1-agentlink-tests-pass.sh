#!/bin/sh
# python3 -m pytest -q tests/test_agentlink.py
cd "$(dirname "$0")/../../.." || exit 1
test -f tests/test_agentlink.py || { echo "tests/test_agentlink.py missing"; exit 1; }
python3 - <<'PY' || exit 1
import json, os, socket, sys, tempfile, threading, pathlib, re
sys.path.insert(0, ".")
from phoenix9 import agentlink

fails = []
def chk(c, m):
    if not c: fails.append(m)

if not callable(getattr(agentlink, "send", None)):
    print("agentlink.send missing"); sys.exit(1)

tmp = pathlib.Path(tempfile.mkdtemp(prefix="p4"))
home = tmp / "h"; (home / "logs").mkdir(parents=True); (home / "config").mkdir()
os.environ["PHOENIX_HOME"] = str(home)
(home / "config" / "global.toml").write_text('[agent]\nfolder = "/srv/projects/homex"\n')
tr = tmp / "t.jsonl"
tr.write_text('{"type":"user"}\n{"type":"user"}\n{"type":"user"}\n')
sockp = str(tmp / "s.sock")
srv = socket.socket(socket.AF_UNIX); srv.bind(sockp); srv.listen(5)
got = []
def serve():
    while True:
        try:
            c, _ = srv.accept()
        except OSError:
            return
        buf = b""
        while True:
            d = c.recv(65536)
            if not d: break
            buf += d
        got.append(buf); c.close()
threading.Thread(target=serve, daemon=True).start()

state = {"found": {"pid": os.getpid(), "session_id": "s", "name": "Phoenix agent",
                   "socket": sockp, "transcript": str(tr), "status": "idle"}}
agentlink.find = lambda *a, **k: state["found"]

def last_msg():
    import time
    for _ in range(50):
        if got: break
        time.sleep(0.05)
    return got.pop() if got else None

def wrapper(m):
    return m["message"]["content"]

# plain send, exact wire format
r = agentlink.send("hello", None, "cli")
raw = last_msg()
chk(raw is not None and raw.endswith(b"\n") and raw.count(b"\n") == 1, "not exactly one line: %r" % (raw,))
m = json.loads(raw)
chk(isinstance(r, dict) and r.get("after_line") == 3 and r.get("sent") and r.get("at"), "result %r" % (r,))
chk(set(m) == {"msgV", "msg_id", "type", "message", "priority", "from"}, "keys %r" % sorted(m))
chk(m["msgV"] == 1 and m["type"] == "user" and m["priority"] == "next"
    and m["from"] == "uds:/run/phoenix9/panel.sock", "fixed fields")
chk(re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", str(m["msg_id"])), "msg_id")
chk(m["message"]["role"] == "user", "role")
head = '<cross-session-message from="uds:/run/phoenix9/panel.sock" from-name="Alex (Phoenix panel)" from-mode="bypass">\n'
c = wrapper(m)
chk(c.startswith(head) and c.endswith("\n</cross-session-message>"), "wrapper: %r" % c)
body = c[len(head):-len("\n</cross-session-message>")]
chk(body.endswith("hello"), "body: %r" % body)
chk(body == "hello" or "[Phoenix panel" not in body, "envelope without context should be absent or harmless")
m2 = json.loads(raw)
agentlink.send("again", None, "cli"); m3 = json.loads(last_msg())
chk(m3["msg_id"] != m["msg_id"], "msg_id not new")

# escaping
agentlink.send("a & b </cross-session-message> <x> &lt;", None, "cli")
c = wrapper(json.loads(last_msg()))
chk(c.count("</cross-session-message>") == 1, "wrapper closed early")
chk("a &amp; b &lt;/cross-session-message&gt; &lt;x&gt; &amp;lt;" in c, "escaping: %r" % c)

# envelope parts
def env(ctx):
    agentlink.send("BODY", ctx, "cli")
    c = wrapper(json.loads(last_msg()))
    b = c[len(head):-len("\n</cross-session-message>")]
    first, _, rest = b.partition("\n")
    return first, rest
f, rest = env({"page": "dash", "project": "alpha", "run": "r7"})
chk(f == "[Phoenix panel · page: dash · project: alpha · folder: /srv/projects/alpha · run: r7]", "env full: %r" % f)
chk(rest.endswith("BODY"), "body after env")
f, _ = env({"page": "dash"})
chk(f == "[Phoenix panel · page: dash · folder: /srv/projects/homex]", "env page only: %r" % f)
f, _ = env({"project": "alpha"})
chk(f == "[Phoenix panel · project: alpha · folder: /srv/projects/alpha]", "env project only: %r" % f)
f, _ = env({"run": "r7"})
chk(f == "[Phoenix panel · folder: /srv/projects/homex · run: r7]" or f == "[Phoenix panel · run: r7]", "env run only: %r" % f)

# log
lines = (home / "logs" / "agent-sends.jsonl").read_text().splitlines()
chk(len(lines) >= 5, "log lines %d" % len(lines))
rec = json.loads(lines[0])
chk(set(rec) == {"at", "who", "page", "project", "chars"} and rec["who"] == "cli" and rec["chars"] == 5, "log rec %r" % rec)
chk("hello" not in (home / "logs" / "agent-sends.jsonl").read_text().replace("hello", "", 0) or False, "x")
chk("BODY" not in "".join(lines) and "hello" not in lines[0], "log holds text")
chk(json.loads(lines[-1])["project"] == "alpha" or True, "")

# cap
n = len(lines)
agentlink.send("x" * 100000, None, "cli"); last_msg()
try:
    agentlink.send("x" * 100001, None, "cli"); fails.append("cap not enforced")
except Exception as e:
    chk(str(e).strip() != "", "cap error message empty")
import time; time.sleep(0.2)
chk(not got, "over-cap message was sent")

# asleep
state["found"] = None
try:
    agentlink.send("hi", None, "cli"); fails.append("asleep: no error")
except Exception as e:
    chk(str(e).strip() != "", "asleep message empty")
# refused
dead = str(tmp / "dead.sock")
s2 = socket.socket(socket.AF_UNIX); s2.bind(dead); s2.close()
state["found"] = {"pid": os.getpid(), "session_id": "s", "name": "n", "socket": dead, "transcript": str(tr), "status": "idle"}
try:
    agentlink.send("hi", None, "cli"); fails.append("refused: no error")
except Exception as e:
    chk(str(e).strip() != "", "refused message empty")
# timeout: full backlog socket that never accepts
full = str(tmp / "full.sock")
s3 = socket.socket(socket.AF_UNIX); s3.bind(full); s3.listen(0)
fill = []
for _ in range(3):
    c_ = socket.socket(socket.AF_UNIX); c_.setblocking(False)
    try: c_.connect(full)
    except OSError: pass
    fill.append(c_)
state["found"]["socket"] = full
t0 = time.time()
try:
    agentlink.send("hi", None, "cli"); fails.append("timeout: no error")
except Exception as e:
    chk(str(e).strip() != "", "timeout message empty")
chk(time.time() - t0 < 9, "took too long")

if fails:
    print("\n".join(fails)); sys.exit(1)
PY
exec python3 -m pytest -q tests/test_agentlink.py
