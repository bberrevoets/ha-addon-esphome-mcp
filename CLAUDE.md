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
  - `Dockerfile` — Alpine + Python + ESPHome container
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
- **ESPHome**: Installed at build time via pip in the Docker image
- **Config mapping**: HA Supervisor maps `/config/` into the container

## Building / Testing

The add-on is built by HA Supervisor when installed. For local testing:

```bash
cd esphome-mcp
docker build --build-arg BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.21 -t esphome-mcp .
docker run -p 8099:8099 -v /path/to/config:/config -e ESPHOME_MCP_AUTH_TOKEN=test esphome-mcp
```

## Deployment

Add `https://github.com/bberrevoets/ha-addon-esphome-mcp` as a custom
add-on repository in Home Assistant, then install and start the add-on.
