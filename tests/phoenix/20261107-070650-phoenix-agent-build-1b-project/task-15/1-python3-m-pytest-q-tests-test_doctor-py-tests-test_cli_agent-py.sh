#!/bin/sh
# python3 -m pytest -q tests/test_doctor.py tests/test_cli_agent.py
# Behaviour check: doctor's "Project chats" check lists each chat unit with its state and warns about failed units or unreadable chat documents.
set -u
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$ROOT" || exit 1
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

python3 -m pytest -q tests/test_doctor.py tests/test_cli_agent.py >"$TMP/pytest.out" 2>&1 \
    || { tail -30 "$TMP/pytest.out"; fail "pytest on doctor and agent cli tests"; }
grep -qi 'chat' tests/test_doctor.py || fail "tests/test_doctor.py has no chat tests"

cat >"$TMP/check.py" <<'PY'
import json, os, sys
from pathlib import Path
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "tests"))
from phoenix9 import agentlink, doctor, paths, projectchat as pc
from tests.fakes import FakeHost, fake_adapters

root = Path(os.environ["PHOENIX_PROJECTS"])
HOME = "/root/.claude"
SID = "0feb0729-478d-4dc7-879a-b3fe804f3466"
T0 = 1_800_000_000.0
NAMES = ["alpha", "beta", "gamma", "delta"]
for n in NAMES:
    (root / n).mkdir()
    (root / n / "CLAUDE.md").write_text("x")


class Host(FakeHost):
    """Per-project chat unit states."""
    def __init__(self, units):
        super().__init__()
        self.units = units
        self.mains = {n: 100 + i for i, n in enumerate(NAMES)}

    def systemctl(self, *args):
        self.calls.append(["systemctl", *args])
        unit = args[-1]
        if unit.startswith("claude-rc-chat@"):
            n = unit.split("@", 1)[1]
            st = self.units.get(n, "inactive")
            if args[0] == "is-active":
                return (0 if st == "active" else 3), st + "\n", ""
            if args[0] == "show":
                return 0, ("%d\n" % self.mains[n] if st == "active" else "0\n"), ""
        if args[0] == "is-active":
            return 0, "active\n", ""
        return 0, "", ""

    def session(self, n, status):
        i = NAMES.index(n)
        sock = "/tmp/cc-socks-0/%s.sock" % n
        pid = 10 + i
        self.files["%s/sessions/%d.json" % (HOME, pid)] = json.dumps(
            {"pid": pid, "cwd": str(root / n), "name": n, "status": status, "messagingSocketPath": sock,
             "kind": "interactive", "sessionId": SID, "startedAt": 1, "bridgeSessionId": "session_B%d" % i})
        self.files[sock] = ""
        self.pids |= {pid, self.mains[n]}
        self.parents[pid] = self.mains[n]


def chat_check(units, docs, sessions, tmp):
    agentlink.forget()
    for n in NAMES:
        d = root / n / ".phoenix" / "chat.md"
        if d.exists():
            d.unlink()
    host = Host(units)
    for n, status in sessions.items():
        host.session(n, status)
    for n, mode in docs.items():
        if mode == "good":
            pc.write_chat_doc(n, pc.build_fields(n, "session_D" + n, SID, T0, T0))
        else:
            (root / n / ".phoenix").mkdir(exist_ok=True)
            (root / n / ".phoenix" / "chat.md").write_text("garbage\x00")
    ad = fake_adapters(tmp)
    ad.host = host
    assert "full" in doctor.CHECKS_BY_MODE and any(
        "chat" in c and "agent" not in c for c in doctor.CHECKS_BY_MODE["full"]), "full mode lacks a chat check"
    data = doctor.run_checks(ad, "full")
    found = [c for c in data["checks"] if "chat" in c["name"] and "agent" not in c["name"]]
    assert len(found) == 1, [c["name"] for c in data["checks"]]
    c = found[0]
    assert "itself failed" not in c["detail"], c
    return c, doctor.render(data)


def has_line(text, name, word):
    return any(name in ln and word in ln.lower() for ln in text.splitlines())


tmp = Path(sys.argv[1])
# 1. all four states, plus a project with no chat yet: listed, and never a failure
c, rendered = chat_check({"beta": "active", "gamma": "active", "delta": "active"},
                         {"beta": "good", "gamma": "good", "delta": "good"},
                         {"gamma": "idle", "delta": "busy"}, tmp)
text = c["detail"]
for name, word in [("alpha", "off"), ("beta", "sleeping"), ("gamma", "live"), ("delta", "working")]:
    assert has_line(text, name, word), (name, word, text)
assert c["ok"] is True, c
assert "chat off" not in (c["detail"] + c["fix"]), c
assert "chat" in rendered.lower()

# 2. a failed unit warns and names the fix
c, _ = chat_check({"beta": "failed", "gamma": "active"}, {"gamma": "good"}, {}, tmp)
text = c["detail"] + "\n" + c["fix"]
assert "beta" in text and "phoenix chat off beta --yes" in text, text
assert "phoenix chat off gamma" not in text and "phoenix chat off alpha" not in text, text

# 3. an unreadable chat document warns and names the fix
c, _ = chat_check({"gamma": "active"}, {"gamma": "bad"}, {}, tmp)
text = c["detail"] + "\n" + c["fix"]
assert "gamma" in text and "phoenix chat off gamma --yes" in text, text
assert "phoenix chat off alpha" not in text, text
print("OK")
PY
mkdir -p "$TMP/phome" "$TMP/projects" "$TMP/t"
PHOENIX_HOME="$TMP/phome" PHOENIX_PROJECTS="$TMP/projects" python3 -I "$TMP/check.py" "$TMP/t" || fail "doctor project chats behaviour"
