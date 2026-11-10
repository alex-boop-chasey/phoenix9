#!/usr/bin/env bash
# Browser checks: seeded demo HOME + tests/demo_server.py (fake adapters) + Playwright at phone and desktop widths.
set -euo pipefail
cd "$(dirname "$0")"

export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/opt/pw-browsers}"
if ! ls -d "$PLAYWRIGHT_BROWSERS_PATH"/chromium* >/dev/null 2>&1; then
  echo "Playwright's browser is not installed at $PLAYWRIGHT_BROWSERS_PATH (the chat installs it; see phase-3 README)"
  exit 1
fi

TMP=$(mktemp -d)
API_PID=""
AGENT_PID=""
cleanup() {
  [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null || true
  [ -n "$AGENT_PID" ] && kill "$AGENT_PID" 2>/dev/null || true
  rm -rf "$TMP"
}
trap cleanup EXIT

[ -d web/node_modules ] || pnpm -C web install --frozen-lockfile
pnpm -C web build

python3 tests/seed_demo.py "$TMP/home" "$TMP/projects"

agentkit/venv.sh
python3 -c 'import secrets; print(secrets.token_hex(16))' >"$TMP/agent-token"
AGENT_PORT=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
agentkit/.venv/bin/python agentkit/demo.py --token-file "$TMP/agent-token" --port "$AGENT_PORT" >"$TMP/agent.out" 2>&1 &
AGENT_PID=$!
export PHOENIX_E2E_AGENT_URL="http://127.0.0.1:$AGENT_PORT" PHOENIX_E2E_AGENT_TOKEN_FILE="$TMP/agent-token"

PORT=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
PHOENIX_API_ORIGINS="http://127.0.0.1:$PORT" python3 tests/demo_server.py "$TMP/home" "$TMP/projects" --port "$PORT" \
  >"$TMP/api.out" 2>&1 &
API_PID=$!

ready=""
for _ in $(seq 1 75); do
  if python3 -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:$PORT/api/info', timeout=2)" 2>/dev/null; then
    ready=yes
    break
  fi
  sleep 0.2
done
if [ -z "$ready" ]; then
  echo "The demo API did not answer within 15 seconds. Its log ends with:"
  tail -n 30 "$TMP/api.out"
  exit 1
fi

PHOENIX_E2E_URL="http://127.0.0.1:$PORT/" PHOENIX_E2E_HOME="$TMP/home" PHOENIX_E2E_PROJECTS="$TMP/projects" \
  pnpm -C web e2e
