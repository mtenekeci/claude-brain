# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Claude Code plugin that gives Claude a persistent Obsidian second brain. Installed via the Claude Code plugin marketplace; exposes a `/brain` skill with subcommands: `init`, `load`, `sync`, `status`, `config`, `remove`, `disconnect`.

## Key files

| Path | Role |
|---|---|
| `skills/brain/SKILL.md` | Full behavioral spec for all `/brain` subcommands — the authoritative source of truth |
| `hooks/session-start.sh` | Injects vault file paths into context before first prompt |
| `hooks/session-end.sh` | Writes a git-enriched auto-close log entry when session ends without a manual sync |
| `hooks/precompact.sh` | Writes a checkpoint entry + tells Claude to fill in details before `/compact` |
| `hooks/post-tool-use.sh` | Counts source file reads; reminds Claude to update vault Architecture every 3 reads |
| `templates/CLAUDE.md` | Template written into each user project on `/brain init` |
| `templates/context.md` | Template for the per-project `context.md` vault file |
| `templates/BRAIN.md` | Template for the vault-level operating instructions at `_system/BRAIN.md` |
| `.claude-plugin/plugin.json` | Plugin manifest (name, version, author) |
| `.claude-plugin/marketplace.json` | Marketplace listing schema |

## Architecture

- **Config**: `~/.claude/brain.config` — single JSON file `{ "vault": "/abs/path" }`. All hooks and the skill derive `VAULT_ROOT` from it.
- **Vault structure**: `<VAULT_ROOT>/_system/` (BRAIN.md + project-index.md) and `<VAULT_ROOT>/projects/<slug>/` (context.md + log.md).
- **Slug**: last path segment of the vault entry for that project; extracted from the `vault:` line in the project's `CLAUDE.md`.
- **Hooks are installed into the user's project** `.claude/settings.json` (not this repo) during `/brain init`. The hook scripts themselves live here and are referenced by absolute path.
- **Tiered vault loading**: Tier 1 = context.md + last log entry (~160 lines); Tier 2 = last 5 log entries (before architectural decisions); Tier 3 = full log (historical tracing).
- **Wikilinks**: all vault writes must use Obsidian `[[wikilink]]` syntax — the skill enforces this so Obsidian's graph view stays connected.

## Working on this plugin

When editing `SKILL.md`, check all subcommand sections for consistency — they share derived constants (`VAULT_ROOT`, `PLUGIN_DIR`, `VAULT_SYSTEM`, `VAULT_PROJECTS`) defined once at the top of the skill.

When editing hooks, note that `session-start.sh` and `post-tool-use.sh` output text that Claude reads as instructions; `session-end.sh` and `precompact.sh` write directly to `log.md` and then output text directing Claude to enrich the entry.

Version is tracked in `.claude-plugin/plugin.json` — bump on any user-facing change.
