# Brain: {project-name}

vault: {vault-root}/projects/{slug}

## Context protocol
On session start (auto-loaded by SessionStart hook):
1. Read `context.md` in full (even if visible in system-reminder after compaction — re-read to engage with rules)
2. Read `architecture.md` in full
3. Read last entry of `log.md` only
4. If `context.md ## Hard Rules` contains entries, hold them in active attention — they gate risky actions

During the session — load more when needed, not upfront:
4. Before any significant design choice → read last 5 `log.md` entries (Tier 2)
5. When asked about history, past decisions, or "what did we do about X" → read full `log.md` (Tier 3)
6. When context.md feels incomplete for the current task → re-read it

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

**Write triggers — act on these without being asked:**

| When | Write |
|---|---|
| You read a source file and learned something non-obvious | Add to `architecture.md`, before your next tool call |
| A decision was made | Add to Decisions immediately |
| An open question resolved | Remove from Open Questions immediately |
| Before PR creation | Read last 5 log entries, update State + Active Work, append log entry |
| Before git merge to main | Update log entry with merge summary + outcome |
| After phase/milestone completion | Full sync: State, Active Work, log entry, compress context.md if >150 lines |
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
- Architecture section: 3-5 bullet summary only — the most critical facts for immediate orientation. All detail lives in `architecture.md`. Always ends with the wikilink to architecture.md.

## architecture.md rules
- No line cap — depth is the point.
- Add a new entry whenever a non-obvious pattern, convention, or structure is discovered.
- Never compress or delete — only add and correct.
- Auto-loaded at session start — always in context.
