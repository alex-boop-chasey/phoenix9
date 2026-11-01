#!/usr/bin/env bash
# The one check command for every build step: Python tests, then the web app's tests and build if it exists.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pytest -q
if [ -f web/package.json ]; then
  [ -d web/node_modules ] || pnpm -C web install --frozen-lockfile
  pnpm -C web test
  pnpm -C web build
fi
