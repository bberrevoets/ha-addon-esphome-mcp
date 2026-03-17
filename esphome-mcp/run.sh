#!/usr/bin/with-contenv bashio
# ==============================================================================
# ESPHome MCP Server — Add-on entry point
# ==============================================================================
set -e

# Read auth token from add-on config
AUTH_TOKEN="$(bashio::config 'auth_token')"

# Auto-generate token if not configured
if [ -z "$AUTH_TOKEN" ] || [ "$AUTH_TOKEN" = "null" ]; then
    TOKEN_FILE="/data/auth_token"
    if [ ! -f "$TOKEN_FILE" ]; then
        AUTH_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
        echo "$AUTH_TOKEN" > "$TOKEN_FILE"
        bashio::log.info "Generated new auth token — retrieve it from the add-on logs"
    else
        AUTH_TOKEN="$(cat "$TOKEN_FILE")"
    fi
    bashio::log.warning "==================================================="
    bashio::log.warning "  MCP Auth Token: ${AUTH_TOKEN}"
    bashio::log.warning "==================================================="
    bashio::log.warning "Set ESPHOME_MCP_TOKEN in your Claude Code environment"
    bashio::log.warning "to this value, or configure it in the add-on options."
fi

export ESPHOME_MCP_AUTH_TOKEN="$AUTH_TOKEN"
export ESPHOME_DIR="/config/esphome"

bashio::log.info "Starting ESPHome MCP Server on port 8099..."
exec python3 -m server.main
