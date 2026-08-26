"""ESPHome MCP Server — FastMCP application with streamable HTTP transport."""

import functools
import json
import logging
import os

import anyio
import uvicorn
from mcp.server.fastmcp import FastMCP

from . import tools
from .auth import BearerAuthMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("esphome-mcp")

mcp = FastMCP(
    name="esphome",
    host="0.0.0.0",
    stateless_http=True,
)


async def _in_thread(fn, *args, **kwargs):
    """Run a blocking tool implementation in a worker thread.

    FastMCP calls plain ``def`` tools directly on the event loop, so a slow
    tool (ESPHome CLI calls, the compile/flash sync-wait window) would stall
    every other request on the server. Offload the work to a thread instead.
    """
    return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))


# ---------------------------------------------------------------------------
# Register tools
# ---------------------------------------------------------------------------
@mcp.tool()
async def esphome_list_devices() -> str:
    """List all available ESPHome device configurations.

    Scans YAML files in the ESPHome config directory,
    returning device names and friendly names. The header line shows the
    ESPHome version this add-on compiles with.
    """
    return await _in_thread(tools.list_devices)


@mcp.tool()
async def esphome_validate(device: str) -> str:
    """Validate an ESPHome device config.

    Args:
        device: Device name (e.g. 'statusdisplay') or YAML filename.
    """
    return await _in_thread(tools.validate, device)


@mcp.tool()
async def esphome_compile(device: str) -> str:
    """Compile ESPHome firmware for a device.

    The build runs in the background. If it finishes quickly the full output
    is returned inline; if it takes longer than the sync window, a pollable
    handle is returned — check progress with esphome_build_status(device).

    Args:
        device: Device name (e.g. 'statusdisplay') or YAML filename.
    """
    return await _in_thread(tools.compile_device, device)


@mcp.tool()
async def esphome_flash(device: str, allow_downgrade: bool = False) -> str:
    """OTA flash a device (compile + upload over the network).

    The upload target is always resolved from the device config
    (`--device OTA`: use_address, static IP or <name>.local) — serial
    upload is never used.

    Before anything is built, the device's running firmware version is
    queried over the native API. The output starts with
    "ESPHome add-on: X | device firmware: Y". If the device runs a NEWER
    ESPHome than this add-on, the flash is REFUSED (nothing is started) and
    a WARNING explains the downgrade; call again with allow_downgrade=true
    only if the user explicitly wants to downgrade the device.

    Like esphome_compile, this runs in the background and may return a
    pollable handle for long builds — check esphome_build_status(device).

    Args:
        device: Device name (e.g. 'statusdisplay') or YAML filename.
        allow_downgrade: Proceed even if the device runs a newer ESPHome
            than this add-on (default False).
    """
    return await _in_thread(tools.flash, device, allow_downgrade)


@mcp.tool()
async def esphome_build_status(device: str) -> str:
    """Get the status/output of the latest background compile or flash.

    Use this to poll a build that esphome_compile / esphome_flash reported as
    still running. Returns running progress (tail) or the final result.

    Args:
        device: Device name (e.g. 'statusdisplay') or YAML filename.
    """
    return await _in_thread(tools.build_status, device)


@mcp.tool()
async def esphome_logs(device: str, num_lines: int = 50) -> str:
    """Get recent logs from an ESPHome device.

    Captures a ~15s snapshot of logs over the network (native API, resolved
    from the device config via `--device OTA`); streaming and serial logs
    are not supported in MCP tools.

    Args:
        device: Device name (e.g. 'statusdisplay') or YAML filename.
        num_lines: Number of log lines to return (default 50).
    """
    return await _in_thread(tools.logs, device, num_lines)


@mcp.tool()
async def esphome_push_files(files: dict[str, str]) -> str:
    """Push YAML config files to the ESPHome directory on Home Assistant.

    Writes files to /config/esphome/. Rejects secrets.yaml.

    Args:
        files: Dict mapping filename to YAML content.
               Use 'archive/name.yaml' for archived configs.
    """
    return await _in_thread(tools.push_files, files)


@mcp.tool()
async def esphome_pull_files(filenames: list[str] | None = None) -> str:
    """Pull YAML config files from the ESPHome directory on Home Assistant.

    Returns file contents. Excludes secrets.yaml.

    Args:
        filenames: Optional list of filenames to pull.
                   If omitted, returns all YAML files.
    """
    result = await _in_thread(tools.pull_files, filenames)
    return json.dumps(result, indent=2)


@mcp.tool()
async def esphome_push_fonts(files: dict[str, str]) -> str:
    """Push font files to the ESPHome fonts directory on Home Assistant.

    Args:
        files: Dict mapping filename to base64-encoded file content.
    """
    return await _in_thread(tools.push_fonts, files)


@mcp.tool()
async def esphome_pull_fonts(filenames: list[str] | None = None) -> str:
    """Pull font files from the ESPHome fonts directory on Home Assistant.

    Returns base64-encoded file contents.

    Args:
        filenames: Optional list of font filenames to pull.
                   If omitted, returns all fonts.
    """
    result = await _in_thread(tools.pull_fonts, filenames)
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# ASGI app with auth middleware
# ---------------------------------------------------------------------------
app = mcp.streamable_http_app()
app.add_middleware(BearerAuthMiddleware)


if __name__ == "__main__":
    port = int(os.environ.get("MCP_PORT", "8099"))
    log.info("ESPHome MCP Server starting on port %d", port)
    uvicorn.run(
        "server.main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
