#!/bin/sh
# python3 -m pytest -q tests/test_adapters.py tests/test_global_settings.py
cd "$(dirname "$0")/../../.." || exit 1
python3 - <<'PY' || exit 1
import os, sys, tempfile, pathlib, os.path
sys.path.insert(0, ".")
sys.path.insert(0, "tests")
from phoenix9 import adapters, settings
from fakes import FakeHost
fails = []
def chk(c, m):
    if not c: fails.append(m)

d = pathlib.Path(tempfile.mkdtemp())
(d / "b.txt").write_text("one\ntwo\n")
(d / "sub").mkdir()
h = adapters.Host()
chk(sorted(h.list_dir(d)) == ["b.txt", "sub"], "Host.list_dir")
chk(h.list_dir(d / "nope") == [], "Host.list_dir missing")
chk(h.exists(d / "b.txt") is True and h.exists(d / "nope") is False, "Host.exists")
chk(h.pid_alive(os.getpid()) is True, "Host.pid_alive self")
chk(h.pid_alive(99999999) is False, "Host.pid_alive dead")
st = h.stat(d / "b.txt")
chk(isinstance(st, dict) and st.get("uid") == os.getuid() and "mode" in st, "Host.stat %r" % (st,))
chk(h.stat(d / "nope") is None, "Host.stat missing")
chk([l.rstrip("\n") for l in h.read_lines(d / "b.txt")] == ["one", "two"], "Host.read_lines")
chk(h.read_lines(d / "nope") == [], "Host.read_lines missing")

f = FakeHost()
for a in ("dirs", "pids", "stats", "files"):
    chk(hasattr(f, a), "FakeHost." + a)
f.files["/x/a.txt"] = "l1\nl2\n"
chk([l.rstrip("\n") for l in f.read_lines("/x/a.txt")] == ["l1", "l2"], "Fake.read_lines")
chk(f.read_lines("/x/none") == [], "Fake.read_lines missing")
chk(f.exists("/x/a.txt") is True and f.exists("/x/none") is False, "Fake.exists")
chk(f.list_dir("/nowhere") == [], "Fake.list_dir missing")
chk(f.stat("/x/none") is None, "Fake.stat missing")
chk(f.pid_alive(4242) is False, "Fake.pid_alive default")
try:
    f.dirs["/x/d"] = ["p", "q"]
    chk(sorted(f.list_dir("/x/d")) == ["p", "q"], "Fake.list_dir")
    chk(f.exists("/x/d") is True, "Fake.exists dir")
    f.pids.add(4242) if hasattr(f.pids, "add") else f.pids.append(4242)
    chk(f.pid_alive(4242) is True, "Fake.pid_alive set")
    f.stats["/x/a.txt"] = {"mode": 0o600, "uid": 0}
    chk(f.stat("/x/a.txt") == {"mode": 0o600, "uid": 0}, "Fake.stat")
except Exception as e:
    fails.append("FakeHost fields misbehave: %r" % (e,))

home = pathlib.Path(tempfile.mkdtemp())
os.environ["PHOENIX_HOME"] = str(home)
(home / "config").mkdir()
g = home / "config" / "global.toml"
dflt = {"folder": "/srv/projects/home", "unit": "claude-rc@home", "watchdog": True}
chk(settings.agent_settings() == dflt, "defaults (no file): %r" % (settings.agent_settings(),))
g.write_text('[agent]\nfolder = "/tmp/x"\nunit = "u@y"\nwatchdog = false\n')
chk(settings.agent_settings() == {"folder": "/tmp/x", "unit": "u@y", "watchdog": False}, "overrides")
g.write_text('[agent]\nfolder = 5\nunit = ""\nwatchdog = "no"\n')
chk(settings.agent_settings() == dflt, "broken values: %r" % (settings.agent_settings(),))
g.write_text('agent = "oops"\n')
chk(settings.agent_settings() == dflt, "agent not a table")

if fails:
    print("\n".join(fails)); sys.exit(1)
PY
exec python3 -m pytest -q tests/test_adapters.py tests/test_global_settings.py
