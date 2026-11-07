#!/bin/sh
# python3 -m pytest -q tests/test_agent_watch.py
cd "$(dirname "$0")/../../.." || exit 1
test -f tests/test_agent_watch.py || { echo "tests/test_agent_watch.py missing"; exit 1; }
test -f phoenix9/agentwatch.py || { echo "phoenix9/agentwatch.py missing"; exit 1; }
python3 - <<'PY' || exit 1
import json, os, sys, tempfile, pathlib, types
sys.path.insert(0, ".")
sys.path.insert(0, "tests")
tmp = pathlib.Path(tempfile.mkdtemp(prefix="p8"))
home = tmp / "home"
(home / "logs").mkdir(parents=True); (home / "config").mkdir()
os.environ["PHOENIX_HOME"] = str(home)
os.environ["PHOENIX_PROJECTS"] = str(tmp / "projects")
(tmp / "projects").mkdir()
(home / "config" / "global.toml").write_text('[agent]\nunit = "claude-rc@testhome"\nfolder = "/srv/projects/home"\n')
from phoenix9 import chat, agentwatch, agentlink
from fakes import FakeHost, FakeClock, FakeNotify

fails = []
def chk(c, m):
    if not c: fails.append(m)

for mod, n in ((chat, "agent_restart"), (agentwatch, "check_once")):
    if not callable(getattr(mod, n, None)):
        print("%s.%s missing" % (mod.__name__, n)); sys.exit(1)

UNIT = "claude-rc@testhome"
CH = "/root/.claude"
FOLDER = "/srv/projects/home"

def make():
    host = FakeHost(); clock = FakeClock(); notify = FakeNotify()
    return host, clock, notify, types.SimpleNamespace(host=host, clock=clock, notify=notify)

def healthy(host):
    host.files[CH + "/sessions/100.json"] = json.dumps({"pid": 100, "cwd": FOLDER, "name": "Phoenix agent",
        "status": "idle", "messagingSocketPath": "/tmp/cc-socks-0/x.sock", "kind": "interactive", "sessionId": "s1"})
    host.files["/tmp/cc-socks-0/x.sock"] = ""
    host.pids.add(100)
    host.files[agentlink.transcript_path(CH, FOLDER, "s1")] = '{"type":"user"}\n'
    host.script(["systemctl", "is-active"], 0, "active\n")

def sick(host):
    host.files.clear(); host.pids.clear()
    host.script(["systemctl", "is-active"], 3, "inactive\n")

def restarts(host):
    return [c for c in host.calls if c[:2] == ["systemctl", "restart"] and UNIT in c]

# agent_restart
host, clock, notify, ad = make()
try:
    chat.agent_restart(ad, "because")
except Exception as e:
    fails.append("agent_restart raised %r" % (e,))
chk(len(restarts(host)) == 1, "agent_restart: no systemctl restart %s: %r" % (UNIT, host.calls))

# healthy
host, clock, notify, ad = make(); healthy(host)
for _ in range(4):
    agentwatch.check_once(ad); clock.sleep(60)
chk(not restarts(host) and not notify.messages, "healthy: restarted or notified")

# one bad check, then healthy again
host, clock, notify, ad = make(); sick(host)
agentwatch.check_once(ad); clock.sleep(60)
chk(not restarts(host), "one bad check restarted")
healthy(host)
agentwatch.check_once(ad); clock.sleep(60)
sick(host)
agentwatch.check_once(ad); clock.sleep(60)
chk(not restarts(host), "non-consecutive bad checks restarted")

# two bad checks: one restart, one notify; back-off
host, clock, notify, ad = make(); sick(host)
agentwatch.check_once(ad); clock.sleep(60)
agentwatch.check_once(ad); clock.sleep(60)
chk(len(restarts(host)) == 1, "two bad checks: restarts=%d" % len(restarts(host)))
chk(len(notify.messages) == 1 and notify.messages[0].startswith("Phoenix agent restarted: ") and len(notify.messages[0]) > len("Phoenix agent restarted: "),
    "notify: %r" % (notify.messages,))
mem = home / "logs" / "agent-watch.json"
chk(mem.exists(), "agent-watch.json not written")
if mem.exists():
    try: json.loads(mem.read_text())
    except Exception: fails.append("agent-watch.json not json")
for _ in range(6):   # still inside 10 minutes
    agentwatch.check_once(ad); clock.sleep(60)
chk(len(restarts(host)) == 1 and len(notify.messages) == 1, "restarted again inside back-off")
clock.sleep(600)
for _ in range(4):
    agentwatch.check_once(ad); clock.sleep(60)
chk(len(restarts(host)) == 2 and len(notify.messages) == 2, "no second restart after back-off: %d" % len(restarts(host)))

# memory survives between calls (fresh process view): state only in the file
host2, clock2, notify2, ad2 = make(); sick(host2)
agentwatch.check_once(ad2)
mem_text = mem.read_text()
chk(isinstance(json.loads(mem_text), (dict, list)), "memory json shape")

# runner loop mentions the watchdog
src = pathlib.Path("phoenix9/watch.py").read_text()
chk("agentwatch" in src, "watch.py does not call agentwatch")
if fails:
    print("\n".join(fails)); sys.exit(1)
PY
exec python3 -m pytest -q tests/test_agent_watch.py
