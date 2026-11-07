#!/bin/sh
# python3 -m pytest -q tests/test_agentlink.py
cd "$(dirname "$0")/../../.." || exit 1
test -f tests/test_agentlink.py || { echo "tests/test_agentlink.py missing"; exit 1; }
test -f phoenix9/agentlink.py || { echo "phoenix9/agentlink.py missing"; exit 1; }
python3 - <<'PY' || exit 1
import sys
sys.path.insert(0, ".")
from phoenix9 import agentlink
for n in ("find", "status"):
    if not callable(getattr(agentlink, n, None)):
        print("agentlink.%s missing" % n); sys.exit(1)
PY
exec python3 -m pytest -q tests/test_agentlink.py
