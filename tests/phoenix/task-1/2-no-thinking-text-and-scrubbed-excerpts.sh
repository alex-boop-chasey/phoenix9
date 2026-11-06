#!/bin/sh
# thinking text never appears in any item; every excerpt is scrubbed
cd "$(dirname "$0")/../../.." || exit 1
exec python3 - <<'PY'
import json, sys
sys.path.insert(0, ".")
from phoenix9 import transcript, scrub

SECRET = "sk-test-Zq8vN3pL7xR2mK9d"
THINK = "pondering-the-hidden-plan-xyzzy-42"
scrub.add_secrets([SECRET])
L = [
 {"type": "user", "message": {"role": "user", "content": "hello"}, "timestamp": "2026-11-06T10:00:00Z", "sessionId": "s1"},
 {"type": "assistant", "message": {"content": [
    {"type": "thinking", "thinking": THINK},
    {"type": "text", "text": "running it"},
    {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "cat .env\necho more"}}]},
  "timestamp": "2026-11-06T10:00:01Z", "sessionId": "s1"},
 {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1",
    "content": "line1\nTOKEN=" + SECRET + "\nline3\nline4\nline5\nline6\nline7 " + SECRET, "is_error": False}]},
  "timestamp": "2026-11-06T10:00:02Z", "sessionId": "s1"},
 {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": THINK + " again"}]}, "sessionId": "s2"},
 {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/a/b.txt"}}]}, "sessionId": "s2"},
 {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t2",
    "content": [{"type": "text", "text": "x " + SECRET}], "is_error": True}]}, "sessionId": "s2"},
]
lines = [json.dumps(x) for x in L]
lines.insert(2, "{broken json")
items, unknown = transcript.parse(lines)
dump = json.dumps(items, default=lambda o: getattr(o, "__dict__", str(o)))
fails = []
if "pondering-the-hidden-plan" in dump:
    fails.append("thinking text leaked into an item")
if SECRET in dump:
    fails.append("secret value leaked into an item")
if not isinstance(unknown, int) or unknown < 1:
    fails.append("broken line not counted: %r" % (unknown,))
ex = [i for i in items if isinstance(i, dict) and "excerpt" in i]
if len(ex) < 2:
    fails.append("expected 2 actions with excerpt, got %d" % len(ex))
for i in ex:
    if SECRET in str(i["excerpt"]):
        fails.append("excerpt not scrubbed")
if ex and "[secret]" not in str(ex[0]["excerpt"]):
    fails.append("excerpt lacks [secret] mask")
if ex and len(str(ex[0]["excerpt"]).splitlines()) > 6:
    fails.append("excerpt longer than 6 lines")
if fails:
    print("\n".join(fails)); sys.exit(1)
print("ok")
PY
