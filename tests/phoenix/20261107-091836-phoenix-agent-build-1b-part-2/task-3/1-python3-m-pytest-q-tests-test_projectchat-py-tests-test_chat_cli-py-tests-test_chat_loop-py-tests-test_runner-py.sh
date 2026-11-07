#!/bin/sh
# python3 -m pytest -q tests/test_projectchat.py tests/test_chat_cli.py tests/test_chat_loop.py tests/test_runner.py
# Behaviour check: watch.check_chats puts idle live chats to sleep, turns old sleeping chats off, skips working chats, busy projects and home, keeps 10-minute spacing and survives errors.
set -u
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$ROOT" || exit 1
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

[ -f tests/test_chat_loop.py ] || fail "tests/test_chat_loop.py missing"
python3 -m pytest -q tests/test_projectchat.py tests/test_chat_cli.py tests/test_chat_loop.py tests/test_runner.py >"$TMP/pytest.out" 2>&1 \
    || { tail -30 "$TMP/pytest.out"; fail "pytest on chat and runner tests"; }

cat >"$TMP/check.py" <<'PY'
import json, os, shutil, sys, time
from pathlib import Path
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "tests"))
from phoenix9 import adapters as adapters_mod, agentlink, atomic, events, paths, projectchat as pc, state, watch
from fakes import FakeHost, FakeClock, fake_adapters

root = Path(os.environ["PHOENIX_PROJECTS"])
phome = Path(os.environ["PHOENIX_HOME"])
HOME = "/root/.claude"
SID = "0feb0729-478d-4dc7-879a-b3fe804f3466"
BR = "session_AAA-1_x"
T = time.time()
MIN, DAY = 60.0, 86400.0


class Host(FakeHost):
    """A host with several chat units; each project has a scripted kind of chat."""
    def __init__(self):
        super().__init__()
        self.units = {}
        self.raise_for = set()

    def add(self, name, i, kind):
        folder = str(root / name)
        if kind == "off":
            self.units[name] = "inactive"
            return
        self.units[name] = "active"
        self.main = getattr(self, "main", {})
        self.main[name] = 100 + i
        if kind in ("live", "working"):
            sock = "/tmp/cc-socks-0/%s.sock" % name
            data = {"pid": 10 + i, "cwd": folder, "name": name,
                    "status": "busy" if kind == "working" else "idle", "messagingSocketPath": sock,
                    "kind": "interactive", "sessionId": SID, "startedAt": 1, "bridgeSessionId": BR}
            self.files["%s/sessions/%d.json" % (HOME, 10 + i)] = json.dumps(data)
            self.files[sock] = ""
            self.pids.update({100 + i, 10 + i})
            self.parents[10 + i] = 100 + i
        else:
            self.pids.add(100 + i)

    def systemctl(self, *args):
        self.calls.append(["systemctl", *args])
        unit = args[-1]
        name = unit.split("@", 1)[1].split(".")[0] if "@" in unit else ""
        if name in self.raise_for:
            raise RuntimeError("systemctl exploded for " + name)
        if args[0] == "is-active":
            u = self.units.get(name, "inactive")
            return (0 if u == "active" else 3), u + "\n", ""
        if args[0] == "show":
            return 0, "%d\n" % getattr(self, "main", {}).get(name, 0), ""
        if args[0] == "disable":
            self.units[name] = "inactive"
        return 0, "", ""

    def disabled(self):
        return [c[-1] for c in self.calls if c[:2] == ["systemctl", "disable"]]


sent = []
def fake_send_to(found, text, context=None, who="cli", timeout=5.0, host=None):
    sent.append({"found": found, "text": text, "context": context})
    return {"sent": True, "at": "x", "after_line": 0}
agentlink.send_to = fake_send_to


def reset(config=""):
    for sub in (root, paths.runs()):
        if sub.exists():
            shutil.rmtree(sub)
        sub.mkdir(parents=True)
    if paths.events().exists():
        paths.events().unlink()
    cfg = phome / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "global.toml").write_text(config)
    agentlink.forget()
    sent.clear()


def setup(specs, config="", bad=()):
    """specs: name -> (kind, minutes since last active). Returns fresh adapters."""
    reset(config)
    h = Host()
    for i, (name, (kind, mins)) in enumerate(sorted(specs.items())):
        folder = root / name
        folder.mkdir()
        (folder / "CLAUDE.md").write_text("x")
        if kind != "none":
            pc.write_chat_doc(name, pc.build_fields(name, BR, SID, T - 10 * DAY, T - mins * MIN))
        h.add(name, i + 1, "off" if kind == "off" else kind)
    h.raise_for = set(bad)
    a = fake_adapters(str(phome))
    a.host, a.clock = h, FakeClock(T)
    adapters_mod.real = lambda: a
    return a


def add_run(project, status, run_id="r1"):
    s = state.new_state(run_id, project)
    s["status"] = status
    atomic.write_json(paths.runs(project) / run_id / "state.json", s)


def slept(a, name):
    pid = 10 + sorted(a.host.units).index(name) + 1
    return pid in a.host.stopped


def runner_events(name):
    out = []
    for e in events.read(paths.events()):
        if e.get("project") == name and (e.get("data") or {}).get("who") == "runner":
            out.append(e)
    return out


assert hasattr(watch, 'check_chats'), 'watch.check_chats missing'
# 1. idle live chat (over the 120-minute default) is put to sleep with a wrap-up; unit stays
a = setup({"alpha": ("live", 130)})
watch.check_chats(a, watch.Memory())
assert slept(a, "alpha"), ("idle chat not stopped", a.host.stopped, a.host.calls)
assert a.host.disabled() == [], a.host.calls
assert len(sent) == 1 and "Wrap up" in sent[0]["text"], sent
assert runner_events("alpha"), "no event with who runner for the sleep"

# 2. recently active live chat is left alone
a = setup({"alpha": ("live", 60)})
watch.check_chats(a, watch.Memory())
assert a.host.stopped == [] and sent == [] and a.host.disabled() == [], (a.host.stopped, sent)
assert not runner_events("alpha")

# 3. the idle limit follows chat.sleep_after_minutes
a = setup({"alpha": ("live", 20)}, config="[chat]\nsleep_after_minutes = 10\n")
watch.check_chats(a, watch.Memory())
assert slept(a, "alpha"), "setting sleep_after_minutes = 10 ignored"
a = setup({"alpha": ("live", 200)}, config="[chat]\nsleep_after_minutes = 300\n")
watch.check_chats(a, watch.Memory())
assert a.host.stopped == [], "setting sleep_after_minutes = 300 ignored"

# 4. working chat is left alone even when old
a = setup({"alpha": ("working", 500)})
watch.check_chats(a, watch.Memory())
assert a.host.stopped == [] and sent == [] and a.host.disabled() == [], (a.host.stopped, sent, a.host.calls)
assert not runner_events("alpha")

# 5. sleeping chat older than 3 days is turned off; younger is not
a = setup({"alpha": ("sleeping", 4 * 24 * 60), "beta": ("sleeping", 2 * 24 * 60)})
watch.check_chats(a, watch.Memory())
assert a.host.disabled() == ["claude-rc-chat@alpha"] or [u.split(".")[0] for u in a.host.disabled()] == ["claude-rc-chat@alpha"], a.host.disabled()
assert a.host.units["alpha"] == "inactive" and a.host.units["beta"] == "active"
assert runner_events("alpha") and not runner_events("beta")
assert sent == [], sent
a = setup({"alpha": ("sleeping", 2 * 24 * 60)}, config="[chat]\noff_after_days = 1\n")
watch.check_chats(a, watch.Memory())
assert a.host.disabled(), "setting off_after_days = 1 ignored"

# 6. a chat that is off, or a project with no chat document, is not touched
a = setup({"alpha": ("off", 5000), "beta": ("none", 0)})
watch.check_chats(a, watch.Memory())
assert a.host.disabled() == [] and a.host.stopped == [] and sent == [], a.host.calls

# 7. projects with a queued, running, waiting or paused run are skipped; others still handled
for status in ("queued", "running", "waiting", "paused-limit"):
    a = setup({"alpha": ("live", 500), "beta": ("live", 500), "gamma": ("sleeping", 9 * 24 * 60)})
    add_run("alpha", status)
    add_run("gamma", status)
    watch.check_chats(a, watch.Memory())
    assert not slept(a, "alpha"), "project with a %s run was put to sleep" % status
    assert slept(a, "beta"), "other project not handled next to a %s run" % status
    assert a.host.units["gamma"] == "active" and a.host.disabled() == [], "project with a %s run turned off" % status
# an ended run does not block
a = setup({"alpha": ("live", 500)})
add_run("alpha", "done")
watch.check_chats(a, watch.Memory())
assert slept(a, "alpha"), "an ended run blocked the chat"

# 8. the agent's folder (home) is never touched
a = setup({"home": ("live", 900), "zeta": ("sleeping", 9 * 24 * 60), "alpha": ("live", 900)})
watch.check_chats(a, watch.Memory())
assert slept(a, "alpha")
assert not slept(a, "home"), "home was put to sleep"
assert a.host.disabled() == [] and not runner_events("home")
a = setup({"home": ("sleeping", 9 * 24 * 60)})
watch.check_chats(a, watch.Memory())
assert a.host.disabled() == [], "home was turned off"

# 9. spacing: about every 10 minutes, kept in Memory, on the fake clock
a = setup({"alpha": ("live", 500)})
mem = watch.Memory()
watch.check_chats(a, mem)
assert slept(a, "alpha")
a.host.stopped.clear()
a.host.add("alpha", 1, "live")
a.clock.t += 5 * MIN
watch.check_chats(a, mem)
assert a.host.stopped == [], "ran again after 5 minutes"
a.clock.t += 6 * MIN
watch.check_chats(a, mem)
assert a.host.stopped == [11], "did not run again after 11 minutes: %s" % a.host.stopped

# 10. an error in one project does not stop the others, and never escapes
for bad, good in (("aaa", "zzz"), ("zzz", "aaa")):
    a = setup({bad: ("live", 500), good: ("live", 500), "mmm": ("sleeping", 9 * 24 * 60)}, bad=[bad])
    watch.check_chats(a, watch.Memory())
    names = sorted(a.host.units)
    assert (10 + names.index(good) + 1) in a.host.stopped, ("good project skipped after error", bad, a.host.stopped)
    assert a.host.units["mmm"] == "inactive", "sleeping project not turned off after error in " + bad
a = setup({"aaa": ("live", 500), "bbb": ("sleeping", 9 * 24 * 60)}, bad=["aaa", "bbb"])
watch.check_chats(a, watch.Memory())
print("OK")
PY
mkdir -p "$TMP/phome" "$TMP/projects"
export PHOENIX_HOME="$TMP/phome" PHOENIX_PROJECTS="$TMP/projects" PHOENIX_INSTALL="$TMP/install"
export PHOENIX_NOTIFY_FILE="$TMP/notify.msg" PHOENIX_SYSTEMD_DIR="$TMP/systemd"
python3 -I "$TMP/check.py" || fail "check_chats behaviour"
