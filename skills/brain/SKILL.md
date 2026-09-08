---
name: brain
description: Use when the user types /brain, /brain init, /brain load, /brain sync, /brain status, /brain config, /brain remove, /brain disconnect, /brain map, or /brain graph. Manages Claude's Obsidian second brain for persistent project context across sessions.
---

# Brain — Obsidian Second Brain

`{BRAIN}` = `python3 "${CLAUDE_PLUGIN_ROOT}/brain/__main__.py"` — write it exactly like that in every Bash call below.

## Config resolution

`VAULT_ROOT` comes from the `vault` field in `~/.claude/brain.config`. Run `{BRAIN} config` to check it. If it reports no vault set (any command besides `init`), say: "Brain is not configured yet. Run `/brain init`." — then stop.

## How the runtime works

The plugin ships all hooks itself (no per-project registration): SessionStart injects `context.md` + the last `log.md` entry directly into context before your first message; UserPromptSubmit runs a per-prompt graph retrieval ("Brain: graph hits") so you rarely need to grep for where something lives; PostToolUse watches for `git commit` and Agent-tool completions and reminds you to write; PreToolUse nudges `{BRAIN} graph find` before a raw Grep/Glob; Stop is the enforcement gate — it blocks ending a turn that made commits or several source edits without a vault write; PreCompact and SessionEnd checkpoint the session into `log.md` if you haven't synced. `codemap.md` (curated `## Modules` / `## Where to look` tables, plus a generated code layer) and `.brain/` (graph cache, dismissed candidates) live per project under `VAULT_ROOT/projects/<slug>/`. Always try `{BRAIN} graph find <term>` before Grep/Glob to find where something lives.

## Linking rules

| What you're writing | Link format |
|---|---|
| Reference to a project's context | `[[projects/<slug>/context\|<slug>]]` |
| Reference to a project's architecture | `[[projects/<slug>/architecture\|<slug> architecture]]` |
| Reference to a project's log | `[[projects/<slug>/log\|<slug> log]]` |
| Reference to project index | `[[_system/project-index\|Project Index]]` |
| Reference to a concept note | `[[concepts/<concept-slug>\|<Concept Name>]]` |

Never use plain text where a wikilink could go. Use typed links when you write meaning: `uses:: [[concepts/x]]`, `decided-by:: [[...]]`, `see:: [[concepts/x]]`.

## Concept graph

`VAULT_ROOT/concepts/` holds atomic notes for reusable architectural entities — hub nodes in Obsidian's graph view, shared across projects.

**Taxonomy** — only these four types get a concept note: `library` (external dependency), `subsystem` (named, composed piece of one project's architecture), `infra` (infrastructure/deployment), `decision` (reach beyond this project). Anything else stays an `architecture.md` bullet.

**Promotion rule** — applied at the same moment as the "non-obvious discovery → architecture.md bullet" trigger below, not a separate pass. Ask: would I plausibly write "see `[[X]]`" from more than one place (another file, decision, or project)? No → bullet only. Yes → run `{BRAIN} graph find <name>` first to check for an existing note (avoid duplicates), derive `CONCEPT_SLUG` (lowercase, hyphenated), then create `VAULT_ROOT/concepts/<CONCEPT_SLUG>.md` (frontmatter `concept`/`type`/`updated`, 1-3 sentence description, `## Used by` list) if it doesn't exist, or append this project to `## Used by` if it does. Link it from the bullet or Decision entry.

## Autonomous write protocol

These rules apply at all times, not just when `/brain` commands are invoked:

Rules:
1. Before any Grep/Glob/Read to find where something lives, use the "Brain: graph hits" injected with your prompt, or run `{BRAIN} graph find <term>` then `{BRAIN} graph near <id>`. On a miss: search the code, then add a codemap `## Modules` row or an architecture.md bullet so the next session hits.
2. Before a design decision, read the relevant architecture.md section (`{BRAIN} graph near <node>` names it) — not the whole file.
3. Write meaning, not mechanics: `## State` + `## Active Work` after commits, decisions when made, module responsibilities when learned. Dates, the codemap tree, Used-by edges, index rows, and the Completed/Changed lines of the plugin's own checkpoint entries are maintained for you. A log entry you write yourself during `/brain sync` is yours in full, Changed line included.
4. Link with typed wikilinks when you write: `uses:: [[concepts/x]]`, `decided-by:: [[...]]`. Promote to a concept note only if you would link it from more than one place; run `{BRAIN} graph find` first to avoid duplicates.
5. Subagents are briefed automatically; fold their "Vault notes:" into the vault when they return.
6. The plugin blocks you from ending a turn that made commits or several source edits without a vault write. Write it, then finish.
Hard Rules in context.md apply to every action.

**Advisory:** after 15+ tool calls without a vault write, pause and ask whether Architecture/Decisions/Open Questions need updating. When the user signals done ("thanks", "ship it", "looks good"), write the log entry immediately.

**Subagent briefing** — every `Agent` dispatch prompt must: name `VAULT_ROOT/projects/<slug>/` and tell the subagent to read `context.md` (+ `architecture.md` for design work) first; inline any Hard Rule or fact specific to its slice directly in the prompt text; ask it to report new patterns/decisions in its final message. You write the vault, not the subagent — single-owner writes avoid races.

## Router

Read only the command file you need.

| Command | Procedure |
|---|---|
| `/brain init` | read `commands/init.md` |
| `/brain load <slug...>` | read `commands/load.md` |
| `/brain sync` | read `commands/sync.md` |
| `/brain status` | read `commands/status.md` |
| `/brain map` | read `commands/map.md` |
| `/brain graph <sub>` | read `commands/graph.md` |
| `/brain config` | read `commands/config.md` |
| `/brain remove` / `/brain disconnect` | read `commands/remove.md` |
