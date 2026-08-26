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
- `scripts/deploy-dev.sh` — push the working tree to the HA host as a local
  dev add-on (see Building / Testing)
- `scripts/render-icons.py` — rasterize `icon.svg`/`logo.svg` to PNG
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
  - `icon.svg` / `icon.png`, `logo.svg` / `logo.png` — presentation files
    (HA reads the PNGs; the SVGs are the sources)
  - `CHANGELOG.md` — Add-on changelog; must live here (next to
    `config.yaml`) or HA shows "No changelog found" on update. The
    root `CHANGELOG.md` is only a pointer to this file

## Key Conventions

- **Auth**: Bearer token in `Authorization` header; auto-generated if not
  configured, persisted to `/data/auth_token`
- **Transport**: Streamable HTTP on port 8099 at `/mcp`; `GET /health`
  (unauthenticated) backs the image `HEALTHCHECK`. Never use
  `HEALTHCHECK NONE`: it leaves `Test: ["NONE"]` in the metadata and the
  Supervisor then waits forever for a healthy event ("Starting")
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
  (`aioesphomeapi`, key/password from `esphome config --show-secrets`)
  *before* starting the build and refuses a downgrade unless
  `allow_downgrade=true`; best effort (unreachable → proceeds)
- **Threads**: FastMCP runs sync tools on the event loop, so every tool in
  `main.py` is `async` and offloads to `anyio.to_thread.run_sync`
- **Runtime env**: `run.sh` mirrors the official ESPHome add-on — data, build
  and PlatformIO caches under `/data` (`ESPHOME_DATA_DIR`, `PLATFORMIO_*_DIR`).
  Never use `/config/esphome/.esphome`; the Device Builder add-on wipes it
- **Config mapping**: HA Supervisor maps `/config/` into the container
- **Presentation files**: `icon.png` (128×128) and `logo.png` (250×100) next
  to `config.yaml`. Edit the SVG sources and regenerate with
  `python scripts/render-icons.py` (Playwright Chromium + Pillow). Commit the
  PNGs as plain git files — **never Git LFS**: the Supervisor clones with plain
  git and would get an LFS pointer file instead of an image

## Building / Testing

The add-on is built by HA Supervisor when installed. Three ways to test a
change before it is released, cheapest first. None of them publishes
anything: users' HA instances only follow `main`, so feature branches are
always safe to push.

1. **Local Docker build** (server smoke test on the dev machine):

   ```bash
   cd esphome-mcp
   docker build --build-arg BUILD_FROM=ghcr.io/esphome/esphome:2026.8.1 -t esphome-mcp .
   docker run -p 8099:8099 -v /path/to/config:/config -e ESPHOME_MCP_AUTH_TOKEN=test esphome-mcp
   ```

2. **Dev add-on on the real HA host** — `bash scripts/deploy-dev.sh`. Copies
   the working tree (uncommitted changes included) to `/addons/esphome-mcp`
   over SSH (`homebox` alias; `HA_SSH_HOST` overrides), renamed
   "ESPHome MCP Server (dev)" with version `<version>-dev.<sha>[.dirty]` on
   host port 8098 (`HA_DEV_PORT`), then runs `ha store reload` + `ha apps`
   install/update/rebuild + start. It runs side by side with the store
   version (8099) and shows up under *Local apps* as `local_esphome-mcp`.
   Flags: `--sync-only` (files only, no build), `--logs`, `--remove`. The
   Supervisor builds on the host: the first build takes a few minutes, later
   ones hit the Docker layer cache (`requirements.txt` is copied before
   `server/`). `/data` (token, caches) survives rebuilds.

3. **Branch as a second repository** (no SSH needed; also for other
   testers): push the branch, then add
   `https://github.com/bberrevoets/ha-addon-esphome-mcp#<branch>` as another
   repository in HA. It installs as a separate add-on (own repository hash)
   — change its host port under *Network* before starting. Each iteration:
   push → *Check for updates* → Update/Rebuild. Remove the repository when
   done.

## Releasing

1. Bump the base-image tag in `esphome-mcp/build.yaml` to the latest stable
   ESPHome (`ghcr.io/esphome/esphome:<tag>`, amd64 + arm64 are published).
2. Bump `version:` in `esphome-mcp/config.yaml`.
3. Add an entry to `esphome-mcp/CHANGELOG.md` (the copy HA displays) and
   update README/DOCS if tools changed.
4. Merge to `main` — HA picks up the new version from the repository.
   Users must reinstall (not just restart) when the base image changed.

## Deployment

Add `https://github.com/bberrevoets/ha-addon-esphome-mcp` as a custom
add-on repository in Home Assistant, then install and start the add-on.
