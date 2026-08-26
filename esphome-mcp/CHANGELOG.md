# Changelog

All notable changes to this project will be documented in this file.

## Attributors

- **Bert Berrevoets** — Project author
- **Olaf van der Kaa** — glibc base image, background builds (PR #6)
- **Claude Code** — AI-assisted development

## [1.2.2] - 2026-08-26

Base image unchanged (`ghcr.io/esphome/esphome:2026.8.1`, still the latest
stable); updating restarts the add-on, no reinstall needed.

### Added

Author: *Bert Berrevoets, Claude Code*

- Add-on icon and logo (`icon.png`, `logo.png`) shown in the Home Assistant
  add-on store and Apps overview instead of the generic placeholder. SVG
  sources are in the add-on folder; `scripts/render-icons.py` regenerates
  the PNGs.
- `scripts/deploy-dev.sh`: deploy the working tree to a Home Assistant host
  as a local "ESPHome MCP Server (dev)" add-on (port 8098) to test changes
  before releasing them.

### Changed

Author: *Bert Berrevoets, Claude Code*

- Documentation: how to test unreleased builds (dev add-on script, or a
  branch added as a second repository with `#<branch>`).

### Fixed

Author: *Bert Berrevoets, Claude Code*

- Per-device tools (`esphome_validate`, `esphome_compile`, `esphome_flash`,
  `esphome_logs`, `esphome_build_status`) accept the device **name** shown by
  `esphome_list_devices`, not only the YAML filename. A device whose
  `esphome.name` differs from its filename (`co2-sensor1` in
  `co2-woonkamer.yaml`) failed with "Device config not found"; the name (or
  `friendly_name`) is now matched against the configs, active and archived.
  Archived matches keep their `archive/` path, so an active config with the
  same filename is never used instead, and background builds are keyed by
  that path as well.

## [1.2.1] - 2026-08-26

### Fixed

Author: *Bert Berrevoets, Claude Code*

- Add-on stuck in "Starting" in the Home Assistant UI. `HEALTHCHECK NONE`
  (1.1.x) leaves a `Test: ["NONE"]` healthcheck in the image metadata, so the
  Supervisor waited forever for a `healthy` event. The server now exposes
  `GET /health` (no auth) and the image defines a real `HEALTHCHECK` against
  it, so the add-on reports *Started* and the watchdog can act on it.
- Changelog moved to `esphome-mcp/CHANGELOG.md` so Home Assistant shows it in
  the update dialog (previously "No changelog found").

## [1.2.0] - 2026-08-26

### Changed

Author: *Bert Berrevoets, Claude Code*

- Base image bumped to `ghcr.io/esphome/esphome:2026.8.1`. The pinned tag in
  `build.yaml` **is** the ESPHome version the add-on compiles with and is now
  bumped together with every add-on release, so a stale image can no longer
  silently downgrade devices (#8).
- `esphome_flash` and `esphome_logs` pass `--device OTA` (exactly what the
  ESPHome Device Builder does): ESPHome resolves the target from the config
  (`use_address`, static IP, `<name>.local`, MQTT IP lookup) and never opens
  the interactive serial/OTA chooser that crashed with `EOFError` (#4).
- Build and cache directories moved to the add-on's own `/data` volume
  (`ESPHOME_DATA_DIR`, `PLATFORMIO_*_DIR`, `ESPHOME_ESP_IDF_PREFIX`, mirroring
  the official add-on). `/config/esphome/.esphome`, used in 1.1.x, is deleted
  by the ESPHome Device Builder add-on on every start.
- MCP tool handlers run in worker threads; long ESPHome commands and the
  compile/flash sync-wait window no longer block the server's event loop.
- `esphome_logs` treats the end of the 15 s snapshot (exit 124) as success
  instead of reporting `Command failed`.

### Added

Author: *Bert Berrevoets, Claude Code*

- Firmware version check on `esphome_flash`: before anything is built, the
  device's running ESPHome version is queried over the native API and the
  output starts with `ESPHome add-on: X | device firmware: Y`. A device that
  runs a newer ESPHome than the add-on is **not** flashed (a `WARNING`
  explains the downgrade) unless the new `allow_downgrade=true` argument is
  passed (#8).
- `esphome_list_devices` and compile output show the add-on's ESPHome version.
- `.markdownlint.json` (180-char lines, sibling-only duplicate headings).

### Fixed

Author: *Bert Berrevoets, Claude Code*

- Pinned `mcp<2` in `requirements.txt`. Unpinned, a fresh image build now
  installs mcp 2.x, which renamed `FastMCP` and made the server crash at
  start (`ModuleNotFoundError: mcp.server.fastmcp`).
- `run.sh` honours a pre-set `ESPHOME_MCP_AUTH_TOKEN` (local `docker run`
  testing) and creates `/data` before writing the generated token.

## [1.1.1] - 2026-08-26

Contributed by Olaf van der Kaa in PR #6 (fixes #5).

### Changed

Author: *Olaf van der Kaa*

- Rebased the image on the official `ghcr.io/esphome/esphome` (Debian/glibc)
  image. The previous Alpine/musl base could not run ESPHome's glibc ESP
  cross-toolchains (`xtensa-lx106-elf-g++`), so every compile failed with
  `not found` (exit 127). Compiles/flashes now work.
- Replaced bashio/`with-contenv` startup with a plain `/data/options.json`
  read; cleared the base image's inherited `ENTRYPOINT` and `HEALTHCHECK`
  (the dashboard healthcheck caused a ~60s restart loop).
- `run.sh` sets `PLATFORMIO_CORE_DIR` to
  `/config/esphome/.esphome/.platformio` so toolchains are reused across
  builds (superseded in 1.2.0).
- Device parser resolves `${substitutions}` and tolerates ESPHome's custom
  YAML tags (`!lambda`, `!include`, ...).

### Added

Author: *Olaf van der Kaa*

- Background builds: `esphome_compile` / `esphome_flash` run in a thread and
  return a pollable handle for long builds, with new `esphome_build_status`
  to check progress — avoids MCP request timeouts on multi-minute compiles.
- `esphome_flash` forces OTA (`--device <name>.local`) so it no longer hangs
  on the interactive serial/OTA chooser when USB adapters are present.

## [1.0.0] - 2026-03-17

### Added

Author: *Bert Berrevoets, Claude Code*

- Initial release as Home Assistant add-on
- FastMCP server with streamable HTTP transport on port 8099
- Bearer token authentication (auto-generated or user-configured)
- Nine MCP tools: list_devices, validate, compile, flash, logs,
  push_files, pull_files, push_fonts, pull_fonts
- Direct filesystem access to `/config/esphome/` — no SSH required
- Alpine-based Docker image with ESPHome and PlatformIO pre-installed
- Multi-architecture support (aarch64, amd64)
- Add-on documentation (DOCS.md)
- secrets.yaml protection in push/pull operations
