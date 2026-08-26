"""ESPHome MCP tool implementations.

All tools operate locally on the Home Assistant filesystem — no SSH needed.
"""

import asyncio
import base64
import glob
import logging
import os
import re
import subprocess
import threading
import time

import yaml

log = logging.getLogger("esphome-mcp")

ESPHOME_DIR = os.environ.get("ESPHOME_DIR", "/config/esphome")
ESPHOME_BIN = "esphome"

FORBIDDEN_FILES = {"secrets.yaml", ".secret.yaml"}

# How long compile/flash wait synchronously before returning a pollable
# handle. Must stay comfortably under the MCP client's request timeout so a
# long build returns a handle instead of erroring with a transport timeout.
SYNC_WAIT_WINDOW = 45
# Hard server-side caps on background builds.
COMPILE_TIMEOUT = 600
FLASH_TIMEOUT = 900

# Firmware version check (esphome_flash): native API port and budgets.
ESPHOME_API_PORT = 6053
CONFIG_DUMP_TIMEOUT = 60  # `esphome config --show-secrets`
VERSION_CHECK_TIMEOUT = 8  # native API connect + device_info

# Every ESPHome upload/log target is resolved from the device config by
# ESPHome itself (use_address, static IP, <name>.local, MQTT IP lookup).
# This is what the ESPHome Device Builder passes too; it never shows the
# interactive serial/OTA chooser, which crashes with EOFError under MCP
# (no stdin).
OTA_ARGS = ["--device", "OTA"]

_LOCAL_VERSION: str | None = None

# Background build registry, keyed by device YAML filename.
_BUILDS: dict[str, dict] = {}
_BUILDS_LOCK = threading.Lock()


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


# ---------------------------------------------------------------------------
# Background builds (compile/flash) — long jobs run in a thread so a slow
# build returns a pollable handle instead of hitting the MCP request timeout.
# ---------------------------------------------------------------------------
def _build_worker(
    key: str, cmd: list[str], timeout: int, pre_check=None
) -> None:
    job = _BUILDS[key]
    if pre_check is not None:
        # Runs in this worker thread (never on the event loop). Its lines
        # are kept separately so they stay visible above any output tail.
        try:
            preamble = list(pre_check())
        except Exception as e:  # best effort, never block the build
            preamble = [f"[pre-flight check skipped: {e}]"]
        with _BUILDS_LOCK:
            job["preamble"] = preamble
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=ESPHOME_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as e:
        with _BUILDS_LOCK:
            job["status"] = "failed"
            job["returncode"] = -1
            job["lines"].append(f"Command not found: {e}")
            job["finished"] = time.time()
        return

    killer = threading.Timer(timeout, proc.kill)
    killer.start()
    try:
        for line in proc.stdout:
            with _BUILDS_LOCK:
                job["lines"].append(line.rstrip("\n"))
        proc.wait()
    finally:
        killer.cancel()

    with _BUILDS_LOCK:
        job["returncode"] = proc.returncode
        job["finished"] = time.time()
        if proc.returncode == 0:
            job["status"] = "done"
        elif proc.returncode is not None and proc.returncode < 0:
            job["status"] = "failed"
            job["lines"].append(f"[killed: exceeded {timeout}s timeout]")
        else:
            job["status"] = "failed"


def _start_build(
    key: str, cmd: list[str], timeout: int, pre_check=None
) -> dict:
    """Start (or reuse a running) background build for `key`.

    `pre_check` is an optional callable returning lines to show above the
    build output (e.g. the firmware version check); it runs in the worker
    thread before the command starts.
    """
    with _BUILDS_LOCK:
        job = _BUILDS.get(key)
        if job and job["status"] == "running":
            return job
        job = {
            "status": "running",
            "lines": [],
            "preamble": [],
            "returncode": None,
            "cmd": cmd,
            "started": time.time(),
            "finished": None,
        }
        _BUILDS[key] = job
    threading.Thread(
        target=_build_worker,
        args=(key, cmd, timeout, pre_check),
        daemon=True,
    ).start()
    return job


def _job_snapshot(job: dict) -> tuple[str, str, int | None, str]:
    with _BUILDS_LOCK:
        return (
            job["status"],
            "\n".join(job["lines"]),
            job["returncode"],
            "\n".join(job["preamble"]),
        )


def _with_preamble(preamble: str, text: str) -> str:
    return f"{preamble}\n\n{text}" if preamble else text


def _await_or_handle(key: str, job: dict, label: str) -> str:
    """Wait up to SYNC_WAIT_WINDOW for completion, else return a poll handle."""
    deadline = time.time() + SYNC_WAIT_WINDOW
    while time.time() < deadline:
        status, _, _, _ = _job_snapshot(job)
        if status != "running":
            break
        time.sleep(1)

    status, output, rc, preamble = _job_snapshot(job)
    if status == "running":
        elapsed = int(time.time() - job["started"])
        tail = "\n".join(output.splitlines()[-15:])
        return _with_preamble(
            preamble,
            f"{label} still running ({elapsed}s elapsed). The build continues "
            f"in the background — poll it with "
            f"esphome_build_status(device='{key}').\n\n"
            f"--- output so far (tail) ---\n{tail}",
        )
    if rc != 0:
        return _with_preamble(preamble, f"Command failed (exit {rc}):\n{output}")
    return _with_preamble(preamble, output)


# ---------------------------------------------------------------------------
# YAML + version helpers
# ---------------------------------------------------------------------------
class _LenientLoader(yaml.SafeLoader):
    """SafeLoader that tolerates ESPHome's custom tags.

    `!secret name` becomes the literal string "!secret name"; every other
    tag (!lambda, !include, !extend, !remove, ...) maps to None. Only scalar
    metadata is read through this loader, never executed.
    """


def _secret_constructor(loader, node):
    return f"!secret {loader.construct_scalar(node)}"


def _ignore_unknown_tag(loader, tag_suffix, node):
    return None


_LenientLoader.add_constructor("!secret", _secret_constructor)
_LenientLoader.add_multi_constructor("!", _ignore_unknown_tag)


def _local_esphome_version() -> str:
    """ESPHome version shipped in this image (== the base-image tag)."""
    global _LOCAL_VERSION
    if _LOCAL_VERSION is None:
        try:
            from esphome.const import __version__

            _LOCAL_VERSION = str(__version__)
        except Exception:
            out = _run([ESPHOME_BIN, "version"], timeout=60)
            match = re.search(r"Version:\s*(\S+)", out)
            _LOCAL_VERSION = match.group(1) if match else "unknown"
    return _LOCAL_VERSION


def _version_tuple(version: str) -> tuple[int, ...] | None:
    """Comparable tuple of the leading numeric groups (2026.8.1 -> (2026, 8, 1)).

    Suffixes such as `-dev`, `b2` are ignored. Returns None if no number is found.
    """
    nums = re.findall(r"\d+", version or "")[:3]
    if not nums:
        return None
    return tuple(int(n) for n in nums) + (0,) * (3 - len(nums))


def _device_config(yaml_path: str) -> dict | None:
    """Fully resolved config (packages, substitutions, secrets) or None.

    Uses `esphome config --show-secrets` so the result is exactly what
    ESPHome itself would use. Secrets stay inside this process.
    """
    try:
        result = subprocess.run(
            [ESPHOME_BIN, "config", yaml_path, "--show-secrets"],
            capture_output=True,
            text=True,
            timeout=CONFIG_DUMP_TIMEOUT,
            cwd=ESPHOME_DIR,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        log.info("Config dump for %s failed: %s", yaml_path, e)
        return None
    if result.returncode != 0:
        return None
    try:
        data = yaml.load(result.stdout, Loader=_LenientLoader)
    except yaml.YAMLError as e:
        log.info("Config dump for %s not parseable: %s", yaml_path, e)
        return None
    return data if isinstance(data, dict) else None


def _device_address(config: dict) -> str | None:
    """Network address ESPHome would use for the device (like CORE.address)."""
    for section in ("wifi", "ethernet"):
        net = config.get(section)
        if not isinstance(net, dict):
            continue
        if net.get("use_address"):
            return str(net["use_address"])
        manual = net.get("manual_ip")
        if isinstance(manual, dict) and manual.get("static_ip"):
            return str(manual["static_ip"])
    name = (config.get("esphome") or {}).get("name")
    return f"{name}.local" if name else None


def _device_firmware_version(yaml_path: str) -> str | None:
    """Ask the running device for its ESPHome version via the native API.

    Best effort: returns None (never raises) when the device has no `api:`,
    is unreachable, or the check exceeds VERSION_CHECK_TIMEOUT.
    """
    config = _device_config(yaml_path)
    if not config or "api" not in config:
        return None
    address = _device_address(config)
    if not address:
        return None
    api = config.get("api") or {}
    encryption = api.get("encryption") if isinstance(api, dict) else None
    key = encryption.get("key") if isinstance(encryption, dict) else None

    try:
        from aioesphomeapi import APIClient
    except ImportError:
        return None

    async def fetch() -> str | None:
        client = APIClient(
            address,
            ESPHOME_API_PORT,
            None,
            noise_psk=str(key) if key else None,
            client_info="esphome-mcp",
        )
        await client.connect(login=False)
        try:
            info = await client.device_info()
            return info.esphome_version or None
        finally:
            await client.disconnect(force=True)

    try:
        return asyncio.run(asyncio.wait_for(fetch(), VERSION_CHECK_TIMEOUT))
    except Exception as e:  # noqa: BLE001 - any failure just skips the check
        log.info(
            "Firmware version check for %s skipped: %s: %s",
            address,
            type(e).__name__,
            e,
        )
        return None


def _flash_preamble(yaml_path: str) -> list[str]:
    """Lines shown above flash output: versions + downgrade warning (#8)."""
    local = _local_esphome_version()
    device = _device_firmware_version(yaml_path)
    lines = [f"ESPHome add-on: {local} | device firmware: {device or 'unknown'}"]
    local_t, device_t = _version_tuple(local), _version_tuple(device or "")
    if local_t and device_t and device_t > local_t:
        lines.append(
            f"WARNING: the device runs a NEWER ESPHome ({device}) than this "
            f"add-on ({local}) — flashing will DOWNGRADE its firmware. Update "
            "the add-on first, or flash from the newer ESPHome Device Builder."
        )
    return lines


def _resolve_substitutions(value: str, subs: dict) -> str:
    """Resolve ${var} / $var references in a string against the subs map.

    Unknown references are left untouched (so the caller's '$' guards still
    fire for genuinely unresolved names).
    """
    if not isinstance(value, str) or "$" not in value:
        return value

    def repl(match):
        key = match.group(1) or match.group(2)
        replacement = subs.get(key)
        return str(replacement) if replacement is not None else match.group(0)

    return re.sub(r"\$\{(\w+)\}|\$(\w+)", repl, value)


def _parse_device_info(yaml_path: str) -> dict:
    """Parse basic device info from a YAML file."""
    try:
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.load(f, Loader=_LenientLoader) or {}

        subs = data.get("substitutions", {}) or {}
        esphome_section = data.get("esphome", {}) or {}
        name = _resolve_substitutions(
            esphome_section.get("name", "unknown"), subs
        )
        friendly_name = _resolve_substitutions(
            esphome_section.get("friendly_name", ""), subs
        )
        return {
            "name": name,
            "friendly_name": friendly_name,
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

    lines = [f"ESPHome Devices (add-on ESPHome {_local_esphome_version()}):", ""]
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
    """Compile ESPHome firmware for a device (runs in the background)."""
    yaml_path = _device_yaml_path(device)
    if not os.path.isfile(yaml_path):
        return f"Device config not found: {yaml_path}"
    key = os.path.basename(yaml_path)
    job = _start_build(
        key,
        [ESPHOME_BIN, "compile", yaml_path],
        COMPILE_TIMEOUT,
        pre_check=lambda: [f"ESPHome add-on: {_local_esphome_version()}"],
    )
    return _await_or_handle(key, job, "Compile")


def flash(device: str) -> str:
    """OTA flash a device (runs in the background).

    `--device OTA` makes ESPHome resolve the upload target from the config
    (use_address / static IP / <name>.local) exactly like the ESPHome Device
    Builder does, so it never falls into the interactive serial/OTA chooser
    (EOFError under MCP). Before the build starts, the device's running
    firmware version is queried and a downgrade warning is emitted if the
    device runs a newer ESPHome than this add-on.
    """
    yaml_path = _device_yaml_path(device)
    if not os.path.isfile(yaml_path):
        return f"Device config not found: {yaml_path}"
    cmd = [ESPHOME_BIN, "run", yaml_path, "--no-logs", *OTA_ARGS]
    key = os.path.basename(yaml_path)
    job = _start_build(
        key, cmd, FLASH_TIMEOUT, pre_check=lambda: _flash_preamble(yaml_path)
    )
    return _await_or_handle(key, job, "Flash")


def build_status(device: str) -> str:
    """Return the status and output of the latest compile/flash for a device."""
    key = os.path.basename(_resolve_device(device))
    with _BUILDS_LOCK:
        job = _BUILDS.get(key)
        if job is None:
            return f"No build found for '{key}'. Start one with esphome_compile."
        status = job["status"]
        output = "\n".join(job["lines"])
        preamble = "\n".join(job["preamble"])
        rc = job["returncode"]
        started = job["started"]
        finished = job["finished"]

    if status == "running":
        elapsed = int(time.time() - started)
        tail = "\n".join(output.splitlines()[-30:])
        return _with_preamble(
            preamble,
            f"Build running ({elapsed}s elapsed).\n\n--- output (tail) ---\n{tail}",
        )

    duration = int((finished or time.time()) - started)
    return _with_preamble(
        preamble, f"Build {status} (exit {rc}, took {duration}s):\n{output}"
    )


LOG_SNAPSHOT_SECONDS = 15


def logs(device: str, num_lines: int = 50) -> str:
    """Get a snapshot of recent logs from an ESPHome device.

    Logs are streamed over the network (`--device OTA` -> native API or
    web_server, resolved from the config) for LOG_SNAPSHOT_SECONDS, then the
    stream is cut with `timeout`. Exit 124 from `timeout` is the normal end of
    a snapshot, not an error.
    """
    yaml_path = _device_yaml_path(device)
    if not os.path.isfile(yaml_path):
        return f"Device config not found: {yaml_path}"
    cmd = [
        "timeout",
        str(LOG_SNAPSHOT_SECONDS),
        ESPHOME_BIN,
        "logs",
        yaml_path,
        *OTA_ARGS,
    ]
    log.info("Running: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=LOG_SNAPSHOT_SECONDS + 15,
            cwd=ESPHOME_DIR,
        )
    except subprocess.TimeoutExpired:
        return "Log snapshot did not finish in time"
    except FileNotFoundError as e:
        return f"Command not found: {e}"

    output = result.stdout
    if result.stderr:
        output += "\n" + result.stderr
    output = output.strip()
    if result.returncode not in (0, 124):
        return f"Command failed (exit {result.returncode}):\n{output}"
    if not output:
        return f"No log output received in {LOG_SNAPSHOT_SECONDS}s."
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
