"""ESPHome MCP tool implementations.

All tools operate locally on the Home Assistant filesystem — no SSH needed.
"""

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
def _build_worker(key: str, cmd: list[str], timeout: int) -> None:
    job = _BUILDS[key]
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


def _start_build(key: str, cmd: list[str], timeout: int) -> dict:
    """Start (or reuse a running) background build for `key`."""
    with _BUILDS_LOCK:
        job = _BUILDS.get(key)
        if job and job["status"] == "running":
            return job
        job = {
            "status": "running",
            "lines": [],
            "returncode": None,
            "cmd": cmd,
            "started": time.time(),
            "finished": None,
        }
        _BUILDS[key] = job
    threading.Thread(
        target=_build_worker, args=(key, cmd, timeout), daemon=True
    ).start()
    return job


def _job_snapshot(job: dict) -> tuple[str, str, int | None]:
    with _BUILDS_LOCK:
        return job["status"], "\n".join(job["lines"]), job["returncode"]


def _await_or_handle(key: str, job: dict, label: str) -> str:
    """Wait up to SYNC_WAIT_WINDOW for completion, else return a poll handle."""
    deadline = time.time() + SYNC_WAIT_WINDOW
    while time.time() < deadline:
        status, _, _ = _job_snapshot(job)
        if status != "running":
            break
        time.sleep(1)

    status, output, rc = _job_snapshot(job)
    if status == "running":
        elapsed = int(time.time() - job["started"])
        tail = "\n".join(output.splitlines()[-15:])
        return (
            f"{label} still running ({elapsed}s elapsed). The build continues "
            f"in the background — poll it with "
            f"esphome_build_status(device='{key}').\n\n"
            f"--- output so far (tail) ---\n{tail}"
        )
    if rc != 0:
        return f"Command failed (exit {rc}):\n{output}"
    return output


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
            class SecretLoader(yaml.SafeLoader):
                pass

            def secret_constructor(loader, node):
                return f"!secret {loader.construct_scalar(node)}"

            SecretLoader.add_constructor("!secret", secret_constructor)

            # ESPHome configs carry many custom tags (!lambda, !include,
            # !extend, !remove, ...). We only need scalar metadata here, so
            # map any unrecognised tag to None instead of crashing the load.
            def _ignore_unknown(loader, tag_suffix, node):
                return None

            SecretLoader.add_multi_constructor("!", _ignore_unknown)
            data = yaml.load(f, Loader=SecretLoader) or {}

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
    """Compile ESPHome firmware for a device (runs in the background)."""
    yaml_path = _device_yaml_path(device)
    if not os.path.isfile(yaml_path):
        return f"Device config not found: {yaml_path}"
    key = os.path.basename(yaml_path)
    job = _start_build(key, [ESPHOME_BIN, "compile", yaml_path], COMPILE_TIMEOUT)
    return _await_or_handle(key, job, "Compile")


def flash(device: str) -> str:
    """OTA flash a device (runs in the background)."""
    yaml_path = _device_yaml_path(device)
    if not os.path.isfile(yaml_path):
        return f"Device config not found: {yaml_path}"
    # Force OTA and run non-interactively. The add-on container may also expose
    # USB serial adapters (/dev/ttyUSB*), which makes `esphome run` prompt for
    # an upload target and crash with EOFError (no stdin under MCP). Target the
    # device's mDNS name so the upload always goes Over-The-Air.
    cmd = [ESPHOME_BIN, "run", yaml_path, "--no-logs"]
    name = _parse_device_info(yaml_path).get("name", "")
    if name and name not in ("unknown", "error") and "$" not in name:
        cmd += ["--device", f"{name}.local"]
    key = os.path.basename(yaml_path)
    job = _start_build(key, cmd, FLASH_TIMEOUT)
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
        rc = job["returncode"]
        started = job["started"]
        finished = job["finished"]

    if status == "running":
        elapsed = int(time.time() - started)
        tail = "\n".join(output.splitlines()[-30:])
        return f"Build running ({elapsed}s elapsed).\n\n--- output (tail) ---\n{tail}"

    duration = int((finished or time.time()) - started)
    return f"Build {status} (exit {rc}, took {duration}s):\n{output}"


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
