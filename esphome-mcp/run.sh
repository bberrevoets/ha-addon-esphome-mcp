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
    echo "[WARN] ==================================================="
    echo "[WARN]   MCP Auth Token: ${AUTH_TOKEN}"
    echo "[WARN] ==================================================="
    echo "[WARN] Set this token in your MCP client's Authorization header."
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
