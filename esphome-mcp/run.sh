#!/usr/bin/env bash
# ==============================================================================
# ESPHome MCP Server — Add-on entry point (glibc base, no bashio)
# ==============================================================================
set -e

OPTIONS_FILE="/data/options.json"

# Read auth token from add-on config (replaces bashio::config)
AUTH_TOKEN="$(python3 -c "import json,sys;
try:
    print(json.load(open('${OPTIONS_FILE}')).get('auth_token') or '')
except Exception:
    print('')" 2>/dev/null || true)"

# Auto-generate token if not configured
if [ -z "$AUTH_TOKEN" ] || [ "$AUTH_TOKEN" = "null" ]; then
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

# Reuse the PlatformIO toolchains/cache the official ESPHome Device Builder
# add-on already downloaded under /config, avoiding a second download.
export PLATFORMIO_CORE_DIR="/config/esphome/.esphome/.platformio"

echo "[INFO] Starting ESPHome MCP Server on port ${MCP_PORT}..."
exec python3 -m server.main
