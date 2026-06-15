# Brain: Codex-brain

vault: /Users/mehmet.tenekeci/Documents/Codex-brain/projects/Codex-brain

## Context protocol
On session start:
1. Read `context.md` in full
2. Read last entry of `log.md` only

**A compacted conversation summary is not a vault read.** Even if the thread already contains dense, accurate-looking project context, you must still read `context.md` at session start. The summary does not contain Hard Rules or the full write protocol. Do not rationalize it away.

**Branch reconciliation after resume.** Compaction summaries often freeze a stale branch name as "current" — treat them as untrusted on branch state. After reading `context.md`, if you are about to run any git operation (push, merge, PR), run `git branch --show-current` and reconcile against the expected sub-branch in `## Active Work`. If they differ, surface the mismatch to the user before acting.

During the session — load more when needed, not upfront:
3. Before any architectural decision or significant design choice → read `architecture.md` in full (Tier 2)
4. Before any significant design choice → also read last 5 `log.md` entries (Tier 2)
5. When asked about history, past decisions, or "what did we do about X" → read full `log.md` (Tier 3)
6. When context.md feels incomplete for the current task → re-read it

**Vault before code — always:**
Before opening any source file to understand how something works, check the `context.md` Architecture section first. Only open the file if the vault doesn't have the answer. If you had to open the file because the vault was missing it — that is a vault gap: update Architecture after reading so the next session doesn't pay the same cost.

Never answer from memory when the vault has the authoritative record.

## Write protocol

**Non-negotiable checkpoints — enforced by hooks, act immediately:**

| Trigger | What to write | Timing |
|---|---|---|
| `git commit` runs | Update `## State` + `## Active Work` in context.md | Before the next response |
| About to run `git push` | Run `git branch --show-current` and compare to the expected sub-branch named in `## Active Work`. If they differ, STOP and surface the mismatch before pushing. Also re-read `## Hard Rules`. | Before push executes |
| Subagent (Agent tool) completes | If new patterns found → architecture.md bullet; if feature complete → full context.md update | Before the next response |
| Source file read revealed something non-obvious | One architecture.md bullet | Before the next tool call |
| Decision made | Add to `## Decisions` | Immediately |
| Open question resolved | Remove from `## Open Questions` | Immediately |

**Advisory triggers — self-enforce these:**

| When | Write |
|---|---|
| 15+ tool calls since last vault write | Pause — check if architecture.md, Decisions, or Open Questions need updating |
| Discrete task completed (bug fix, feature, investigation) | Update State + Active Work + append log entry, before final response |
| User signals done ("thanks", "done", "good", "bye", "ship it", "looks good") | Write log entry immediately, confirm saved |

**Minimal write** (small task, single file): one entry added to `architecture.md` if something non-obvious was discovered. No log entry needed.

**Full write** (multiple files read, decision made, bug fixed, meaningful work): update State + Active Work + all changed sections, append log entry.

Before `/compact`: write session summary to `log.md`, compress `context.md` if >150 lines.

## Sync is part of the job
Writing to the vault is not a separate chore — it is the last step of every meaningful task. Do not wait to be asked. A session that ends without a log entry is incomplete.

## context.md rules
- Hard cap: 150 lines. Compress, never delete.
- Decisions beyond 5 entries: compress each to one line
- Resolved open questions: remove immediately
- Architecture section: 3-5 bullet summary only — the most critical facts for immediate orientation. All detail lives in `architecture.md`. Always ends with: `Full reference: [[projects/Codex-brain/architecture|Architecture]]`

## architecture.md rules
- No line cap — depth is the point.
- Add a new entry whenever a non-obvious pattern, convention, or structure is discovered.
- Sections grow over time — never compress or delete, only add and correct.
- Loaded on demand (Tier 2) — before architectural decisions, not at session start.

## Superpowers integration

When superpowers skills run in this project, these checkpoints are non-negotiable:

**brainstorming skill** (hook fires on invocation):
- Before asking any clarifying questions → read context.md + last log entry. This IS Step 1 "Explore project context" — not a preliminary, the actual step.
- Before proposing approaches → read architecture.md in full (Tier 2 trigger: this is a design decision).
- When design is approved → write decisions to `## Decisions` immediately, before the spec is committed.

**subagent-driven-development skill** (hook fires on invocation):
- Before dispatching the first implementer → read context.md + architecture.md.
- After each subagent task completes (Agent PostToolUse hook reminder) → act on it before dispatching the next subagent. Continuous execution is not a reason to skip.
- After ALL tasks complete → full vault sync (State + Active Work + log entry) before finishing-a-development-branch.

## Briefing subagents on the vault

A dispatched subagent (Agent tool) starts cold — no `SessionStart` hook fires for it, so it has never seen `context.md` or `architecture.md` unless you put that in front of it. Every implementer/researcher prompt you write MUST:
1. **Name the vault path** (`<vault>/projects/<slug>/`) and instruct the subagent to read `context.md` — and `architecture.md` too, if the task involves non-trivial design or touches existing patterns — before starting work.
2. **Inline the sharp edges directly** — any Hard Rule or Architecture fact specific to that subagent's slice of work goes in the prompt text itself, verbatim. Don't gamble on the subagent finding it.
3. **Ask it to report back** any new pattern, convention, or decision it discovered, in its final message. The subagent does not write to the vault — you do, once it returns. This keeps vault writes single-owner and avoids concurrent-write races across parallel subagents.

---

# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## What this repo is

Codex plugin that gives Codex a persistent Obsidian second brain. Installed via the Codex plugin marketplace; exposes a `/brain` skill with subcommands: `init`, `load`, `sync`, `status`, `config`, `remove`, `disconnect`.

## Key files

| Path | Role |
|---|---|
| `skills/brain/SKILL.md` | Full behavioral spec for all `/brain` subcommands — the authoritative source of truth |
| `hooks/session-start.sh` | Injects full context.md + last log entry content directly into context before first prompt (not just paths) |
| `hooks/session-end.sh` | Writes a git-enriched auto-close log entry when session ends without a manual sync |
| `hooks/precompact.sh` | Writes a checkpoint entry + tells Codex to fill in details before `/compact` |
| `hooks/post-tool-use.sh` | Counts source file reads; reminds Codex to update vault Architecture every 3 reads |
| `templates/AGENTS.md` | Template written into each user project on `/brain init` |
| `templates/context.md` | Template for the per-project `context.md` vault file |
| `templates/BRAIN.md` | Template for the vault-level operating instructions at `_system/BRAIN.md` |
| `.Codex-plugin/plugin.json` | Plugin manifest (name, version, author) |
| `.Codex-plugin/marketplace.json` | Marketplace listing schema |

## Architecture

- **Config**: `~/.Codex/brain.config` — single JSON file `{ "vault": "/abs/path" }`. All hooks and the skill derive `VAULT_ROOT` from it.
- **Vault structure**: `<VAULT_ROOT>/_system/` (BRAIN.md + project-index.md) and `<VAULT_ROOT>/projects/<slug>/` (context.md + log.md).
- **Slug**: last path segment of the vault entry for that project; extracted from the `vault:` line in the project's `AGENTS.md`.
- **Hooks are installed into the user's project** `.Codex/settings.json` (not this repo) during `/brain init`. The hook scripts themselves live here and are referenced by absolute path.
- **Tiered vault loading**: Tier 1 = context.md + last log entry (~160 lines); Tier 2 = last 5 log entries (before architectural decisions); Tier 3 = full log (historical tracing).
- **Wikilinks**: all vault writes must use Obsidian `[[wikilink]]` syntax — the skill enforces this so Obsidian's graph view stays connected.

## Working on this plugin

When editing `SKILL.md`, check all subcommand sections for consistency — they share derived constants (`VAULT_ROOT`, `PLUGIN_DIR`, `VAULT_SYSTEM`, `VAULT_PROJECTS`) defined once at the top of the skill.

When editing hooks, note that `session-start.sh` and `post-tool-use.sh` output text that Codex reads as instructions; `session-end.sh` and `precompact.sh` write directly to `log.md` and then output text directing Codex to enrich the entry.

Version is tracked in `.Codex-plugin/plugin.json` — bump on any user-facing change.
