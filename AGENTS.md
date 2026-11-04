# AGENTS.md

Instructions for AI coding agents (Claude Code, Codex and others) working in this repository. `CLAUDE.md` only imports
this file, so edit this one. [README.md](README.md) describes the project for people; this file lists what the code
alone does not tell you.

<!-- repo-init:start -->
## Repository Info

- **Company:** Berrevoets Systems
- **Author:** Bert Berrevoets
- **Contact:** <bert@berrevoets.net>
- **Remote:** <https://github.com/bberrevoets/ha-addon-esphome-mcp> (public)

## Workflow Rules

- **GitHub Flow:** `main` is the default and only long-lived branch. It is protected by the ruleset "Protect main":
  no direct pushes, no deletion, changes only through a pull request, and all PR conversations must be resolved
  before merging. Merged head branches are deleted automatically.
- After cloning, run `git config pull.rebase true` once, so `git pull` rebases instead of creating merge commits.
- Work on a branch per topic, push it, and open a PR to `main` only when Bert asks for it, assigned to him
  (`gh pr create --assignee bberrevoets`). PRs are squash-merged. After a merge: switch to `main` and pull, then delete the
  local branch with `git branch -D <branch>` (`-d` refuses after a squash merge) once
  `gh pr view <branch> --json state,headRefOid` shows `MERGED` and the same commit as `git rev-parse <branch>`.
- **"Update the documentation"** means `AGENTS.md`, the project's own `README.md` files (not vendored third-party ones)
  and `CHANGELOG.md`; then commit and push.
- [CHANGELOG.md](CHANGELOG.md) follows Keep a Changelog: the Attributors list at the top, and one `Author: *Name*`
  line under each section heading (`### Added`, `### Changed`, ...).
- Markdown must pass `markdownlint-cli2 "**/*.md"` with [.markdownlint.json](.markdownlint.json) (180-character
  lines) before every commit.
- Binaries go through Git LFS: every `filter=lfs` pattern in `.gitattributes` — the standard set (PDF, ZIP, PNG,
  JPEG, STEP/STP, STL, 3MF, F3D/F3Z) plus any pattern this repository adds. Add a pattern there before committing
  another binary type (GIF, BMP, ...). The patterns are lowercase and match `X.PNG` only where `core.ignorecase` is
  true (Windows, macOS); on a case-sensitive system check a new binary with `git check-attr filter -- <file>` before
  committing it.
- Commit messages use the conventional style (`feat:`, `fix:`, `docs:`, `chore:`).
<!-- repo-init:end -->

## Project Overview

Home Assistant custom add-on that runs an MCP (Model Context Protocol)
server for ESPHome operations. Claude Code connects to it over HTTP
instead of SSH, getting direct access to ESPHome CLI and the
`/config/esphome/` filesystem on the HA host.

Public and used by others: people add this repository in Home Assistant, and their instances follow `main`. Bert's own
install is the store add-on `c9d6b5b8_esphome-mcp` on the HA host `homebox`.

## Repository Layout

- `repository.yaml` — HA add-on repository metadata
- `scripts/deploy-dev.sh` — push the working tree to the HA host as a local
  dev add-on (see Building / Testing)
- `scripts/render-icons.py` — rasterize `icon.svg`/`logo.svg` to PNG
- `.github/workflows/esphome-bump.yml` + `.github/scripts/bump_esphome.py` —
  daily check for a new stable ESPHome release; opens/refreshes the
  `chore/esphome-bump` PR that bumps build.yaml, config.yaml and the CHANGELOG
- `esphome-mcp/` — The add-on
  - `config.yaml` — HA add-on manifest (name, version, ports, options)
  - `build.yaml` — Multi-arch Docker build config
  - `Dockerfile` — built on the official ESPHome (Debian/glibc) image
  - `run.sh` — Add-on entry point (reads config, starts server)
  - `requirements.txt` — Python dependencies (mcp, uvicorn, pyyaml)
  - `server/` — Python package
    - `main.py` — FastMCP app, tool registration, uvicorn entry point
    - `tools.py` — All tool implementations (no SSH, local filesystem)
    - `auth.py` — Bearer token middleware (fails closed on an empty token)
  - `tests/` — pytest unit tests (local only, not in the image);
    `requirements-dev.txt` installs the server deps plus pytest
  - `DOCS.md` — Add-on documentation page shown in HA UI
  - `icon.svg` / `icon.png`, `logo.svg` / `logo.png` — presentation files
    (HA reads the PNGs; the SVGs are the sources)
  - `CHANGELOG.md` — Add-on changelog; must live here (next to
    `config.yaml`) or HA shows "No changelog found" on update. The
    root `CHANGELOG.md` points to this file and only records repository
    changes that do not ship in the add-on

## Cross-Repository

- **esphome** (`../esphome`, `bberrevoets/esphome`, private): the device configurations, which reach this add-on through
  their `.mcp.json`. Tool names and behaviour come from here, so check that repo's docs when a tool changes.

## Conventions

- **Auth**: Bearer token in `Authorization` header, compared with
  `secrets.compare_digest`; an empty token answers 503 (fail closed). If not
  configured, `run.sh` generates one, persists it to `/data/auth_token` and
  saves it as the `auth_token` option via the Supervisor API
  (`hassio_api: true`) so it shows in the Configuration tab. The log only
  shows a fingerprint, except as fallback when saving the option fails
- **Transport**: Streamable HTTP on port 8099 at `/mcp`; `GET /health`
  (unauthenticated) backs the image `HEALTHCHECK`. Never use
  `HEALTHCHECK NONE`: it leaves `Test: ["NONE"]` in the metadata and the
  Supervisor then waits forever for a healthy event ("Starting")
- **Secrets**: `secrets.yaml` is explicitly rejected in push/pull tools
- **Confinement**: every caller-supplied path goes through
  `_confined_path()` (realpath check against `ESPHOME_DIR`) — push/pull and
  `_device_yaml_path()`. Never `os.path.join(ESPHOME_DIR, user_input)` directly
- **Bulk reads**: `esphome_pull_files` / `esphome_pull_fonts` need
  `filenames` or `all=true`. FastMCP drops unknown arguments silently, so
  "no arguments" must never mean "everything"
- **Lenient YAML**: `_LenientLoader` only reads metadata; it maps unknown
  tags to None and drops `<<: !include` merge keys (`flatten_mapping`)
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
  git and would get an LFS pointer file instead of an image. This overrides the
  LFS rule above: `.gitattributes` unsets the filter for everything under
  `esphome-mcp/`, after the repo-init block, so keep that line
- **Merges reach users**: a change to `version:` in `config.yaml` offers an
  update to everyone who installed the add-on. Changes that leave `version:`
  alone stay invisible to them, so docs and tooling PRs must stay out of it
- **Two changelogs**: add-on releases go in `esphome-mcp/CHANGELOG.md`, which HA
  shows in the update dialog. Keep `[Unreleased]` out of that file:
  `bump_esphome.py` inserts each release before the first `## [` heading.
  Changes that do not ship in the add-on go in the root `CHANGELOG.md`

## Building / Testing

The add-on is built by HA Supervisor when installed. Three ways to test a
change before it is released, cheapest first. None of them publishes
anything: users' HA instances only follow `main`, so feature branches are
always safe to push.

Run the unit tests first (no Docker, no ESPHome needed):

```bash
python -m venv .venv && .venv/bin/pip install -r esphome-mcp/requirements-dev.txt
cd esphome-mcp && ../.venv/bin/python -m pytest
```

On Windows the venv folder is `.venv/Scripts/` instead of `.venv/bin/`.

Lint with `npx markdownlint-cli2 "**/*.md"`; `.markdownlint-cli2.jsonc` skips what `.gitignore` skips, such as `.venv/`.

1. **Local Docker build** (server smoke test on the dev machine):

   ```bash
   cd esphome-mcp
   BASE=$(sed -n 's/^  amd64: //p' build.yaml)
   docker build --build-arg BUILD_FROM="$BASE" -t esphome-mcp .
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
   `server/`). `/data` (token, caches) survives rebuilds. On the host, `ha addons` is deprecated in favour of `ha apps`,
   and the store refresh is `ha store reload`. The Supervisor refuses `rebuild` when the staged version differs from the
   installed one: use `update`.

3. **Branch as a second repository** (no SSH needed; also for other
   testers): push the branch, then add
   `https://github.com/bberrevoets/ha-addon-esphome-mcp#<branch>` as another
   repository in HA. It installs as a separate add-on (own repository hash)
   — change its host port under *Network* before starting. Each iteration:
   push → *Check for updates* → Update/Rebuild. Remove the repository when
   done.

## Releasing

ESPHome-only bumps arrive automatically as a `chore/esphome-bump` PR (see
`esphome-bump.yml`); review the ESPHome release notes, then merge. Also diff
the official add-on's `docker/ha-addon-rootfs/etc/s6-overlay/s6-rc.d/esphome/run`
between the old and new ESPHome tag: `run.sh` mirrors its exports, and new
ones are not listed as breaking changes (2026.10.0 added three toolchain and
cache paths). A daily run rebuilds the bump branch from `main`, so merge soon
after pushing your own commits to it. Renovate was rejected for this: it cannot move `config.yaml`, `build.yaml` and
the CHANGELOG in lockstep.

Codex does not review bot PRs, so check them by hand:

- Breaking changes: the GitHub release body, or `https://esphome.io/changelog/<version>.html` when it only links there.
- `gh api repos/esphome/esphome/compare/<old>...<new>` stops at 300 files. Fetch `requirements.txt` per tag and diff
  it, and filter the compare output for `docker/` files.
- Smoke test with Docker running: the local build above, `pip3 check` in the image, then an MCP client from the repo
  `.venv` runs initialize, validate and compile on an ESP8266 config. The success line is "Successfully compiled
  program"; a test YAML with `api:` also needs `wifi:`; `docker exec` does not see the exports from `run.sh`, so read
  `/proc/1/environ`.

GitHub releases (`vX.Y.Z`, tag on the merge commit) are published only on Bert's explicit go. Follow the earlier
releases: why, what to check in configs, how to update. A reinstall wipes `/data`, so an auto-generated token changes.

For a manual release:

1. Bump the base-image tag in `esphome-mcp/build.yaml` to the latest stable
   ESPHome (`ghcr.io/esphome/esphome:<tag>`, amd64 + arm64 are published).
2. Bump `version:` in `esphome-mcp/config.yaml`.
3. Add an entry to `esphome-mcp/CHANGELOG.md` (the copy HA displays) and
   update README/DOCS if tools changed.
4. Merge to `main` — HA picks up the new version from the repository.
   Users must reinstall (not just restart) when the base image changed. HA caches the repository, so they first use
   *Check for updates* in the add-on store; option-only changes just need a restart.

## Deployment

Add `https://github.com/bberrevoets/ha-addon-esphome-mcp` as a custom
add-on repository in Home Assistant, then install and start the add-on.
