#!/bin/sh
# python3 -m pytest -q tests/test_deploy_agent.py
cd "$(dirname "$0")/../../.." || exit 1
test -f tests/test_deploy_agent.py || { echo "tests/test_deploy_agent.py missing"; exit 1; }
python3 - <<'PY' || exit 1
import json, re, sys, pathlib
fails = []
def chk(c, m):
    if not c: fails.append(m)

d = pathlib.Path("deploy/agent")
for n in ("CLAUDE.md", "settings.json", "agents/navigator.md", "agents/editor.md", "agents/checker.md"):
    chk((d / n).is_file(), "deploy/agent/%s missing" % n)
if fails:
    print("\n".join(fails)); sys.exit(1)

def strings(o):
    if isinstance(o, str): yield o
    elif isinstance(o, dict):
        for v in o.values(): yield from strings(v)
    elif isinstance(o, list):
        for v in o: yield from strings(v)

try:
    s = json.loads((d / "settings.json").read_text())
except Exception as e:
    print("settings.json does not parse: %r" % (e,)); sys.exit(1)
chk(s.get("model") == "claude-sonnet-5-5", "settings model: %r" % (s.get("model"),))
ss = (s.get("hooks") or {}).get("SessionStart")
chk(ss is not None, "no hooks.SessionStart")
cmds = [x.strip() for x in strings(ss)]
chk("/opt/phoenix9/bin/phoenix agent brief" in cmds, "hook command wrong: %r" % (cmds,))

def front(p):
    t = p.read_text()
    m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n", t, re.S)
    if not m: return None
    out = {}
    for ln in m.group(1).splitlines():
        k, sep, v = ln.partition(":")
        if sep: out[k.strip()] = v.strip().strip("'\"")
    return out
for name, model in (("navigator", "claude-haiku-5-5"), ("editor", "claude-sonnet-5-5"), ("checker", "claude-haiku-5-5")):
    f = front(d / "agents" / (name + ".md"))
    if f is None:
        fails.append("%s.md has no front matter" % name); continue
    chk(f.get("name"), "%s: no name" % name)
    chk(f.get("description"), "%s: no description" % name)
    chk(f.get("model") == model, "%s: model %r" % (name, f.get("model")))
nav = front(d / "agents" / "navigator.md") or {}
chk("Read" in nav.get("tools", "") and "Bash" in nav.get("tools", ""), "navigator tools: %r" % (nav.get("tools"),))

c = (d / "CLAUDE.md").read_text()
for w in ("Phoenix agent", "/srv/projects/home", "Agent panel", "Planning session", "Build", "Step",
          "Task", "Quick edit", "Helper", "folder:", "notes/NOW.md", "Alex (Phoenix panel)",
          "[Phoenix panel", "changelog", "/clear", "phoenix"):
    chk(w in c, "CLAUDE.md lacks %r" % w)

r = pathlib.Path("deploy/README.md").read_text()
chk("deploy/agent" in r or "agent/" in r, "deploy/README.md does not mention the agent folder")

if fails:
    print("\n".join(fails)); sys.exit(1)
PY
exec python3 -m pytest -q tests/test_deploy_agent.py
