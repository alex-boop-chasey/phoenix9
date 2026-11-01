#!/usr/bin/env bash
# First install of Phoenix 9 on the VPS. Run as root:
#   bash install.sh --tag v9.1
# Refuses to run when Phoenix 9 is already installed (use `phoenix update` after that).
# Secrets are copied file to file with `install -m 600`; they are never read into a variable,
# put on a command line or printed.
#
# Environment overrides (tests only; the defaults are the real server):
#   PHOENIX_INSTALL      where the code goes            (/opt/phoenix9)
#   PHOENIX_HOME         where data and secrets go      (/var/lib/phoenix9)
#   PHOENIX_SYSTEMD_DIR  where unit files go            (/etc/systemd/system)
#   PHOENIX_SYSTEMCTL    the systemctl command          (systemctl)
#   PHOENIX_BIN_LINK     the `phoenix` command link     (/usr/local/bin/phoenix)
#   PHOENIX_INSTALL_ALLOW_NONROOT=1  skip the root check
set -euo pipefail

INSTALL="${PHOENIX_INSTALL:-/opt/phoenix9}"
HOME_DIR="${PHOENIX_HOME:-/var/lib/phoenix9}"
SYSTEMD_DIR="${PHOENIX_SYSTEMD_DIR:-/etc/systemd/system}"
SYSTEMCTL="${PHOENIX_SYSTEMCTL:-systemctl}"
BIN_LINK="${PHOENIX_BIN_LINK:-/usr/local/bin/phoenix}"
TAG=""
REPO="https://github.com/alex-boop-chasey/phoenix9.git"
API_PORT=8095
V8_CONFIG="/var/lib/docker/volumes/phoenix-config/_data"
TELEGRAM_ENV="/home/builder/.config/hands/telegram.env"
NO_START=no
SKIP_CHECKS=no
SKIP_WEB=no

say() { printf '==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --tag) [ $# -ge 2 ] || die "--tag needs a value"; TAG="$2"; shift 2 ;;
        --repo) [ $# -ge 2 ] || die "--repo needs a value"; REPO="$2"; shift 2 ;;
        --api-port) [ $# -ge 2 ] || die "--api-port needs a value"; API_PORT="$2"; shift 2 ;;
        --v8-config) [ $# -ge 2 ] || die "--v8-config needs a value"; V8_CONFIG="$2"; shift 2 ;;
        --telegram-env) [ $# -ge 2 ] || die "--telegram-env needs a value"; TELEGRAM_ENV="$2"; shift 2 ;;
        --no-start) NO_START=yes; shift ;;
        --skip-checks) SKIP_CHECKS=yes; warn "--skip-checks: tools and tests are NOT checked (tests only)"; shift ;;
        --skip-web) SKIP_WEB=yes; warn "--skip-web: the dashboard is NOT built (tests only)"; shift ;;
        *) die "unknown option: $1" ;;
    esac
done

[[ "$TAG" =~ ^v9\.(0|[1-9][0-9]*)$ ]] || die "give the release with --tag v9.N (for example --tag v9.1)"
[[ "$API_PORT" =~ ^[1-9][0-9]{0,4}$ ]] || die "--api-port must be a port number"

# ------------------------------------------------------------------ 1. checks
say "Checking this computer"
if [ "${PHOENIX_INSTALL_ALLOW_NONROOT:-}" != 1 ] && [ "$(id -u)" -ne 0 ]; then
    die "run install.sh as root (it writes to /opt and /etc/systemd)."
fi
need_tool() {
    if command -v "$1" >/dev/null 2>&1; then return 0; fi
    if [ "$SKIP_CHECKS" = yes ]; then warn "$1 is missing"; else die "$1 is not installed."; fi
}
for tool in git python3 node pnpm gh; do need_tool "$tool"; done
if command -v python3 >/dev/null 2>&1 \
   && ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
    if [ "$SKIP_CHECKS" = yes ]; then warn "python3 is older than 3.12"; else die "python3 3.12 or newer is needed."; fi
fi
if ! command -v docker >/dev/null 2>&1; then
    warn "docker is not installed: the step images cannot be built yet."
fi

# ------------------------------------------------------------------ 2. not twice
if [ -e "$INSTALL" ]; then
    die "already installed: use \`phoenix update\` ($INSTALL exists)."
fi

# ------------------------------------------------------------------ 3. clone
say "Downloading Phoenix 9 $TAG into $INSTALL"
git -c credential.helper= -c 'credential.helper=!gh auth git-credential' clone --quiet "$REPO" "$INSTALL"
git -C "$INSTALL" checkout --quiet --detach "$TAG"

# ------------------------------------------------------------------ 4. data folders
say "Creating the data folders in $HOME_DIR"
mkdir -p "$HOME_DIR" "$HOME_DIR/config" "$HOME_DIR/runs" "$HOME_DIR/logs" "$HOME_DIR/update"
install -d -m 700 "$HOME_DIR/secrets" "$HOME_DIR/keys"
chmod 700 "$HOME_DIR/secrets" "$HOME_DIR/keys"

# ------------------------------------------------------------------ 5. secrets
say "Copying the Claude and Telegram keys (file to file, never shown)"
copy_secret() {
    local src="$1" dest="$2"
    if [ -e "$dest" ]; then
        say "kept the existing $(basename "$dest")"
    elif [ -f "$src" ]; then
        install -m 600 "$src" "$dest"
        say "saved $(basename "$dest") (mode 0600)"
    else
        warn "$src was not found, so $(basename "$dest") was not saved."
    fi
}
copy_secret "$V8_CONFIG/claude.env" "$HOME_DIR/secrets/claude.env"
copy_secret "$TELEGRAM_ENV" "$HOME_DIR/secrets/telegram.env"

# ------------------------------------------------------------------ 6. api.env
if [ ! -e "$HOME_DIR/config/api.env" ]; then
    say "Writing config/api.env (dashboard port $API_PORT)"
    printf 'PHOENIX_API_PORT=%s\nPHOENIX_API_ORIGINS=%s\n' "$API_PORT" "https://files.rebirthwebdesign.com.au" \
        > "$HOME_DIR/config/api.env"
fi

# ------------------------------------------------------------------ 7. build and check
stop_failed() {
    printf 'ERROR: %s failed. The download is left in %s for inspection.\n' "$1" "$INSTALL" >&2
    printf 'To start over: rm -rf %s   (then run install.sh again)\n' "$INSTALL" >&2
    exit 1
}
if [ "$SKIP_WEB" = no ]; then
    say "Building the dashboard"
    (cd "$INSTALL" && pnpm -C web install --frozen-lockfile && pnpm -C web build) || stop_failed "the dashboard build"
fi
if [ "$SKIP_CHECKS" = no ]; then
    say "Running the checks"
    (cd "$INSTALL" && ./check.sh) || stop_failed "the checks"
fi

# ------------------------------------------------------------------ 8. services
say "Installing the systemd units"
for unit in phoenix-api.service phoenix-runner.service phoenix9-update.service; do
    install -m 644 "$INSTALL/deploy/$unit" "$SYSTEMD_DIR/$unit"
done
"$SYSTEMCTL" daemon-reload
if [ "$NO_START" = yes ]; then
    say "Not starting the services (--no-start). Start them with: systemctl enable --now phoenix-runner phoenix-api"
else
    say "Starting the runner and the dashboard"
    "$SYSTEMCTL" enable --now phoenix-runner.service phoenix-api.service
fi

# ------------------------------------------------------------------ 9. command
say "Linking the phoenix command at $BIN_LINK"
ln -sfn "$INSTALL/bin/phoenix" "$BIN_LINK"

# ------------------------------------------------------------------ 10. doctor and next steps
if [ "$SKIP_CHECKS" = no ]; then
    say "Quick health check"
    PHOENIX_HOME="$HOME_DIR" PHOENIX_INSTALL="$INSTALL" "$INSTALL/bin/phoenix" doctor --quick \
        || warn "the quick health check found problems (see above). The install itself is done."
fi
cat <<NEXT

Phoenix 9 $TAG is installed.
Next steps:
  1. Connect GitHub (paste the token, then press Ctrl-D):
       phoenix services connect github --from-stdin
  2. Build the step images:
       phoenix images build
  3. Check everything:
       phoenix doctor
The dashboard listens on 127.0.0.1:$API_PORT. See $INSTALL/deploy/README.md.
NEXT
