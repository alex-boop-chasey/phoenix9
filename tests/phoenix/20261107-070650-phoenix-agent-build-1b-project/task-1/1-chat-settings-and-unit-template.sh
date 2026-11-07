#!/bin/sh
# python3 -m pytest -q tests/test_global_settings.py tests/test_install_sh.py
# Behaviour check: [chat] settings, the unit template, and install.sh installing it without enabling an instance.
set -u
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$ROOT" || exit 1
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

# the existing tests must still pass (the builder adds the chat ones to them)
python3 -m pytest -q tests/test_global_settings.py tests/test_install_sh.py >"$TMP/pytest.out" 2>&1 \
    || { tail -30 "$TMP/pytest.out"; fail "pytest on settings and install tests"; }

# ---- settings
cat >"$TMP/settings_check.py" <<'PY'
import os, sys
from pathlib import Path
sys.path.insert(0, os.getcwd())
from phoenix9 import settings

home = Path(os.environ["PHOENIX_HOME"])
(home / "config").mkdir(parents=True, exist_ok=True)
gl = home / "config" / "global.toml"

def put(text):
    gl.write_text(text)

want = {"sleep_after_minutes": 120, "off_after_days": 3, "start_wait_seconds": 60,
        "wrap_up_minutes": 3, "claude_home": "/root/.claude"}
put("")
got = settings.chat_settings()
assert got == want, f"defaults: {got!r}"

put('[chat]\nsleep_after_minutes = 30\noff_after_days = 7\nstart_wait_seconds = 15\n'
    'wrap_up_minutes = 1\nclaude_home = "/tmp/ch"\n')
got = settings.chat_settings()
assert got == {"sleep_after_minutes": 30, "off_after_days": 7, "start_wait_seconds": 15,
               "wrap_up_minutes": 1, "claude_home": "/tmp/ch"}, f"overrides: {got!r}"

bad = [("sleep_after_minutes", '"soon"'), ("sleep_after_minutes", "-5"), ("off_after_days", '"x"'),
       ("off_after_days", "-1"), ("start_wait_seconds", '"x"'), ("wrap_up_minutes", '"x"'),
       ("claude_home", "5"), ("sleep_after_minutes", "true")]
for key, val in bad:
    put(f"[chat]\n{key} = {val}\n")
    try:
        got = settings.chat_settings()
    except Exception:
        continue    # refused loudly
    assert got[key] == want[key], f"bad {key}={val} was accepted: {got[key]!r}"
print("settings ok")
PY
mkdir -p "$TMP/phome"
PHOENIX_HOME="$TMP/phome" python3 -I "$TMP/settings_check.py" || fail "chat settings"

# ---- unit template
T=deploy/claude-rc-chat@.service
[ -f "$T" ] || fail "$T missing"
grep -q '^WorkingDirectory=/srv/projects/%i[[:space:]]*$' "$T" || fail "WorkingDirectory"
EXEC="$(grep '^ExecStart=' "$T")"
[ -n "$EXEC" ] || fail "no ExecStart"
for w in "claude" "remote-control" "--name %i" "--spawn same-dir" "--capacity 3" \
         "--create-session-in-dir" "--permission-mode bypassPermissions"; do
    case "$EXEC" in *"$w"*) ;; *) fail "ExecStart lacks: $w";; esac
done
grep -q -- '--bare' "$T" && fail "template uses --bare"
grep -Eq '^Restart=(on-failure|always|on-abnormal)' "$T" || fail "Restart not set"
grep -Eiq 'TOKEN=|KEY=|SECRET|PASSWORD' "$T" && fail "template looks like it carries a secret"

# ---- install.sh copies it and enables no instance
O="$TMP/origin"; mkdir -p "$O/work"
git ls-files -co --exclude-standard -z | while IFS= read -r -d '' f; do
    [ -f "$f" ] && [ ! -L "$f" ] && { mkdir -p "$O/work/$(dirname "$f")"; cp -p "$f" "$O/work/$f"; }
done 2>/dev/null
if ! [ -f "$O/work/$T" ]; then
    # POSIX sh has no read -d; fall back to python copy
    python3 -I - "$ROOT" "$O/work" <<'PY'
import shutil, subprocess, sys
from pathlib import Path
root, dest = Path(sys.argv[1]), Path(sys.argv[2])
out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=root,
                     capture_output=True, text=True, check=True).stdout.split("\0")
for n in filter(None, out):
    s = root / n
    if s.is_file() and not s.is_symlink():
        (dest / n).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, dest / n)
PY
fi
G="git -c user.name=t -c user.email=t@example.com"
( cd "$O/work" && git init -q -b main && git add -A && $G commit -q -m r && git tag v9.0 ) >/dev/null 2>&1 || fail "temp origin"
git clone -q --bare "$O/work" "$O/origin.git" || fail "bare clone"

mkdir -p "$TMP/tools" "$TMP/units" "$TMP/v8"
printf '#!/bin/sh\necho "$@" >> %s\n' "$TMP/systemctl.log" >"$TMP/tools/systemctl"
printf '#!/bin/sh\nexit 0\n' >"$TMP/tools/gh"; cp "$TMP/tools/gh" "$TMP/tools/pnpm"
printf '#!/bin/sh\necho "Status: inactive"\n' >"$TMP/tools/ufw"
chmod 755 "$TMP"/tools/*
echo "CLAUDE_CODE_OAUTH_TOKEN=x" >"$TMP/v8/claude.env"; echo "TELEGRAM_TOKEN=x" >"$TMP/tg.env"
: >"$TMP/systemctl.log"
PATH="$TMP/tools:$PATH" PHOENIX_INSTALL="$TMP/opt" PHOENIX_HOME="$TMP/ihome" \
PHOENIX_SYSTEMD_DIR="$TMP/units" PHOENIX_SYSTEMCTL="$TMP/tools/systemctl" \
PHOENIX_BIN_LINK="$TMP/phoenix-link" PHOENIX_INSTALL_ALLOW_NONROOT=1 \
    bash deploy/install.sh --tag v9.0 --repo "$O/origin.git" --v8-config "$TMP/v8" \
    --telegram-env "$TMP/tg.env" --skip-checks --skip-web </dev/null >"$TMP/install.out" 2>&1 \
    || { tail -20 "$TMP/install.out"; fail "install.sh failed"; }

U="$TMP/units/claude-rc-chat@.service"
[ -f "$U" ] && [ ! -L "$U" ] || fail "template not copied into PHOENIX_SYSTEMD_DIR"
cmp -s "$U" "$T" || fail "installed template differs from deploy/ copy"
if grep -q 'claude-rc-chat' "$TMP/systemctl.log"; then
    fail "install.sh touched a chat instance: $(grep claude-rc-chat "$TMP/systemctl.log")"
fi
grep -Eq 'claude-rc@' "$TMP/systemctl.log" && fail "install.sh touched claude-rc instances"
echo "OK"
