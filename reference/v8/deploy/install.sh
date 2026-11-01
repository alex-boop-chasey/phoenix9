#!/usr/bin/env bash
# Set up Phoenix v8 core on the VPS as a Docker Compose project.
#
# Run as root from anywhere:  bash /docker/phoenix-v8/deploy/install.sh
# Safe to run again: volumes, phoenix.toml and token files that already exist
# are kept (press Enter at a token prompt to keep the one you have).
#
# What it does:
#   1. builds the Phoenix image (phoenix-core:8) from deploy/Dockerfile.phoenix
#   2. creates the volumes phoenix-plans, phoenix-runs, phoenix-config, phoenix-cache
#   3. writes /phoenix/config/phoenix.toml (Telegram through the host's ph-notify if it is there)
#   4. asks for the Claude token and the GitHub token and writes
#      /phoenix/config/claude.env and github.env (mode 0600, never shown on screen)
#   5. starts the service and runs `python -m phoenix doctor` inside it
set -euo pipefail

DEPLOY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$DEPLOY")"
IMAGE="phoenix-core:8"
STEP_IMAGE="phoenix-step:0.6.0"
COMPOSE=(docker compose -f "$DEPLOY/docker-compose.yml")
VOLUMES=(phoenix-plans phoenix-runs phoenix-config phoenix-cache)
NOTIFY_FILE="${PHOENIX_NOTIFY_FILE:-/srv/phoenix-inbox/jobs/notify.msg}"

say() { printf '==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }

# Run a shell command in a throwaway Phoenix container that has the config volume.
# Whatever is piped in goes to the command's stdin (that is how tokens travel:
# never on a command line, where `ps` could show them).
in_config() {
    docker run --rm -i --entrypoint sh -v phoenix-config:/phoenix/config "$IMAGE" -c "$1"
}

find_ph_notify() {
    local c
    for c in "${PH_NOTIFY:-}" "$(command -v ph-notify 2>/dev/null || true)" \
             /usr/local/bin/ph-notify /home/*/.local/bin/ph-notify; do
        if [ -n "$c" ] && [ -f "$c" ]; then
            printf '%s\n' "$c"
            return 0
        fi
    done
    return 1
}

# Ask for one secret and store it as KEY=value in /phoenix/config/<file>, mode 0600.
ask_secret() {
    local file="$1" key="$2" question="$3" value="" have=no
    if in_config "test -s /phoenix/config/$file"; then have=yes; fi
    if [ "$have" = yes ]; then
        question="$question (press Enter to keep the one already saved)"
    fi
    printf '%s: ' "$question"
    IFS= read -rs value || true
    printf '\n'
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    if [ -z "$value" ]; then
        if [ "$have" = yes ]; then
            say "kept the existing $file"
        else
            warn "no value given: $file was not written. Run install.sh again to add it."
        fi
        return 0
    fi
    printf '%s=%s\n' "$key" "$value" \
        | in_config "umask 077; cat > /phoenix/config/$file.tmp && chmod 600 /phoenix/config/$file.tmp && mv /phoenix/config/$file.tmp /phoenix/config/$file"
    value=""
    say "saved $file (mode 0600)"
}

# ------------------------------------------------------------------ checks
[ "$(id -u)" -eq 0 ] || { echo "Run install.sh as root (it talks to Docker)." >&2; exit 1; }
command -v docker >/dev/null || { echo "Docker is not installed." >&2; exit 1; }
docker compose version >/dev/null || { echo "docker compose is not available." >&2; exit 1; }
if ! docker image inspect "$STEP_IMAGE" >/dev/null 2>&1; then
    warn "the step image $STEP_IMAGE is not built yet: build it first with  docker build -t $STEP_IMAGE $REPO/image/"
fi

# ------------------------------------------------------------------ 1. image
say "building $IMAGE"
docker build -f "$DEPLOY/Dockerfile.phoenix" -t "$IMAGE" "$REPO"

# ------------------------------------------------------------------ 2. volumes
for v in "${VOLUMES[@]}"; do
    if docker volume inspect "$v" >/dev/null 2>&1; then
        say "volume $v already exists"
    else
        docker volume create "$v" >/dev/null
        say "created volume $v"
    fi
done
in_config "mkdir -p /phoenix/config/projects"

# ------------------------------------------------------------------ 3. Telegram + phoenix.toml
telegram=""
notify_mount="/dev/null"
if script="$(find_ph_notify)"; then
    if [ -f "$NOTIFY_FILE" ]; then
        in_config "cat > /phoenix/config/ph-notify && chmod 755 /phoenix/config/ph-notify" < "$script"
        telegram="/phoenix/config/ph-notify"
        notify_mount="$NOTIFY_FILE"
        say "Telegram: using $script (copied to $telegram, writes $NOTIFY_FILE)"
    else
        warn "found $script but not $NOTIFY_FILE, so Telegram messages are off"
    fi
else
    warn "no ph-notify script found: Telegram messages are off (they are printed in the log instead)"
fi
printf '# Written by deploy/install.sh. Read by docker compose.\nPHOENIX_NOTIFY_FILE=%s\n' "$notify_mount" > "$DEPLOY/.env"

if in_config "test -f /phoenix/config/phoenix.toml"; then
    say "phoenix.toml already exists: left as it is"
else
    printf '# Phoenix v8 settings. Every setting not listed here has its default.\ntelegram_script = "%s"\n' "$telegram" \
        | in_config "cat > /phoenix/config/phoenix.toml"
    say "wrote phoenix.toml (telegram_script = \"$telegram\")"
fi

# ------------------------------------------------------------------ 4. tokens
ask_secret claude.env CLAUDE_CODE_OAUTH_TOKEN "Claude token (from 'claude setup-token')"
ask_secret github.env GH_TOKEN "GitHub token (rebirth-wd fine-grained PAT)"

# ------------------------------------------------------------------ 5. start and check
say "starting the phoenix service"
"${COMPOSE[@]}" up -d
sleep 3
say "running python -m phoenix doctor inside the container"
if docker exec phoenix python -m phoenix doctor; then
    say "done. Drop a plan with:  docker cp plan.md phoenix:/phoenix/plans/"
else
    warn "doctor did not print OK: see the lines above"
    exit 1
fi
