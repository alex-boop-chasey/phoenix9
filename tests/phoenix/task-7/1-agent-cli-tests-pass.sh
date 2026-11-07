#!/bin/sh
# python3 -m pytest -q tests/test_cli_agent.py
cd "$(dirname "$0")/../../.." || exit 1
test -f tests/test_cli_agent.py || { echo "tests/test_cli_agent.py missing"; exit 1; }
test -f phoenix9/cli/agent.py || { echo "phoenix9/cli/agent.py missing"; exit 1; }
python3 - <<'PY' || exit 1
import sys
sys.path.insert(0, ".")
from phoenix9.ops import agent
if not callable(getattr(agent, "brief", None)):
    print("ops.agent.brief missing"); sys.exit(1)
PY
out=$(PHOENIX_HOME=$(mktemp -d) python3 -m phoenix9 --help 2>&1)
echo "$out" | grep -q "agent" || { echo "phoenix --help does not list agent"; exit 1; }
for c in brief status send read; do
  PHOENIX_HOME=$(mktemp -d) python3 -m phoenix9 agent "$c" --help >/dev/null 2>&1 || { echo "phoenix agent $c --help fails"; exit 1; }
done
exec python3 -m pytest -q tests/test_cli_agent.py
