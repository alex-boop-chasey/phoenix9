#!/bin/sh
# Phoenix 9 updater entry point (run by phoenix9-update.service as root).
# It always runs the INSTALLED package, copied to a throwaway folder first, so the folder swap can
# never change the code that is doing the swap, and new code never runs the update. It never looks
# at the -next folder. See docs/architecture.md section 15.
set -eu

INSTALL="${PHOENIX_INSTALL:-/opt/phoenix9}"
PY="${PHOENIX_UPDATER_PYTHON:-/usr/bin/python3}"
BASE="${PHOENIX_UPDATER_TMP:-/run}"

if [ ! -f "$INSTALL/phoenix9/updater.py" ]; then
  echo "Phoenix 9 is not installed at $INSTALL (no phoenix9/updater.py there), so nothing was updated." >&2
  exit 1
fi

COPY="$(mktemp -d "$BASE/phoenix9-updater.XXXXXX")"
trap 'rm -rf "$COPY"' EXIT
trap 'exit 143' TERM INT HUP
cp -R "$INSTALL/phoenix9" "$COPY/phoenix9"
cd "$COPY"
PYTHONPATH="$COPY" "$PY" -m phoenix9.updater run-request
