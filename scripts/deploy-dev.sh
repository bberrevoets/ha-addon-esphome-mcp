#!/usr/bin/env bash
# ==============================================================================
# deploy-dev.sh — test the working tree on a real Home Assistant host WITHOUT
# releasing it.
#
# Copies esphome-mcp/ to /addons/esphome-mcp on the HA host (a "Local add-on",
# id: local_esphome-mcp), renamed "ESPHome MCP Server (dev)" on host port 8098
# so it runs side by side with the installed store version (8099). The
# Supervisor builds the image on the host; /data (token, caches) persists
# across rebuilds.
#
# Usage:
#   scripts/deploy-dev.sh              sync + install/update/rebuild + start
#   scripts/deploy-dev.sh --sync-only  sync files + reload store, no build
#   scripts/deploy-dev.sh --logs       tail the dev add-on log
#   scripts/deploy-dev.sh --remove     uninstall the dev add-on, delete /addons copy
#
# Environment:
#   HA_SSH_HOST  ssh alias/host for the HA box (default: homebox — root via the
#                Advanced SSH add-on, which maps /addons)
#   HA_DEV_PORT  host port for the dev add-on (default: 8098)
#
# Runs from Git Bash on Windows or any Linux shell (needs ssh, tar, git, sed).
# ==============================================================================
set -euo pipefail

SSH_HOST="${HA_SSH_HOST:-homebox}"
DEV_PORT="${HA_DEV_PORT:-8098}"
ADDON_DIR="esphome-mcp"
REMOTE_DIR="/addons/esphome-mcp"
LOCAL_SLUG="local_esphome-mcp"
DEV_NAME="ESPHome MCP Server (dev)"

usage() { sed -n '/^# Usage:/,/^# ====/p' "$0" | sed 's/^# \{0,1\}//' | sed '$d'; }

MODE=deploy
case "${1:-}" in
    "") ;;
    --sync-only) MODE=sync ;;
    --logs) MODE=logs ;;
    --remove) MODE=remove ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage; exit 2 ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

remote() { ssh -n -T "$SSH_HOST" "$@"; }          # no stdin
remote_stdin() { ssh -T "$SSH_HOST" "$@"; }       # stdin piped through
addon_field() { { remote "ha apps info $LOCAL_SLUG" 2>/dev/null || true; } | sed -n "s/^$1:[[:space:]]*//p" | sed -n "1p"; }
host_name() { ssh -T -G "$SSH_HOST" | sed -n 's/^hostname //p'; }

case "$MODE" in
    logs)
        remote "ha apps logs $LOCAL_SLUG" | tail -n 60
        exit 0
        ;;
    remove)
        remote "ha apps uninstall $LOCAL_SLUG >/dev/null 2>&1 || true; rm -rf $REMOTE_DIR; ha store reload >/dev/null"
        echo "Removed $LOCAL_SLUG and $REMOTE_DIR on $SSH_HOST"
        exit 0
        ;;
esac

# ---- version stamp: <config version>-dev.<short sha>[.dirty] (valid semver) --
BASE_VERSION="$(sed -n 's/^version:[[:space:]]*//p' "$ADDON_DIR/config.yaml" | tr -d '"'"'"'')"
SHA="$(git rev-parse --short HEAD)"
DIRTY=""
if [ -n "$(git status --porcelain -- "$ADDON_DIR")" ]; then DIRTY=".dirty"; fi
DEV_VERSION="${BASE_VERSION}-dev.${SHA}${DIRTY}"

# ---- stage a patched copy ----------------------------------------------------
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
tar -C "$ADDON_DIR" --exclude='__pycache__' --exclude='*.pyc' -cf - . | tar -C "$STAGE" -xf -
sed -i \
    -e "s/^name:.*/name: ${DEV_NAME}/" \
    -e "s/^version:.*/version: ${DEV_VERSION}/" \
    -e "s|^  8099/tcp: 8099|  8099/tcp: ${DEV_PORT}|" \
    "$STAGE/config.yaml"
if ! grep -q "^version: ${DEV_VERSION}$" "$STAGE/config.yaml" \
   || ! grep -q "^  8099/tcp: ${DEV_PORT}$" "$STAGE/config.yaml"; then
    echo "failed to patch staged config.yaml" >&2
    exit 1
fi

# ---- upload + reload the local store -----------------------------------------
echo "==> Syncing $ADDON_DIR/ -> $SSH_HOST:$REMOTE_DIR ($DEV_VERSION)"
tar -C "$STAGE" -cf - . | remote_stdin "rm -rf $REMOTE_DIR && mkdir -p $REMOTE_DIR && tar -xf - -C $REMOTE_DIR"
remote "ha store reload" >/dev/null

if [ "$MODE" = sync ]; then
    echo "Synced. Local add-on '$DEV_NAME' is listed in the store; rebuild with: $0"
    exit 0
fi

# ---- install / update / rebuild ---------------------------------------------
INSTALLED="$(addon_field version)"
LATEST="$(addon_field version_latest)"
if [ -z "$INSTALLED" ] || [ "$INSTALLED" = "null" ]; then
    ACTION=install
elif [ "$INSTALLED" != "$LATEST" ]; then
    ACTION=update          # Supervisor refuses `rebuild` when the version changed
else
    ACTION=rebuild
fi
echo "==> ha apps $ACTION $LOCAL_SLUG (installed: ${INSTALLED:-none}, staged: $LATEST) — builds on the host, be patient"
remote "ha apps $ACTION $LOCAL_SLUG"

if [ "$(addon_field state)" != "started" ]; then
    echo "==> ha apps start $LOCAL_SLUG"
    remote "ha apps start $LOCAL_SLUG"
fi

echo
echo "==> Recent log ($LOCAL_SLUG):"
remote "ha apps logs $LOCAL_SLUG" | tail -n 25
echo
HOST="$(host_name)"
echo "Dev add-on '$DEV_NAME' $DEV_VERSION is $(addon_field state)"
echo "  health : http://${HOST}:${DEV_PORT}/health"
echo "  MCP    : http://${HOST}:${DEV_PORT}/mcp   (Bearer token: add-on option or see log above)"
