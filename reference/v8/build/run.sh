#!/usr/bin/env bash
# Phoenix v8 core: unattended build loop.
#
# For each step file in build/steps/, starts a FRESH `claude -p` session with that
# step's prompt, then checks the result itself (new "Step N:" commit, clean tree,
# whole pytest suite green). Up to 3 tries per step, each try a new session told
# what failed last time. A step that still fails is logged and the loop moves on.
# Usage-limit hits wait and retry without using a try.
#
# Run:      bash build/run.sh            (steps 1-9)
#           FIRST=10 LAST=10 bash build/run.sh   (one step)
# Re-run:   finished steps are skipped. To redo a step, delete its line in build/progress.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

STEPS_DIR="$ROOT/build/steps"
LOG_DIR="$ROOT/build/logs"
PROGRESS="$ROOT/build/progress"
REF="${REF:-/root/ref/phoenix-0.6.0}"
FIRST="${FIRST:-1}"
LAST="${LAST:-9}"            # steps 10-11 need you (tokens, GitHub, merge)
TRIES="${TRIES:-3}"
SESSION_MIN="${SESSION_MIN:-120}"   # hard cap per session
LIMIT_WAIT_MIN="${LIMIT_WAIT_MIN:-30}"
LIMIT_MAX_H="${LIMIT_MAX_H:-12}"
PY="$ROOT/.venv/bin/python"

# Claude Code refuses permission bypass as root unless it is told it is sandboxed.
export IS_SANDBOX=1

mkdir -p "$LOG_DIR"
touch "$PROGRESS"

say()    { echo "[$(date '+%F %T')] $*" | tee -a "$LOG_DIR/run.log"; }
stop()   { say "STOPPED: $*"; notify "stopped: $*"; exit 1; }
notify() { if command -v ph-notify >/dev/null 2>&1; then ph-notify "Phoenix v8 build: $*" >/dev/null 2>&1 || true; fi; }

# One loop at a time.
exec 9>"$ROOT/build/.lock"
flock -n 9 || { echo "Another build loop is already running."; exit 1; }

# ---------- progress file: "<step>\t<status>\t<tries>\t<note>" ----------
status_of() { awk -F'\t' -v n="$1" '$1==n {print $2}' "$PROGRESS" | tail -n1; }
record()    { printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" >> "$PROGRESS"; }

# ---------- reading claude -p JSON output ----------
field() {  # field <json file> <key>
  python3 - "$1" "$2" <<'EOF'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print(""); sys.exit()
if isinstance(d, list):
    d = next((x for x in reversed(d) if isinstance(x, dict) and x.get("type") == "result"), {})
v = d.get(sys.argv[2], "")
print("" if v is None else v)
EOF
}

is_limit() {  # is_limit <json file> <stderr file>
  # Only an errored session counts. A normal answer that merely talks about
  # limits and resets (step 3 builds rate-limit handling) must not match.
  python3 - "$1" "$2" <<'EOF'
import json, re, sys
words = lambda t: re.search(r'limit', t, re.I) and re.search(r'reset', t, re.I)
try:
    d = json.load(open(sys.argv[1]))
    if isinstance(d, list):
        d = next((x for x in reversed(d) if isinstance(x, dict) and x.get("type") == "result"), None)
except Exception:
    d = None
if not isinstance(d, dict):  # no result at all: fall back to the end of stderr
    try:
        err = open(sys.argv[2], errors="replace").read()[-2000:]
    except Exception:
        err = ""
    sys.exit(0 if words(err) else 1)
if d.get("api_error_status") == 429:
    sys.exit(0)
text = str(d.get("result") or "")
sys.exit(0 if d.get("is_error") and len(text) <= 600 and words(text) else 1)
EOF
}

# ---------- setup ----------
find_ref() {
  [ -f "$REF/hands/loop.py" ] && return 0
  local src
  while IFS= read -r src; do
    src="${src%/hands/loop.py}"
    if git -c safe.directory='*' -C "$src" cat-file -e 'bce3d66^{commit}' 2>/dev/null; then
      mkdir -p "$(dirname "$REF")"
      git -c safe.directory='*' clone -q "$src" "$REF" \
        && git -C "$REF" checkout -q bce3d66 \
        && { say "reference 0.6.0 copied from $src"; return 0; }
    fi
  done < <(find /home /root /opt /srv /docker -maxdepth 5 -type f -path '*/hands/loop.py' 2>/dev/null)
  return 1
}

bootstrap() {
  command -v claude >/dev/null || stop "claude is not on PATH for this user"
  command -v git    >/dev/null || stop "git is not installed"
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' \
    || stop "python3 is older than 3.12"

  if [ ! -x "$PY" ]; then
    python3 -m venv .venv 2>/dev/null || { apt-get install -y -qq python3-venv >/dev/null && python3 -m venv .venv; } \
      || stop "could not create .venv (apt install python3-venv)"
    "$PY" -m pip install -q --upgrade pip pytest || stop "could not install pytest into .venv"
  fi

  find_ref || stop "Phoenix 0.6.0 code (commit bce3d66) not found. Put a copy at $REF"

  if [ ! -d .git ]; then git init -q -b main; fi
  git config user.name  >/dev/null || git config user.name  "Phoenix builder"
  git config user.email >/dev/null || git config user.email "builder@rebirth.ai"
  if ! git rev-parse -q --verify HEAD >/dev/null; then
    git add -A && git commit -qm "Step 0: build kit" || stop "first commit failed"
  fi
}

preflight() {
  local out="$LOG_DIR/preflight.json"
  echo "Reply with the single word OK." \
    | timeout 120 claude -p --output-format json --permission-mode bypassPermissions > "$out" 2> "$LOG_DIR/preflight.stderr"
  local res; res="$(field "$out" result)"
  echo "$res" | grep -q OK || stop "claude -p test failed: $(tail -c 400 "$LOG_DIR/preflight.stderr") $res"
  say "preflight OK (claude -p works, permission bypass allowed)"
}

# ---------- one step ----------
compose_prompt() {  # compose_prompt <n> <step file> <feedback>
  local n="$1" file="$2" feedback="$3"
  cat <<EOF
You are an unattended coding agent building Phoenix v8 core, step $n of 11, in the folder $ROOT.
Nobody is watching and nobody will answer questions. Never stop to ask. When something is unclear, pick the sensible option, write it down in BUILD-NOTES.md under "## Step $n", and keep going.

Before you start:
- Read CLAUDE.md (fixed facts and hard rules).
- Read BUILD-NOTES.md if it exists (decisions from earlier steps).
- Run \`git log --oneline\` to see what earlier steps built.
- Phoenix 0.6.0 reference code is at $REF (read only).

Rules for this session:
- Build only step $n. Do not start later steps.
- Never edit CLAUDE.md or anything under build/.
- "Done when" items that say "Manual": run them yourself and paste the command and its output into BUILD-NOTES.md under "## Step $n". If one cannot run on this machine, say why there and carry on.
- When finished: \`.venv/bin/python -m pytest -q\` must pass for the whole repo, earlier steps' tests included. Then commit everything with a message that starts exactly "Step $n:". Leave no uncommitted files.
EOF
  if [ -n "$feedback" ]; then
    cat <<EOF

PREVIOUS TRY FAILED. Its work is still in the folder. Fix it rather than starting over.
What the build loop found:
$feedback
EOF
  fi
  printf '\n--- STEP %s ---\n\n' "$n"
  cat "$file"
}

check_step() {  # check_step <n> <start sha>; prints why on failure
  local n="$1" start="$2"
  if [ "$(git rev-parse HEAD)" = "$start" ]; then echo "No new commit was made."; return 1; fi
  if ! git log --format=%s "$start..HEAD" | grep -q "^Step $n:"; then
    echo "No commit message starts with \"Step $n:\"."; return 1
  fi
  if [ -n "$(git diff --name-only "$start..HEAD" -- CLAUDE.md build)" ]; then
    echo "CLAUDE.md or build/ was changed; that is not allowed:"
    git diff --name-only "$start..HEAD" -- CLAUDE.md build; return 1
  fi
  if [ -n "$(git status --porcelain)" ]; then
    echo "Uncommitted changes left behind:"; git status --short | head -20; return 1
  fi
  local out rc
  out="$("$PY" -m pytest -q 2>&1)"; rc=$?
  if [ "$rc" -ne 0 ]; then
    if [ "$rc" -eq 5 ]; then echo "pytest found no tests."; else echo "pytest failed (exit $rc):"; fi
    echo "$out" | tail -n 60
    return 1
  fi
  echo "$out" | tail -n 3
}

run_step() {
  local n="$1" nn; nn="$(printf %02d "$n")"
  local file="$STEPS_DIR/step-$nn.md"
  [ -f "$file" ] || { say "step $n: no file $file, skipping"; return; }

  local start; start="$(git rev-parse HEAD)"
  local feedback="" try=1 waited_min=0

  while [ "$try" -le "$TRIES" ]; do
    local base="$LOG_DIR/step-$nn-try$try"
    compose_prompt "$n" "$file" "$feedback" > "$base.prompt.md"
    say "step $n try $try: session started"

    timeout -s INT -k 60 "${SESSION_MIN}m" \
      claude -p --output-format json --permission-mode bypassPermissions \
      < "$base.prompt.md" > "$base.json" 2> "$base.stderr"
    local rc=$?
    local result cost
    result="$(field "$base.json" result)"
    cost="$(field "$base.json" total_cost_usd)"

    if is_limit "$base.json" "$base.stderr"; then
      if [ "$waited_min" -ge $((LIMIT_MAX_H * 60)) ]; then
        record "$n" "paused" "$try" "usage limit not reset after ${LIMIT_MAX_H}h"
        stop "usage limit still hit after ${LIMIT_MAX_H}h at step $n"
      fi
      say "step $n: usage limit hit, waiting ${LIMIT_WAIT_MIN} min (not counted as a try)"
      [ "$waited_min" -eq 60 ] && notify "waiting on usage limit at step $n"
      sleep $((LIMIT_WAIT_MIN * 60)); waited_min=$((waited_min + LIMIT_WAIT_MIN))
      continue
    fi

    local note=""
    [ "$rc" -eq 124 ] && note="The session was stopped after ${SESSION_MIN} minutes (time limit)."

    if check_step "$n" "$start" > "$base.check.txt" 2>&1; then
      say "step $n PASSED on try $try (cost \$${cost:-?})"
      record "$n" "passed" "$try" "$(git log -1 --format=%s)"
      return
    fi

    say "step $n try $try failed: $(head -n1 "$base.check.txt")"
    feedback="$note
$(cat "$base.check.txt")

The previous session's last message:
$(echo "$result" | tail -c 1500)"
    try=$((try + 1))
  done

  # Out of tries: keep the work so later steps have a clean tree, mark it, move on.
  git add -A >/dev/null 2>&1
  git commit -qm "Step $n: WIP, failed checks after $TRIES tries" >/dev/null 2>&1 || true
  record "$n" "failed" "$TRIES" "$(head -n1 "$LOG_DIR/step-$nn-try$TRIES.check.txt")"
  say "step $n FAILED after $TRIES tries, moving on"
  notify "step $n failed after $TRIES tries"
}

summary() {
  say "----- summary -----"
  for n in $(seq "$FIRST" "$LAST"); do
    local line; line="$(awk -F'\t' -v n="$n" '$1==n' "$PROGRESS" | tail -n1)"
    say "step $n: ${line:-not run}"
  done
  local passed failed
  passed="$(awk -F'\t' '$2=="passed"' "$PROGRESS" | cut -f1 | sort -u | wc -l)"
  failed="$(awk -F'\t' '$2=="failed"' "$PROGRESS" | cut -f1 | sort -u | wc -l)"
  notify "finished steps $FIRST-$LAST: $passed passed, $failed failed"
}

# ---------- main ----------
say "===== build loop started: steps $FIRST-$LAST ====="
bootstrap
preflight
for n in $(seq "$FIRST" "$LAST"); do
  st="$(status_of "$n")"
  if [ "$st" = "passed" ] || [ "$st" = "failed" ]; then
    say "step $n already $st, skipping"; continue
  fi
  run_step "$n"
done
summary
