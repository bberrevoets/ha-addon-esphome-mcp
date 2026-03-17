"""ESPHome MCP Server — FastMCP application with streamable HTTP transport."""

import json
import logging
import os

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
    stateless_http=True,
)


# ---------------------------------------------------------------------------
# Register tools
# ---------------------------------------------------------------------------
@mcp.tool()
def esphome_list_devices() -> str:
    """List all available ESPHome device configurations.

    Scans YAML files in the ESPHome config directory,
    returning device names and friendly names.
    """
    return tools.list_devices()


@mcp.tool()
def esphome_validate(device: str) -> str:
    """Validate an ESPHome device config.

    Args:
        device: Device name (e.g. 'statusdisplay') or YAML filename.
    """
    return tools.validate(device)


@mcp.tool()
def esphome_compile(device: str) -> str:
    """Compile ESPHome firmware for a device.

    Args:
        device: Device name (e.g. 'statusdisplay') or YAML filename.
    """
    return tools.compile_device(device)


@mcp.tool()
def esphome_flash(device: str) -> str:
    """OTA flash a device.

    Args:
        device: Device name (e.g. 'statusdisplay') or YAML filename.
    """
    return tools.flash(device)


@mcp.tool()
def esphome_logs(device: str, num_lines: int = 50) -> str:
    """Get recent logs from an ESPHome device.

    Captures a snapshot of logs (streaming is not supported in MCP tools).

    Args:
        device: Device name (e.g. 'statusdisplay') or YAML filename.
        num_lines: Number of log lines to return (default 50).
    """
    return tools.logs(device, num_lines)


@mcp.tool()
def esphome_push_files(files: dict[str, str]) -> str:
    """Push YAML config files to the ESPHome directory on Home Assistant.

    Writes files to /config/esphome/. Rejects secrets.yaml.

    Args:
        files: Dict mapping filename to YAML content.
               Use 'archive/name.yaml' for archived configs.
    """
    return tools.push_files(files)


@mcp.tool()
def esphome_pull_files(filenames: list[str] | None = None) -> str:
    """Pull YAML config files from the ESPHome directory on Home Assistant.

    Returns file contents. Excludes secrets.yaml.

    Args:
        filenames: Optional list of filenames to pull.
                   If omitted, returns all YAML files.
    """
    result = tools.pull_files(filenames)
    return json.dumps(result, indent=2)


@mcp.tool()
def esphome_push_fonts(files: dict[str, str]) -> str:
    """Push font files to the ESPHome fonts directory on Home Assistant.

    Args:
        files: Dict mapping filename to base64-encoded file content.
    """
    return tools.push_fonts(files)


@mcp.tool()
def esphome_pull_fonts(filenames: list[str] | None = None) -> str:
    """Pull font files from the ESPHome fonts directory on Home Assistant.

    Returns base64-encoded file contents.

    Args:
        filenames: Optional list of font filenames to pull.
                   If omitted, returns all fonts.
    """
    result = tools.pull_fonts(filenames)
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
