"""ESPHome MCP tool implementations.

All tools operate locally on the Home Assistant filesystem — no SSH needed.
"""

import base64
import glob
import logging
import os
import subprocess

import yaml

log = logging.getLogger("esphome-mcp")

ESPHOME_DIR = os.environ.get("ESPHOME_DIR", "/config/esphome")
ESPHOME_BIN = "esphome"

FORBIDDEN_FILES = {"secrets.yaml", ".secret.yaml"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _resolve_device(device: str) -> str:
    """Resolve a device name to its YAML filename (without path)."""
    if not device.endswith(".yaml"):
        device = f"{device}.yaml"
    return device


def _device_yaml_path(device: str) -> str:
    """Return the full path to a device YAML file."""
    filename = _resolve_device(device)
    path = os.path.join(ESPHOME_DIR, filename)
    if os.path.isfile(path):
        return path
    archive_path = os.path.join(ESPHOME_DIR, "archive", filename)
    if os.path.isfile(archive_path):
        return archive_path
    return path


def _run(cmd: list[str], timeout: int = 120, cwd: str | None = None) -> str:
    """Run a command and return combined stdout+stderr."""
    log.info("Running: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd or ESPHOME_DIR,
        )
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        output = output.strip()
        if result.returncode != 0:
            return f"Command failed (exit {result.returncode}):\n{output}"
        return output
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s"
    except FileNotFoundError as e:
        return f"Command not found: {e}"


def _parse_device_info(yaml_path: str) -> dict:
    """Parse basic device info from a YAML file."""
    try:
        with open(yaml_path, encoding="utf-8") as f:
            class SecretLoader(yaml.SafeLoader):
                pass

            def secret_constructor(loader, node):
                return f"!secret {loader.construct_scalar(node)}"

            SecretLoader.add_constructor("!secret", secret_constructor)
            data = yaml.load(f, Loader=SecretLoader)

        esphome_section = data.get("esphome", {})
        return {
            "name": esphome_section.get("name", "unknown"),
            "friendly_name": esphome_section.get("friendly_name", ""),
            "file": os.path.basename(yaml_path),
        }
    except Exception as e:
        return {
            "name": "error",
            "friendly_name": "",
            "file": os.path.basename(yaml_path),
            "error": str(e),
        }


def _is_forbidden(filename: str) -> bool:
    """Check if a filename is forbidden for transfer."""
    return os.path.basename(filename).lower() in FORBIDDEN_FILES


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------
def list_devices() -> str:
    """List all available ESPHome device configurations."""
    devices = []

    for path in sorted(glob.glob(os.path.join(ESPHOME_DIR, "*.yaml"))):
        if _is_forbidden(path):
            continue
        info = _parse_device_info(path)
        info["status"] = "active"
        devices.append(info)

    archive_dir = os.path.join(ESPHOME_DIR, "archive")
    if os.path.isdir(archive_dir):
        for path in sorted(glob.glob(os.path.join(archive_dir, "*.yaml"))):
            info = _parse_device_info(path)
            info["status"] = "archived"
            devices.append(info)

    if not devices:
        return "No device configurations found."

    lines = ["ESPHome Devices:", ""]
    for d in devices:
        name = d["name"]
        friendly = f' ("{d["friendly_name"]}")' if d.get("friendly_name") else ""
        status = f" [{d['status']}]" if d["status"] == "archived" else ""
        error = f" ERROR: {d['error']}" if d.get("error") else ""
        lines.append(f"  - {name}{friendly}{status} ({d['file']}){error}")

    return "\n".join(lines)


def validate(device: str) -> str:
    """Validate an ESPHome device config."""
    yaml_path = _device_yaml_path(device)
    if not os.path.isfile(yaml_path):
        return f"Device config not found: {yaml_path}"
    return _run([ESPHOME_BIN, "config", yaml_path])


def compile_device(device: str) -> str:
    """Compile ESPHome firmware for a device."""
    yaml_path = _device_yaml_path(device)
    if not os.path.isfile(yaml_path):
        return f"Device config not found: {yaml_path}"
    return _run([ESPHOME_BIN, "compile", yaml_path], timeout=300)


def flash(device: str) -> str:
    """OTA flash a device."""
    yaml_path = _device_yaml_path(device)
    if not os.path.isfile(yaml_path):
        return f"Device config not found: {yaml_path}"
    return _run([ESPHOME_BIN, "run", yaml_path, "--no-logs"], timeout=600)


def logs(device: str, num_lines: int = 50) -> str:
    """Get recent logs from an ESPHome device."""
    yaml_path = _device_yaml_path(device)
    if not os.path.isfile(yaml_path):
        return f"Device config not found: {yaml_path}"
    output = _run(
        ["timeout", "15", ESPHOME_BIN, "logs", yaml_path],
        timeout=30,
    )
    lines = output.splitlines()
    if len(lines) > num_lines:
        lines = lines[-num_lines:]
    return "\n".join(lines)


def push_files(files: dict[str, str]) -> str:
    """Write YAML files to the ESPHome config directory.

    Args:
        files: Dict mapping filename to YAML content.
    """
    results = []
    for filename, content in files.items():
        if _is_forbidden(filename):
            results.append(f"{filename}: REJECTED (secrets files cannot be pushed)")
            continue
        if not filename.endswith(".yaml"):
            results.append(f"{filename}: REJECTED (only .yaml files allowed)")
            continue

        # Support archive/ subdirectory
        target = os.path.join(ESPHOME_DIR, filename)
        os.makedirs(os.path.dirname(target), exist_ok=True)

        try:
            with open(target, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            results.append(f"{filename}: OK")
        except OSError as e:
            results.append(f"{filename}: ERROR ({e})")

    return "Push results:\n" + "\n".join(results)


def pull_files(filenames: list[str] | None = None) -> dict[str, str]:
    """Read YAML files from the ESPHome config directory.

    Args:
        filenames: Optional list of filenames to pull. If None, pulls all.

    Returns:
        Dict mapping filename to YAML content.
    """
    result = {}

    if filenames is None:
        # Pull all YAML files
        paths = sorted(glob.glob(os.path.join(ESPHOME_DIR, "*.yaml")))
        archive_dir = os.path.join(ESPHOME_DIR, "archive")
        if os.path.isdir(archive_dir):
            paths += sorted(glob.glob(os.path.join(archive_dir, "*.yaml")))
    else:
        paths = []
        for fn in filenames:
            if not fn.endswith(".yaml"):
                fn = f"{fn}.yaml"
            path = os.path.join(ESPHOME_DIR, fn)
            if os.path.isfile(path):
                paths.append(path)
            else:
                archive_path = os.path.join(ESPHOME_DIR, "archive", fn)
                if os.path.isfile(archive_path):
                    paths.append(archive_path)

    for path in paths:
        if _is_forbidden(path):
            continue
        rel = os.path.relpath(path, ESPHOME_DIR)
        try:
            with open(path, encoding="utf-8") as f:
                result[rel] = f.read()
        except OSError as e:
            result[rel] = f"ERROR: {e}"

    return result


def push_fonts(files: dict[str, str]) -> str:
    """Write font files to the ESPHome fonts directory.

    Args:
        files: Dict mapping filename to base64-encoded content.
    """
    fonts_dir = os.path.join(ESPHOME_DIR, "fonts")
    os.makedirs(fonts_dir, exist_ok=True)

    results = []
    for filename, b64_content in files.items():
        target = os.path.join(fonts_dir, os.path.basename(filename))
        try:
            data = base64.b64decode(b64_content)
            with open(target, "wb") as f:
                f.write(data)
            results.append(f"{filename}: OK ({len(data)} bytes)")
        except Exception as e:
            results.append(f"{filename}: ERROR ({e})")

    return "Font push results:\n" + "\n".join(results)


def pull_fonts(filenames: list[str] | None = None) -> dict[str, str]:
    """Read font files from the ESPHome fonts directory.

    Args:
        filenames: Optional list of font filenames. If None, pulls all.

    Returns:
        Dict mapping filename to base64-encoded content.
    """
    fonts_dir = os.path.join(ESPHOME_DIR, "fonts")
    result = {}

    if not os.path.isdir(fonts_dir):
        return result

    if filenames is None:
        paths = sorted(glob.glob(os.path.join(fonts_dir, "*")))
    else:
        paths = [
            os.path.join(fonts_dir, os.path.basename(fn))
            for fn in filenames
            if os.path.isfile(os.path.join(fonts_dir, os.path.basename(fn)))
        ]

    for path in paths:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as f:
                data = f.read()
            result[os.path.basename(path)] = base64.b64encode(data).decode("ascii")
        except OSError as e:
            result[os.path.basename(path)] = f"ERROR: {e}"

    return result
