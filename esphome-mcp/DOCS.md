# ESPHome MCP Server

This add-on runs an MCP (Model Context Protocol) server that exposes
ESPHome operations as tools for Claude Code. It runs directly on your
Home Assistant instance with native filesystem access to
`/config/esphome/` — no SSH tunneling required.

## Architecture

```text
Claude Code (desktop)  --HTTP-->  HA Add-on (MCP Server)  --local-->  ESPHome CLI
                                       |
                                  /config/esphome/  (direct filesystem access)
```

## Configuration

### auth_token

An authentication token to secure the MCP endpoint. If left empty, a
token is auto-generated on first start and printed in the add-on logs.

You can set your own token in the add-on configuration:

```yaml
auth_token: "my-secret-token"
```

## Setup

1. Add this repository as a custom add-on repository in Home Assistant:
   **Settings > Add-ons > Add-on Store > ... > Repositories**
   Enter: `https://github.com/bberrevoets/ha-addon-esphome-mcp`

2. Install the **ESPHome MCP Server** add-on and start it.

3. Check the add-on logs for the auth token (if you didn't set one).

4. Set the `ESPHOME_MCP_TOKEN` environment variable on your development
   machine to the auth token value.

5. Configure `.mcp.json` in your ESPHome project:

   ```json
   {
     "mcpServers": {
       "esphome": {
         "type": "http",
         "url": "http://<your-ha-host>:8099/mcp",
         "headers": {
           "Authorization": "Bearer ${ESPHOME_MCP_TOKEN}"
         }
       }
     }
   }
   ```

6. Restart Claude Code and verify the connection with `/mcp`.

## Available Tools

| Tool | Description |
| ---- | ----------- |
| `esphome_list_devices` | List device configs with names |
| `esphome_validate` | Validate a device YAML config |
| `esphome_compile` | Compile firmware for a device |
| `esphome_flash` | OTA flash a device |
| `esphome_logs` | Get recent device logs (snapshot) |
| `esphome_push_files` | Write YAML files to the config directory |
| `esphome_pull_files` | Read YAML files from the config directory |
| `esphome_push_fonts` | Write font files (base64-encoded) |
| `esphome_pull_fonts` | Read font files (base64-encoded) |

## Security

- All requests require a valid Bearer token in the Authorization header.
- `secrets.yaml` is explicitly rejected in push/pull operations.
- The add-on exposes port 8099 — ensure your network is trusted or use
  a reverse proxy with TLS.

## Network

The add-on listens on port **8099** (TCP). Make sure this port is
accessible from your development machine.
