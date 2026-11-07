#!/bin/sh
# python3 -m pytest -q tests/test_transcript.py
cd "$(dirname "$0")/../../.." || exit 1
test -f tests/test_transcript.py || { echo "tests/test_transcript.py missing"; exit 1; }
test -f tests/fixtures/agent-transcript.jsonl || { echo "fixture missing"; exit 1; }
test -f phoenix9/transcript.py || { echo "phoenix9/transcript.py missing"; exit 1; }
exec python3 -m pytest -q tests/test_transcript.py
