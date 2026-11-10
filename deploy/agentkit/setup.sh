#!/bin/sh
# One-time (and safe to repeat) setup of the Phoenix agent service. Run as root after the merge.
# It never creates or touches the API key, and never prints the token.
set -eu

HOME_DIR="${PHOENIX_HOME:-/var/lib/phoenix9}"
AGENT_DIR="$HOME_DIR/agentkit"
CODE_DIR="${PHOENIX_INSTALL:-/opt/phoenix9}/agentkit"
GLOBAL="$HOME_DIR/config/global.toml"
USER_NAME=phoenix-agentkit

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this as root." >&2
  exit 1
fi
if [ ! -f "$CODE_DIR/requirements.lock" ]; then
  echo "The agent code is not installed at $CODE_DIR yet. Run the updater first." >&2
  exit 1
fi

# The system user (no login shell) and its folder.
if ! id "$USER_NAME" >/dev/null 2>&1; then
  useradd --system --home-dir "$AGENT_DIR" --no-create-home --shell /usr/sbin/nologin "$USER_NAME"
fi
mkdir -p "$AGENT_DIR"
chown "$USER_NAME:$USER_NAME" "$AGENT_DIR"
chmod 750 "$AGENT_DIR"

# The virtual environment, built from the lock file.
[ -x "$AGENT_DIR/venv/bin/python" ] || python3 -m venv "$AGENT_DIR/venv"
if ! cmp -s "$CODE_DIR/requirements.lock" "$AGENT_DIR/venv/.lock-installed"; then
  "$AGENT_DIR/venv/bin/pip" install -q --no-deps -r "$CODE_DIR/requirements.lock"
  cp "$CODE_DIR/requirements.lock" "$AGENT_DIR/venv/.lock-installed"
fi

# The settings file: copied from the example, an existing one is kept.
if [ ! -f "$AGENT_DIR/config.toml" ]; then
  cp "$CODE_DIR/config.example.toml" "$AGENT_DIR/config.toml"
  chown "root:$USER_NAME" "$AGENT_DIR/config.toml"
  chmod 640 "$AGENT_DIR/config.toml"
fi

# The shared token: made once, readable by root and the agent user only.
if [ ! -s "$AGENT_DIR/token" ]; then
  (umask 077; head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$AGENT_DIR/token.new")
  mv "$AGENT_DIR/token.new" "$AGENT_DIR/token"
fi
chown "root:$USER_NAME" "$AGENT_DIR/token"
chmod 640 "$AGENT_DIR/token"

# Tell Phoenix who the agent is: [agent_next] uid and token_file in global.toml.
AGENT_UID="$(id -u "$USER_NAME")"
mkdir -p "$HOME_DIR/config"
python3 - "$GLOBAL" "$AGENT_UID" "$AGENT_DIR/token" <<'PY'
import os, re, sys
path, uid, token_file = sys.argv[1:4]
text = open(path).read() if os.path.exists(path) else ""
lines = text.splitlines()
out, in_section, seen = [], False, set()
for line in lines:
    header = re.match(r"\s*\[([^\]]+)\]\s*$", line)
    if header:
        if in_section:
            out += [f"{k} = {v}" for k, v in want.items() if k not in seen]
        in_section = header.group(1).strip() == "agent_next"
        want = {"uid": uid, "token_file": f'"{token_file}"'}
        seen = set()
    elif in_section:
        key = re.match(r"\s*(\w+)\s*=", line)
        if key and key.group(1) in ("uid", "token_file"):
            seen.add(key.group(1))
            line = f"{key.group(1)} = {uid if key.group(1) == 'uid' else chr(34) + token_file + chr(34)}"
    out.append(line)
if in_section:
    out += [f"{k} = {v}" for k, v in want.items() if k not in seen]
elif not any(re.match(r"\s*\[agent_next\]\s*$", l) for l in lines):
    out += ["", "[agent_next]", f"uid = {uid}", f'token_file = "{token_file}"']
tmp = path + ".new"
open(tmp, "w").write("\n".join(out) + "\n")
os.chmod(tmp, os.stat(path).st_mode & 0o7777 if os.path.exists(path) else 0o640)
os.replace(tmp, path)
PY

cp "$CODE_DIR/../deploy/agentkit/phoenix-agentkit.service" /etc/systemd/system/phoenix-agentkit.service 2>/dev/null || true
systemctl daemon-reload 2>/dev/null || true

echo "Agent setup is done. Next: put the API key in $AGENT_DIR/api-key, check the price table, then start the unit."
echo "See deploy/agentkit/README.md."
