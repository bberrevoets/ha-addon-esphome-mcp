# CLAUDE.md

This file provides guidance to Claude Code when working with code in
this repository.

## Project Overview

Home Assistant custom add-on that runs an MCP (Model Context Protocol)
server for ESPHome operations. Claude Code connects to it over HTTP
instead of SSH, getting direct access to ESPHome CLI and the
`/config/esphome/` filesystem on the HA host.

## Repository Structure

- `repository.yaml` — HA add-on repository metadata
- `esphome-mcp/` — The add-on
  - `config.yaml` — HA add-on manifest (name, version, ports, options)
  - `build.yaml` — Multi-arch Docker build config
  - `Dockerfile` — built on the official ESPHome (Debian/glibc) image
  - `run.sh` — Add-on entry point (reads config, starts server)
  - `requirements.txt` — Python dependencies (mcp, uvicorn, pyyaml)
  - `server/` — Python package
    - `main.py` — FastMCP app, tool registration, uvicorn entry point
    - `tools.py` — All tool implementations (no SSH, local filesystem)
    - `auth.py` — Bearer token middleware
  - `DOCS.md` — Add-on documentation page shown in HA UI

## Key Conventions

- **Auth**: Bearer token in `Authorization` header; auto-generated if not
  configured, persisted to `/data/auth_token`
- **Transport**: Streamable HTTP on port 8099 at `/mcp`
- **Secrets**: `secrets.yaml` is explicitly rejected in push/pull tools
- **ESPHome**: Provided by the official `ghcr.io/esphome/esphome`
  (Debian/glibc) base image — required so the ESP cross-toolchains can run.
  The tag pinned in `build.yaml` **is** the ESPHome version; bump it together
  with `version:` in `config.yaml` and a CHANGELOG entry on every release
- **Builds**: compile/flash run as background jobs; poll with
  `esphome_build_status` when a build outlives the sync window
- **OTA only**: flash/logs pass `--device OTA` (never `<name>.local`, never
  interactive) so ESPHome resolves the target from the config
- **Version check**: `flash()` queries the device over the native API
  (`aioesphomeapi`, key from `esphome config --show-secrets`) and warns on
  downgrade; best effort, runs inside the build worker thread
- **Threads**: FastMCP runs sync tools on the event loop, so every tool in
  `main.py` is `async` and offloads to `anyio.to_thread.run_sync`
- **Runtime env**: `run.sh` mirrors the official ESPHome add-on — data, build
  and PlatformIO caches under `/data` (`ESPHOME_DATA_DIR`, `PLATFORMIO_*_DIR`).
  Never use `/config/esphome/.esphome`; the Device Builder add-on wipes it
- **Config mapping**: HA Supervisor maps `/config/` into the container

## Building / Testing

The add-on is built by HA Supervisor when installed. For local testing:

```bash
cd esphome-mcp
docker build --build-arg BUILD_FROM=ghcr.io/esphome/esphome:2026.8.1 -t esphome-mcp .
docker run -p 8099:8099 -v /path/to/config:/config -e ESPHOME_MCP_AUTH_TOKEN=test esphome-mcp
```

## Releasing

1. Bump the base-image tag in `esphome-mcp/build.yaml` to the latest stable
   ESPHome (`ghcr.io/esphome/esphome:<tag>`, amd64 + arm64 are published).
2. Bump `version:` in `esphome-mcp/config.yaml`.
3. Add a CHANGELOG entry and update README/DOCS if tools changed.
4. Merge to `main` — HA picks up the new version from the repository.
   Users must reinstall (not just restart) when the base image changed.

## Deployment

Add `https://github.com/bberrevoets/ha-addon-esphome-mcp` as a custom
add-on repository in Home Assistant, then install and start the add-on.
