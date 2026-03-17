# ESPHome MCP Server — Home Assistant Add-on

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

MCP (Model Context Protocol) server that exposes ESPHome operations as
tools for [Claude Code](https://claude.ai/code). Runs as a Home
Assistant add-on with direct filesystem access — no SSH required.

## Quick Start

1. Add this repository as a custom add-on repository in Home Assistant:

   **Settings > Add-ons > Add-on Store > ... (menu) > Repositories**

   ```text
   https://github.com/bberrevoets/ha-addon-esphome-mcp
   ```

2. Install and start the **ESPHome MCP Server** add-on.

3. Check the add-on logs for the auto-generated auth token.

4. Set `ESPHOME_MCP_TOKEN` in your shell environment.

5. Add to `.mcp.json` in your ESPHome project:

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

6. Restart Claude Code and verify with `/mcp`.

## Tools

| Tool | Description |
| ---- | ----------- |
| `esphome_list_devices` | List device configs with names |
| `esphome_validate` | Validate a device YAML config |
| `esphome_compile` | Compile firmware for a device |
| `esphome_flash` | OTA flash a device |
| `esphome_logs` | Get recent device logs |
| `esphome_push_files` | Write YAML configs to HA |
| `esphome_pull_files` | Read YAML configs from HA |
| `esphome_push_fonts` | Write font files (base64) to HA |
| `esphome_pull_fonts` | Read font files (base64) from HA |

## Architecture

```text
Claude Code (desktop)  --HTTP-->  HA Add-on (MCP Server)  --local-->  ESPHome CLI
                                       |
                                  /config/esphome/  (direct filesystem access)
```

See [esphome-mcp/DOCS.md](esphome-mcp/DOCS.md) for full documentation.

## License

[MIT](LICENSE) — Berrevoets Systems
