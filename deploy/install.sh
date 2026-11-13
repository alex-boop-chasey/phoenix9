#!/usr/bin/env bash
# First install of Phoenix 9 on the VPS. Run as root:
#   bash install.sh --tag v9.1
# Refuses to run when Phoenix 9 is already installed (use `phoenix update` after that).
#
# Host firewall: when ufw is active, install.sh adds ONE rule so step containers can reach the key
# proxy (TCP from the docker bridge subnet to the bridge gateway, on the proxy port range only; see
# docs/architecture.md section 14). It prints the rule and asks first (--yes skips the question).
#   bash install.sh --firewall-only [--yes]   just that step, on a server that is already installed
#   bash install.sh --dry-run                 print what the firewall step would add; change nothing
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
ASSUME_YES=no
DRY_RUN=no
FIREWALL_ONLY=no
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
        --yes) ASSUME_YES=yes; shift ;;
        --dry-run) DRY_RUN=yes; shift ;;
        --firewall-only) FIREWALL_ONLY=yes; shift ;;
        --skip-checks) SKIP_CHECKS=yes; warn "--skip-checks: tools and tests are NOT checked (tests only)"; shift ;;
        --skip-web) SKIP_WEB=yes; warn "--skip-web: the dashboard is NOT built (tests only)"; shift ;;
        *) die "unknown option: $1" ;;
    esac
done

# ------------------------------------------------------------------ host firewall (ufw) for the key proxy
PROXY_PORTS_DEFAULT="47100-47199"
UFW_COMMENT="phoenix9 key proxy"

# The proxy port range from HOME/config/global.toml `proxy_ports` (default 47100-47199), as "LO HI".
proxy_ports() {
    local text
    text="$(python3 - "$HOME_DIR/config/global.toml" "$PROXY_PORTS_DEFAULT" <<'PY' 2>/dev/null
import sys, tomllib
try:
    with open(sys.argv[1], "rb") as f:
        print(tomllib.load(f).get("proxy_ports", sys.argv[2]))
except (OSError, ValueError):
    print(sys.argv[2])
PY
)" || text="$PROXY_PORTS_DEFAULT"
    [ -n "$text" ] || text="$PROXY_PORTS_DEFAULT"
    if [[ "$text" =~ ^[[:space:]]*([0-9]{4,5})[[:space:]]*-[[:space:]]*([0-9]{4,5})[[:space:]]*$ ]] \
       && [ "${BASH_REMATCH[1]}" -ge 1024 ] && [ "${BASH_REMATCH[1]}" -le "${BASH_REMATCH[2]}" ] \
       && [ "${BASH_REMATCH[2]}" -le 65535 ]; then
        echo "${BASH_REMATCH[1]} ${BASH_REMATCH[2]}"
    else
        return 1
    fi
}

# Add the one ufw rule letting step containers reach the key proxy; idempotent, asks unless --yes.
firewall_step() {
    say "Checking the host firewall for the key proxy"
    if ! command -v ufw >/dev/null 2>&1; then say "ufw is not installed: no rule needed."; return 0; fi
    local status
    if ! status="$(ufw status 2>&1)"; then
        warn "could not read \`ufw status\` (run as root). The key proxy rule was not checked."; return 0
    fi
    if ! grep -Eq '^Status:[[:space:]]*active' <<<"$status"; then
        say "ufw is not active: no rule needed."; return 0
    fi
    if ! command -v docker >/dev/null 2>&1; then
        warn "docker is not installed, so the bridge network is unknown: the key proxy rule was not added."
        return 0
    fi
    local net gateway subnet iface ports lo hi
    if ! net="$(docker network inspect bridge --format \
            '{{(index .IPAM.Config 0).Gateway}} {{(index .IPAM.Config 0).Subnet}} {{index .Options "com.docker.network.bridge.name"}}' 2>/dev/null)"; then
        warn "could not read docker's bridge network: the key proxy rule was not added."; return 0
    fi
    read -r gateway subnet iface <<<"$net"
    iface="${iface:-docker0}"
    if ! [[ "$gateway" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ && "$subnet" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}$ \
            && "$iface" =~ ^[A-Za-z0-9_.-]{1,15}$ ]]; then
        warn "docker's bridge network looks odd ($net): the key proxy rule was not added."; return 0
    fi
    if ! ports="$(proxy_ports)"; then
        die "global.toml proxy_ports must look like \"$PROXY_PORTS_DEFAULT\" (two ports from 1024 to 65535, low first)"
    fi
    read -r lo hi <<<"$ports"
    local rule="ufw allow in on $iface from $subnet to $gateway port $lo:$hi proto tcp comment '$UFW_COMMENT'"
    local gw_re="${gateway//./\\.}" net_re="${subnet//./\\.}"
    if grep -Eq "^${gw_re}[[:space:]]+${lo}:${hi}/tcp[[:space:]]+on[[:space:]]+${iface}[[:space:]]+ALLOW([[:space:]]+IN)?[[:space:]]+${net_re}([[:space:]]|$)" <<<"$status"; then
        say "ufw already lets step containers reach the key proxy ($subnet -> $gateway ports $lo-$hi)."; return 0
    fi
    say "ufw is on, so step containers cannot reach the key proxy yet. This rule will be added:"
    printf '    %s\n' "$rule"
    if [ "$DRY_RUN" = yes ]; then say "Dry run: nothing changed."; return 0; fi
    if [ "$ASSUME_YES" != yes ]; then
        local answer=""
        read -r -p "Add this ufw rule now? [y/N] " answer || answer=""
        if [[ ! "$answer" =~ ^[Yy] ]]; then
            warn "not added. Steps that use account keys will fail until it is (run: $rule)"; return 0
        fi
    fi
    ufw allow in on "$iface" from "$subnet" to "$gateway" port "$lo:$hi" proto tcp comment "$UFW_COMMENT" \
        || die "ufw refused the rule: $rule"
    say "Added the ufw rule for the key proxy."
}

if [ "$DRY_RUN" = yes ] || [ "$FIREWALL_ONLY" = yes ]; then
    if [ "$DRY_RUN" = no ] && [ "${PHOENIX_INSTALL_ALLOW_NONROOT:-}" != 1 ] && [ "$(id -u)" -ne 0 ]; then
        die "run install.sh --firewall-only as root (it changes ufw)."
    fi
    firewall_step
    exit 0
fi

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
    # The allowed page origins are a Phoenix setting (Global settings > Dashboard addresses); the API adds
    # PHOENIX_API_ORIGINS here itself on its first start (default: the dashboard address's origin).
    printf 'PHOENIX_API_PORT=%s\n' "$API_PORT" > "$HOME_DIR/config/api.env"
fi

# ------------------------------------------------------------------ 6b. host firewall
firewall_step

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
# The project chat template: instances are started later by `phoenix chat`, never here.
install -m 644 "$INSTALL/deploy/claude-rc-chat@.service" "$SYSTEMD_DIR/claude-rc-chat@.service"
chmod 755 "$INSTALL/deploy/chat-launch.sh"   # the chat unit's ExecStart (re-attaches the saved conversation)
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
