# Changelog

All notable changes to this project will be documented in this file.

## Attributors

- **Bert Berrevoets** — Project author
- **Claude Code** — AI-assisted development

## [1.1.0] - 2026-05-20

### Changed

- Rebased the image on the official `ghcr.io/esphome/esphome` (Debian/glibc)
  image. The previous Alpine/musl base could not run ESPHome's glibc ESP
  cross-toolchains (`xtensa-lx106-elf-g++`), so every compile failed with
  `not found` (exit 127). Compiles/flashes now work.
- Replaced bashio/`with-contenv` startup with a plain `/data/options.json`
  read; cleared the base image's inherited `ENTRYPOINT` and `HEALTHCHECK`
  (the dashboard healthcheck caused a ~60s restart loop).
- `run.sh` sets `PLATFORMIO_CORE_DIR` to the shared
  `/config/esphome/.esphome/.platformio` so toolchains are reused across
  builds and shared with the ESPHome Device Builder add-on.

### Added

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
