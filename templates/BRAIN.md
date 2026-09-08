# Claude Brain — Vault Operating Instructions

This vault is managed by Claude using the claude-brain plugin.

## Vault structure

- `_system/` — system files managed by the plugin, do not delete
- `projects/<slug>/` — one isolated folder per project: `context.md`, `architecture.md`, `log.md`, and (code projects) `codemap.md`
- `concepts/` — atomic notes for reusable architectural entities (libraries, named subsystems, infra, decisions), shared across projects; hub nodes in the graph view

## Per-project files

- `context.md` — compiled living knowledge, hard cap 150 lines
- `architecture.md` — living architecture reference, no line cap
- `log.md` — append-only session log, only last entry loaded at session start
- `codemap.md` — generated + curated map of the project's code folder (files, exported symbols, imports, manifest deps); a `.brain/` folder alongside it holds the machine-readable layer the generated block is rendered from

## Rules for Claude

- Never load a project folder other than the one relevant to the current session
- `context.md` hard cap is 150 lines — compress older content, never delete
- `log.md` is append-only — never modify past entries
- After writing to a project, always update `last-active` in `_system/project-index.md`
- Before creating a note in `concepts/`, check whether one already exists for that entity (by slug) — append to its `## Used by` instead of creating a duplicate. This is how cross-project sharing works.
- Use `brain graph find|near|path|top|lint` to query the project's knowledge graph (built from `context.md`/`architecture.md` links and concept notes) instead of re-reading every file by hand

## Tiered loading

- Tier 1 (always): `context.md` in full + last `log.md` entry (~160 lines)
- Tier 2 (before architectural decisions): last 5 `log.md` entries (+40 lines)
- Tier 3 (tracing a specific historical problem): full `log.md`

## Hooks and automation

All lifecycle hooks (SessionStart, PostToolUse, PreCompact, SessionEnd) ship with the claude-brain
plugin itself — there is nothing to register per project. A code project's `CLAUDE.md` carries only
a slim `brain: <slug>` marker; the plugin resolves it back to this vault at session start.
