#!/usr/bin/env bash
# ==============================================================================
# ESPHome MCP Server — Add-on entry point (glibc base, no bashio)
# ==============================================================================
set -e

OPTIONS_FILE="/data/options.json"
MCP_PORT="${MCP_PORT:-8099}"

# Read auth token from add-on config (replaces bashio::config). A token
# already present in the environment (local `docker run -e ...` testing)
# takes precedence.
AUTH_TOKEN="${ESPHOME_MCP_AUTH_TOKEN:-}"
if [ -z "$AUTH_TOKEN" ]; then
    AUTH_TOKEN="$(python3 -c "import json,sys;
try:
    print(json.load(open('${OPTIONS_FILE}')).get('auth_token') or '')
except Exception:
    print('')" 2>/dev/null || true)"
fi

# Auto-generate token if not configured
if [ -z "$AUTH_TOKEN" ] || [ "$AUTH_TOKEN" = "null" ]; then
    mkdir -p /data
    TOKEN_FILE="/data/auth_token"
    if [ ! -f "$TOKEN_FILE" ]; then
        AUTH_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
        echo "$AUTH_TOKEN" > "$TOKEN_FILE"
    else
        AUTH_TOKEN="$(cat "$TOKEN_FILE")"
    fi
    # Store it as the auth_token option so it shows in the add-on's
    # Configuration tab instead of the log (needs hassio_api: true). The
    # next start then reads it from options.json like a configured token.
    if python3 - "$AUTH_TOKEN" "$OPTIONS_FILE" <<'PY'
import json, os, sys, urllib.request

token, options_file = sys.argv[1], sys.argv[2]
supervisor_token = os.environ.get("SUPERVISOR_TOKEN")
if not supervisor_token:
    sys.exit(1)
try:
    with open(options_file) as f:
        options = json.load(f)
except Exception:
    options = {}
options["auth_token"] = token
request = urllib.request.Request(
    "http://supervisor/addons/self/options",
    data=json.dumps({"options": options}).encode(),
    headers={
        "Authorization": f"Bearer {supervisor_token}",
        "Content-Type": "application/json",
    },
    method="POST",
)
try:
    urllib.request.urlopen(request, timeout=10)
except Exception as e:
    print(f"[WARN] Could not save the token to the add-on options: {e}")
    sys.exit(1)
PY
    then
        echo "[INFO] Generated an MCP auth token and saved it as the auth_token"
        echo "[INFO] option: copy it from the add-on's Configuration tab."
    else
        # Never lock the user out: without the Supervisor API the log is the
        # only place the generated token can be read.
        echo "[WARN] ==================================================="
        echo "[WARN]   MCP Auth Token: ${AUTH_TOKEN}"
        echo "[WARN] ==================================================="
        echo "[WARN] Set this token in your MCP client's Authorization header."
    fi
fi

# Log a fingerprint only, enough to check which token a client should use.
if [ "${#AUTH_TOKEN}" -ge 32 ]; then
    echo "[INFO] MCP auth token: ${AUTH_TOKEN:0:4}...${AUTH_TOKEN: -4}"
else
    echo "[INFO] MCP auth token: set (${#AUTH_TOKEN} characters)"
fi

export ESPHOME_MCP_AUTH_TOKEN="$AUTH_TOKEN"
export ESPHOME_DIR="/config/esphome"
export MCP_PORT

# ------------------------------------------------------------------------------
# ESPHome / PlatformIO environment — mirrors the official ESPHome Device
# Builder add-on (docker/ha-addon-rootfs/etc/s6-overlay/s6-rc.d/esphome/run).
#
# Everything lives in this add-on's private /data volume, which persists
# across restarts and updates. Do NOT use /config/esphome/.esphome: the
# official Device Builder add-on deletes that directory on every start.
# ------------------------------------------------------------------------------
pio_cache_base=/data/cache/platformio

# Storage json + build dirs (/data/build/<name>) instead of /config/esphome/.esphome
export ESPHOME_DATA_DIR=/data
# Libraries pre-installed in the base image
export PLATFORMIO_GLOBALLIB_DIR=/piolibs
# Toolchains/platforms/packages cache (core_dir itself must stay default —
# PlatformIO keeps its settings in core_dir/appstate.json)
export PLATFORMIO_PLATFORMS_DIR="${pio_cache_base}/platforms"
export PLATFORMIO_PACKAGES_DIR="${pio_cache_base}/packages"
export PLATFORMIO_CACHE_DIR="${pio_cache_base}/cache"
# Native toolchain installs (ESP-IDF / nRF SDK) on the persistent volume
export ESPHOME_ESP_IDF_PREFIX=/data/cache/idf
export ESPHOME_SDK_NRF_PREFIX=/data/cache/sdk-nrf

mkdir -p "${pio_cache_base}" /config/esphome

ESPHOME_VERSION="$(esphome version 2>/dev/null | sed -n 's/^Version: //p' || true)"
echo "[INFO] ESPHome ${ESPHOME_VERSION:-unknown} (base image)"
echo "[INFO] Starting ESPHome MCP Server on port ${MCP_PORT}..."
exec python3 -m server.main
