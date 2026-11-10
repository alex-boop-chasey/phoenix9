#!/usr/bin/env bash
# Run agentkit's tests inside its own virtual environment.
set -euo pipefail
cd "$(dirname "$0")/.."
agentkit/venv.sh
exec agentkit/.venv/bin/python -m pytest -q agentkit/tests "$@"
