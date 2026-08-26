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
| `esphome_compile` | Compile firmware (background; returns inline or a poll handle) |
| `esphome_flash` | OTA flash a device (background; refuses firmware downgrades unless allowed) |
| `esphome_build_status` | Poll the latest background compile/flash for a device |
| `esphome_logs` | Get recent device logs (15 s network snapshot) |
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

## Long-running builds

Compiles (and the compile step of a flash) can take several minutes,
especially the first build of a device. These run in the background: if a
build finishes within ~45s the full output is returned immediately;
otherwise the tool returns a handle and you poll `esphome_build_status`
with the device name until it reports `done` or `failed`.

## ESPHome version and firmware downgrades

The add-on compiles with the ESPHome version of its base image — the tag
pinned in `build.yaml` (shown by `esphome_list_devices` and in the add-on
log at start). Each add-on release bumps that tag; update the add-on to get
a newer ESPHome.

Because the caller is usually an AI agent, `esphome_flash` first asks the
device for its running firmware version over the native API (before
anything is compiled) and starts its output with:

```text
ESPHome add-on: 2026.8.1 | device firmware: 2026.9.0
WARNING: the device runs a NEWER ESPHome (2026.9.0) than this add-on (2026.8.1) — flashing would DOWNGRADE its firmware. ...

Flash NOT started. To downgrade the device anyway, call esphome_flash again with allow_downgrade=true.
```

A newer device is **not** flashed unless `allow_downgrade=true` is passed.
The check is best effort: a device without `api:`, unreachable, or slow to
answer shows `device firmware: unknown` and the flash proceeds.

## Network targets (OTA only)

`esphome_flash` and `esphome_logs` always pass `--device OTA`, like the
ESPHome Device Builder. ESPHome resolves the target from the device config:
`wifi.use_address`, a static `manual_ip`, or `<name>.local` via mDNS. The
device therefore needs `api:` (and `ota:` for flashing) and must be
reachable from the Home Assistant host. Serial (USB) upload/logging is not
supported by this add-on.

## Build cache

Toolchains, PlatformIO packages and build files are stored in the add-on's
private `/data` volume (`/data/cache`, `/data/build`). They survive restarts
and updates but are removed when the add-on is uninstalled, so the first
compile after a reinstall downloads the toolchains again.
