#!/bin/sh
# python3 -m pytest -q tests/test_api_agent.py
cd "$(dirname "$0")/../../.." || exit 1
test -f tests/test_api_agent.py || { echo "tests/test_api_agent.py missing"; exit 1; }
grep -q "/api/agent" phoenix9/api/server.py || { echo "no agent routes in server.py"; exit 1; }
exec python3 -m pytest -q tests/test_api_agent.py
