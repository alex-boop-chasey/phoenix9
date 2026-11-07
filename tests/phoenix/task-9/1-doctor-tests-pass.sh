#!/bin/sh
# python3 -m pytest -q tests/test_doctor.py
cd "$(dirname "$0")/../../.." || exit 1
test -f tests/test_doctor.py || { echo "tests/test_doctor.py missing"; exit 1; }
python3 - <<'PY' || exit 1
import sys
sys.path.insert(0, ".")
from phoenix9 import doctor
full = set(doctor.CHECKS_BY_MODE["full"])
new = [k for k in doctor.CHECKS if k not in (
    "python","library","services","api","origins","home","secrets","images","proxy-rule","firewall",
    "claude","advisor","disk","updater","project-links","memory-files")]
if len(new) < 4:
    print("fewer than 4 new doctor checks: %r" % new); sys.exit(1)
miss = [k for k in new if k not in full]
if miss:
    print("new checks not in full mode: %r" % miss); sys.exit(1)
src = open("tests/test_doctor.py").read().lower()
for word in ("agent", "transcript", "claude.md", "settings.json", "0700", "0o700"):
    if word not in src:
        print("tests/test_doctor.py does not cover %r" % word); sys.exit(1)
PY
exec python3 -m pytest -q tests/test_doctor.py
