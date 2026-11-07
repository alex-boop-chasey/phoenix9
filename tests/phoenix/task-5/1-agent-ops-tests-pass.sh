#!/bin/sh
# python3 -m pytest -q tests/test_ops_agent.py
cd "$(dirname "$0")/../../.." || exit 1
test -f tests/test_ops_agent.py || { echo "tests/test_ops_agent.py missing"; exit 1; }
test -f phoenix9/ops/agent.py || { echo "phoenix9/ops/agent.py missing"; exit 1; }
python3 - <<'PY' || exit 1
import json, os, sys, tempfile, pathlib, types
sys.path.insert(0, ".")
sys.path.insert(0, "tests")
tmp = pathlib.Path(tempfile.mkdtemp(prefix="p5"))
os.environ["PHOENIX_HOME"] = str(tmp / "home")
os.environ["PHOENIX_PROJECTS"] = str(tmp / "projects")
(tmp / "home").mkdir(); (tmp / "projects").mkdir()
from phoenix9 import agentlink, events, paths
from phoenix9.ops import common, agent
from fakes import FakeHost

fails = []
def chk(c, m):
    if not c: fails.append(m)

for n in ("status", "messages", "send", "sessions"):
    if not callable(getattr(agent, n, None)):
        print("ops.agent.%s missing" % n); sys.exit(1)

host = FakeHost()
common.make_adapters = lambda: types.SimpleNamespace(host=host)

CH = "/root/.claude"
TDIR = CH + "/projects/-srv-projects-home"
def line(o): return json.dumps(o)
T = [
 line({"type": "user", "message": {"role": "user", "content": "hello there"}, "timestamp": "2026-11-06T10:00:00Z", "sessionId": "s1"}),
 line({"type": "assistant", "message": {"content": [{"type": "text", "text": "first answer"}]}, "timestamp": "2026-11-06T10:00:01Z", "sessionId": "s1"}),
 "{broken json",
 line({"type": "user", "message": {"role": "user", "content": "second question"}, "timestamp": "2026-11-06T10:00:02Z", "sessionId": "s1"}),
 line({"type": "assistant", "message": {"content": [{"type": "text", "text": "second answer"}]}, "timestamp": "2026-11-06T10:00:03Z", "sessionId": "s1"}),
 line({"type": "assistant", "message": {"content": [{"type": "text", "text": "third answer"}]}, "timestamp": "2026-11-06T10:00:04Z", "sessionId": "s1"}),
]
OLD = [
 line({"type": "user", "message": {"role": "user", "content": "old"}, "timestamp": "2026-11-01T09:00:00Z", "sessionId": "s0"}),
 line({"type": "assistant", "message": {"content": [{"type": "text", "text": "old a"}]}, "timestamp": "2026-11-01T09:00:01Z", "sessionId": "s0"}),
]
def asleep():
    host.files.clear(); host.dirs.clear(); host.pids.clear(); host.stats.clear()

def awake():
    asleep()
    host.files[CH + "/sessions/100.json"] = json.dumps({"pid": 100, "cwd": "/srv/projects/home",
        "name": "Phoenix agent", "status": "idle", "messagingSocketPath": "/tmp/cc-socks-0/x.sock",
        "kind": "interactive", "sessionId": "s1", "extra": 1})
    host.files["/tmp/cc-socks-0/x.sock"] = ""
    host.pids.add(100)
    host.files[TDIR + "/s1.jsonl"] = "\n".join(T) + "\n"
    host.files[TDIR + "/s0.jsonl"] = "\n".join(OLD) + "\n"
    host.stats[TDIR + "/s1.jsonl"] = {"mode": 0o600, "uid": 0, "mtime": 2000}
    host.stats[TDIR + "/s0.jsonl"] = {"mode": 0o600, "uid": 0, "mtime": 1000}

def items_of(r):
    if isinstance(r, dict):
        v = r.get("items")
        return v if isinstance(v, list) else []
    return []

try:
    # asleep
    asleep()
    s = agent.status()
    chk(isinstance(s, dict) and s.get("state") == "asleep", "status asleep: %r" % (s,))
    r = agent.messages(0, 50)
    chk(isinstance(r, dict) and items_of(r) == [], "messages asleep: %r" % (r,))
    chk(agent.sessions() == [], "sessions asleep: %r" % (agent.sessions(),))

    awake()
    s = agent.status()
    chk(s.get("state") == "idle" and s.get("pid") == 100 and s.get("session_id") == "s1", "status: %r" % (s,))

    r = agent.messages(0, 100)
    its = items_of(r)
    chk(len(its) >= 5, "messages items: %r" % (r,))
    chk(r.get("unknown") == 1, "unknown: %r" % (r.get("unknown"),))
    chk(r.get("last_line") == 6, "last_line: %r" % (r.get("last_line"),))
    chk(r.get("session_id") == "s1", "session_id: %r" % (r.get("session_id"),))
    chk(all(isinstance(i.get("line"), int) for i in its), "items lack line")
    lines_all = [i["line"] for i in its]
    chk(lines_all == sorted(lines_all), "items not in line order")
    r2 = agent.messages(3, 100)
    its2 = items_of(r2)
    chk(its2 and all(i["line"] > 3 for i in its2), "after=3 not honoured: %r" % ([i.get("line") for i in its2],))
    chk([i["line"] for i in its2] == [l for l in lines_all if l > 3], "after=3 wrong set")
    r3 = agent.messages(0, 2)
    chk([i["line"] for i in items_of(r3)] == lines_all[:2], "limit=2 should give first 2 items")
    r4 = agent.messages(6, 100)
    chk(items_of(r4) == [] and r4.get("last_line") == 6, "after=last: %r" % (r4,))

    ss = agent.sessions()
    chk(isinstance(ss, list) and len(ss) == 2, "sessions: %r" % (ss,))
    if isinstance(ss, list) and len(ss) == 2:
        chk([x.get("session_id") for x in ss] == ["s1", "s0"], "sessions order: %r" % (ss,))
        chk(ss[0].get("lines") == 6 and ss[1].get("lines") == 2, "sessions lines: %r" % (ss,))
        chk(all(x.get("started") for x in ss), "sessions started: %r" % (ss,))
        chk(all(set(x) >= {"session_id", "started", "lines"} for x in ss), "sessions keys")

    # send
    calls = []
    def fake_send(text, context=None, who="cli", *a, **k):
        calls.append((text, context, who))
        return {"sent": True, "at": "2026-11-06T10:00:00Z", "after_line": 6}
    agentlink.send = fake_send
    res = agent.send("do the thing", {"page": "dash"}, "alex")
    chk(res == {"sent": True, "at": "2026-11-06T10:00:00Z", "after_line": 6}, "send result %r" % (res,))
    chk(calls and calls[0][0] == "do the thing" and calls[0][1] == {"page": "dash"} and calls[0][2] == "alex", "send args %r" % (calls,))
    evs = [e for e in events.read(paths.events()) if e.get("type") == "command"]
    chk(len(evs) == 1 and "alex" in json.dumps(evs[0].get("data")), "command event: %r" % (evs,))

    def bad_send(*a, **k):
        raise agentlink.SendError("The Phoenix agent is asleep, nothing sent.")
    agentlink.send = bad_send
    try:
        agent.send("x", None, "cli"); fails.append("send error not raised")
    except common.OpsError as e:
        chk("asleep" in str(e), "reason lost: %r" % (str(e),))
    except Exception as e:
        fails.append("wrong error type %r" % (e,))
except Exception as e:
    import traceback; traceback.print_exc()
    fails.append("exception: %r" % (e,))

if fails:
    print("\n".join(fails)); sys.exit(1)
PY
exec python3 -m pytest -q tests/test_ops_agent.py
