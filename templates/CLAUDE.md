# Brain: {project-name}

vault: {vault-root}/projects/{slug}

## Hard rules

These are non-negotiable. They override default reasoning and cannot be skipped for any task, however simple it seems.

1. **Vault before code.** Before opening any source file to understand how something works, check `context.md` Architecture first. Only open the file if the vault doesn't have the answer.

2. **Vault miss = vault update.** If you opened a source file because the vault lacked the answer, you MUST update the Architecture section before moving on. Every miss must pay for itself.

3. **No session ends without a log entry.** If meaningful work was done, write a `log.md` entry before the session closes — without being asked. A session with no log entry is incomplete work.

4. **Vault is the source of truth.** Never answer questions about project state, decisions, or history from memory alone. Read the vault first.

5. **Context is a living document.** When `context.md` becomes stale, fix it inline — do not defer. Future sessions depend on it being accurate.

## Context protocol
On session start (auto-loaded by SessionStart hook):
1. Read `context.md` in full (even if visible in system-reminder after compaction — re-read to engage with rules)
2. Read last entry of `log.md` only
3. If `context.md ## Hard Rules` contains entries, hold them in active attention — they gate risky actions

**Branch reconciliation after resume.** Compaction summaries often freeze a stale branch name as "current" — treat them as untrusted on branch state. Before any git push, merge, or PR creation, run `git branch --show-current` and reconcile against the expected sub-branch in `## Active Work`. If they differ, surface the mismatch to the user before acting.

Tier 2 — load on demand, not upfront:
4. Before any architectural decision or significant design choice → read `architecture.md` in full
5. Before any significant design choice → also read last 5 `log.md` entries

During the session — load more when needed, not upfront:
6. When asked about history, past decisions, or "what did we do about X" → read full `log.md` (Tier 3)
7. When context.md feels incomplete for the current task → re-read it

**Vault before code — always:**
Before opening any source file to understand how something works, check `architecture.md` first. Only open the file if the vault doesn't have the answer. If you had to open the file because the vault was missing it — that is a vault gap: update `architecture.md` after reading so the next session doesn't pay the same cost.

Never answer from memory when the vault has the authoritative record.

## Pre-Action Checklist

Before ANY of these actions, STOP and check `context.md` Hard Rules + `architecture.md` for relevant constraints:
- Git merge to main/master
- Force push
- PR creation
- Branch deletion
- Docker deployment
- Database migration
- npm publish / package release
- Breaking API changes

Check for:
- Workflow rules (PR-first? review required? branch protection?)
- Testing requirements (must pass before merge/deploy?)
- Deployment procedures (staging-first? approval needed?)
- Dependency constraints (version pinning? compatibility?)

If rules exist and conflict with the action, stop and ask the user.

## Write protocol

**Non-negotiable checkpoints — enforced by hooks, act immediately:**

| Trigger | What to write | Timing |
|---|---|---|
| About to run `git push` | Run `git branch --show-current` and compare to the expected sub-branch in `## Active Work`. If they differ, STOP and surface the mismatch before pushing. Also re-read `## Hard Rules`. | Before push executes |
| `git commit` runs | Update `## State` + `## Active Work` in context.md | Before the next response |
| Subagent (Agent tool) completes | If new patterns found → architecture.md bullet; if feature complete → full context.md update | Before the next response |
| Source file read revealed something non-obvious | One architecture.md bullet. If it's a library/subsystem/infra/decision someone would plausibly link to from elsewhere ("see [[X]]" from >1 place), also create/update its note in `{vault-root}/concepts/` (see ## Concept graph) and link it from the bullet. | Before the next tool call |
| Decision made | Add to `## Decisions` | Immediately |
| Open question resolved | Remove from `## Open Questions` | Immediately |

**Advisory triggers — self-enforce these:**

| When | Write |
|---|---|
| Before PR creation | Read last 5 log entries, update State + Active Work, append log entry |
| Before git merge to main | Update log entry with merge summary + outcome |
| After phase/milestone completion | Full sync: State, Active Work, log entry, compress context.md if >150 lines |
| 15+ tool calls since last vault write | Pause — check if architecture.md, Decisions, or Open Questions need updating |
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
- Architecture section: 3-5 bullet summary only — the most critical facts for immediate orientation. All detail lives in `architecture.md`. Always ends with the wikilink to architecture.md.

## architecture.md rules
- No line cap — depth is the point.
- Add a new entry whenever a non-obvious pattern, convention, or structure is discovered.
- Never compress or delete — only add and correct.
- Loaded on demand (Tier 2) — before architectural decisions, not at session start. Keeps session start lean.
- Bullets that reference a shared library, subsystem, infra component, or cross-reaching decision should link to its concept note: `— see [[concepts/<slug>|<Name>]]` (see ## Concept graph).

## Concept graph

`{vault-root}/concepts/` holds atomic notes for reusable architectural entities — libraries, named subsystems, infra components, and decisions with reach beyond this project. These become hub nodes in Obsidian's graph view, including hubs shared across multiple projects.

**Taxonomy** — only these four types get a concept note: `library`, `subsystem` (a named, composed piece of the architecture, e.g. "auth flow"), `infra`, `decision` (with reach beyond this project). Anything else stays an architecture.md bullet.

**Promotion rule** — applied at the same moment as the existing "non-obvious discovery → architecture.md bullet" trigger, not as a separate pass. Ask: would I plausibly write "see `[[X]]`" from more than one place (another file, decision, or project)?
- No → architecture.md bullet only, as before.
- Yes → derive `CONCEPT_SLUG` (lowercase, hyphenated name), then check `{vault-root}/concepts/<CONCEPT_SLUG>.md`:
  - Doesn't exist → create it from `templates/concept.md` with `type`, a 1-3 sentence description, and `## Used by` starting with this project.
  - Exists → append this project to `## Used by` (don't rewrite other entries — this is how cross-project sharing works).
  - Link it from the architecture.md bullet (or `## Decisions` entry): `— see [[concepts/<CONCEPT_SLUG>|<Concept Name>]]`.

Concept notes are never deleted automatically.

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
