#!/usr/bin/env bash
# Phoenix 9 project chat launcher: started by claude-rc-chat@<project>.service as `chat-launch.sh <project>`.
# Re-attaches the project's saved conversation (the "Conversation id" line of .phoenix/chat.md), so waking a
# chat opens the same conversation. If that conversation can't be re-attached (it fails within 90 seconds:
# deleted in the app, expired), the chat document is moved to chat.old.md and a new conversation is created.
# SIGTERM/SIGINT are passed on to Claude, so `systemctl stop` ends the conversation cleanly.
# Tests override the folders with PHOENIX_PROJECTS and PHOENIX_CLAUDE_BIN.
set -u

PROJECT="${1:-}"
PROJECTS="${PHOENIX_PROJECTS:-/srv/projects}"
CLAUDE="${PHOENIX_CLAUDE_BIN:-/root/.local/bin/claude}"
REATTACH_WINDOW=90   # seconds: a failure sooner than this means the saved conversation is gone

refuse() {
    printf 'chat-launch: %s\n' "$1" >&2
    exit 2
}

[[ "$PROJECT" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || refuse "not a valid project name: '$PROJECT'"
FOLDER="$PROJECTS/$PROJECT"
[ -d "$FOLDER" ] || refuse "no project folder $FOLDER"
cd "$FOLDER" || refuse "cannot enter the project folder $FOLDER"
DOC="$FOLDER/.phoenix/chat.md"

saved_id() {
    # The saved conversation id from the chat document, or nothing when it is missing or malformed.
    local id=""
    if [ -f "$DOC" ]; then
        id="$(sed -n 's/^Conversation id:[[:space:]]*//p' "$DOC" | head -n 1 | tr -d '\r')"
        id="${id%"${id##*[![:space:]]}"}"
    fi
    if [[ "$id" =~ ^[A-Za-z0-9_-]{1,100}$ ]]; then
        printf '%s' "$id"
    fi
}

CHILD=""
SIGNALLED=no
pass_on() {
    # Pass the stop signal to Claude (as TERM: background children ignore INT) and remember it.
    SIGNALLED=yes
    if [ -n "$CHILD" ]; then
        kill -TERM "$CHILD" 2>/dev/null
    fi
}
trap pass_on TERM INT

ID="$(saved_id)"
if [ -n "$ID" ] && [ "$SIGNALLED" = no ]; then
    STARTED=$SECONDS
    "$CLAUDE" remote-control --session-id "$ID" --permission-mode bypassPermissions &
    CHILD=$!
    # A stop signal that arrived before CHILD was set was not passed on yet.
    [ "$SIGNALLED" = no ] || kill -TERM "$CHILD" 2>/dev/null
    # `wait` returns early when a signal arrives; keep waiting until Claude has really ended.
    while :; do
        wait "$CHILD"
        RC=$?
        kill -0 "$CHILD" 2>/dev/null || break
    done
    CHILD=""
    if [ "$SIGNALLED" = yes ] || [ "$RC" -eq 0 ] || [ $((SECONDS - STARTED)) -ge "$REATTACH_WINDOW" ]; then
        exit "$RC"
    fi
    mv -f "$DOC" "$FOLDER/.phoenix/chat.old.md"
    printf 'chat-launch: the saved conversation could not be re-attached (exit %s); starting a new one\n' "$RC"
fi

[ "$SIGNALLED" = no ] || exit 143
trap - TERM INT
exec "$CLAUDE" remote-control --name "$PROJECT" --spawn same-dir --capacity 3 --create-session-in-dir \
    --permission-mode bypassPermissions
