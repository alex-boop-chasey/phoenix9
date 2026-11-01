#!/bin/sh
# Git credential helper for Phoenix's own clones (phoenix/git.py).
# Usage (set by git.py, never stored in a repo): git-credential.sh <github.env> get
# It reads GH_TOKEN from the env file at the moment git asks, and hands it to
# git on stdout. The token is never written into a URL, a config file or a
# workspace.
envfile="$1"
action="$2"
cat >/dev/null                  # git writes the request on stdin; read it so git never gets SIGPIPE
[ "$action" = get ] || exit 0
[ -r "$envfile" ] || exit 0
token=$(sed -n 's/^[[:space:]]*\(export[[:space:]][[:space:]]*\)\{0,1\}GH_TOKEN[[:space:]]*=[[:space:]]*//p' "$envfile" \
        | head -n 1 | sed 's/[[:space:]]*$//' | sed "s/^\"\(.*\)\"\$/\1/; s/^'\(.*\)'\$/\1/")
[ -n "$token" ] || exit 0
printf 'username=x-access-token\npassword=%s\n' "$token"
