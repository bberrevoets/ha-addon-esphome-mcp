# Changelog

The add-on's changelog lives in [esphome-mcp/CHANGELOG.md](esphome-mcp/CHANGELOG.md).

Home Assistant only displays an add-on's changelog when the file sits next
to the add-on's `config.yaml`, so that copy is the canonical one and is
what the Supervisor shows in the update dialog.

This file only records repository changes that do not ship in the add-on, such as the agent setup and lint.

## Attributors

- **Bert Berrevoets** (Berrevoets Systems, <bert@berrevoets.net>) — author and maintainer
- **Claude Opus 5.5** — co-author (see the commit trailers)

## [Unreleased]

### Added

Author: *Bert Berrevoets*

- CI on pull requests: unit tests with the Python of the add-on image, and Markdown lint.

### Changed

Author: *Bert Berrevoets*

- AI agent setup (2026-11): the instructions moved from `CLAUDE.md` to `AGENTS.md`, the single source for Claude Code,
  Codex and other agents, with a `CLAUDE.md` stub that imports it. Repo-init blocks in `.gitignore` and
  `.gitattributes`, an override that keeps everything under `esphome-mcp/` out of Git LFS, a Conventions section in
  `README.md`, and `.markdownlint-cli2.jsonc` so the lint gate skips `.venv/`. `AGENTS.md` also gained the bump-PR
  checks, release rules and HA CLI notes that only lived in agent memory.
