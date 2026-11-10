#!/usr/bin/env bash
# Make agentkit's own virtual environment (agentkit/.venv) from the lock file when it is missing or out of date.
set -euo pipefail
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || python3 -m venv .venv
if ! cmp -s requirements.lock .venv/.lock-installed; then
  .venv/bin/pip install -q --no-deps -r requirements.lock
  cp requirements.lock .venv/.lock-installed
fi
