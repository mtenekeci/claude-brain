# Claude Brain — Vault Operating Instructions

This vault is managed by Claude using the claude-brain plugin.

## Vault structure

- `_system/` — system files managed by the plugin, do not delete
- `projects/<slug>/` — one isolated folder per project

## Per-project files

- `context.md` — compiled living knowledge, hard cap 150 lines
- `log.md` — append-only session log, only last entry loaded at session start

## Rules for Claude

- Never load a project folder other than the one relevant to the current session
- `context.md` hard cap is 150 lines — compress older content, never delete
- `log.md` is append-only — never modify past entries
- After writing to a project, always update `last-active` in `_system/project-index.md`

## Tiered loading

- Tier 1 (always): `context.md` in full + last `log.md` entry (~160 lines)
- Tier 2 (before architectural decisions): last 5 `log.md` entries (+40 lines)
- Tier 3 (tracing a specific historical problem): full `log.md`

Per-project automation lives in the `CLAUDE.md` written to each project's code folder.
