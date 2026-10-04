#!/usr/bin/env python3
"""Bump the add-on to a newer ESPHome release.

The base-image tag in esphome-mcp/build.yaml IS the ESPHome version the
add-on ships, and every bump must move three files in lockstep (see
CLAUDE.md, "Releasing"):

- esphome-mcp/build.yaml   ghcr.io/esphome/esphome:<tag> for every arch
- esphome-mcp/config.yaml  version: patch bump
- esphome-mcp/CHANGELOG.md new release entry (the copy HA displays)

Usage: bump_esphome.py <latest-esphome-tag>

Writes `bumped=true|false`, `esphome=<tag>` and `version=<addon version>`
to $GITHUB_OUTPUT when set. Exits 0 without changes when already current.
"""

from __future__ import annotations

import datetime
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD_YAML = ROOT / "esphome-mcp" / "build.yaml"
CONFIG_YAML = ROOT / "esphome-mcp" / "config.yaml"
CHANGELOG = ROOT / "esphome-mcp" / "CHANGELOG.md"

IMAGE_RE = re.compile(r"(ghcr\.io/esphome/esphome:)([0-9][0-9.]*)")
VERSION_RE = re.compile(r"^version:\s*(\d+)\.(\d+)\.(\d+)\s*$", re.MULTILINE)


def _vtuple(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version))


def _output(**values: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        for key, value in values.items():
            f.write(f"{key}={value}\n")


def main() -> int:
    if len(sys.argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
        print("usage: bump_esphome.py <YYYY.M.P>", file=sys.stderr)
        return 2
    latest = sys.argv[1]

    build = BUILD_YAML.read_text(encoding="utf-8")
    current_tags = {m.group(2) for m in IMAGE_RE.finditer(build)}
    if not current_tags:
        print(f"no ghcr.io/esphome/esphome tag found in {BUILD_YAML}", file=sys.stderr)
        return 1
    current = max(current_tags, key=_vtuple)
    if _vtuple(latest) <= _vtuple(current) and len(current_tags) == 1:
        print(f"ESPHome {current} is current (latest release {latest})")
        _output(bumped="false", esphome=current)
        return 0

    config = CONFIG_YAML.read_text(encoding="utf-8")
    match = VERSION_RE.search(config)
    if not match:
        print(f"no semantic version: line in {CONFIG_YAML}", file=sys.stderr)
        return 1
    major, minor, patch = (int(g) for g in match.groups())
    new_version = f"{major}.{minor}.{patch + 1}"

    BUILD_YAML.write_text(IMAGE_RE.sub(rf"\g<1>{latest}", build), encoding="utf-8")
    CONFIG_YAML.write_text(
        VERSION_RE.sub(f"version: {new_version}", config, count=1), encoding="utf-8"
    )

    today = datetime.date.today().isoformat()
    entry = (
        f"## [{new_version}] - {today}\n\n"
        "### Changed\n\n"
        "Author: *GitHub Actions (esphome-bump)*\n\n"
        f"- Base image bumped to `ghcr.io/esphome/esphome:{latest}` (was `{current}`).\n"
        f"  Release notes: <https://github.com/esphome/esphome/releases/tag/{latest}>.\n"
        "  Reinstall the add-on (not just restart) to pick up the new base image.\n\n"
    )
    changelog = CHANGELOG.read_text(encoding="utf-8")
    first = changelog.find("\n## [")
    if first == -1:
        print(f"no release heading found in {CHANGELOG}", file=sys.stderr)
        return 1
    CHANGELOG.write_text(
        changelog[: first + 1] + entry + changelog[first + 1 :], encoding="utf-8"
    )

    print(f"Bumped ESPHome {current} -> {latest}, add-on {match.group(0)!r} -> {new_version}")
    _output(bumped="true", esphome=latest, version=new_version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
