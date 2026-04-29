# Brain: {project-name}

vault: {vault-root}/projects/{slug}

## Context protocol
On session start:
1. Read `context.md` in full
2. Read last entry of `log.md` only

During the session — load more when needed, not upfront:
3. Before any architectural decision or significant design choice → read last 5 `log.md` entries (Tier 2)
4. When asked about history, past decisions, or "what did we do about X" → read full `log.md` (Tier 3)
5. When context.md feels incomplete for the current task → re-read it

**Vault before code — always:**
Before opening any source file to understand how something works, check the `context.md` Architecture section first. Only open the file if the vault doesn't have the answer. If you had to open the file because the vault was missing it — that is a vault gap: update Architecture after reading so the next session doesn't pay the same cost.

Never answer from memory when the vault has the authoritative record.

## Write protocol
- After completing a significant task: update `context.md` state + append `log.md` entry
- After making an architectural decision: update `context.md` decisions section
- After any session where ≥ 3 source files were read: before writing the log entry, ask "what would a future session need to know to avoid re-reading these files?" Add the answer to the `context.md` Architecture section. This applies especially to bug-fix sessions — diagnosing a bug requires the most code reading and produces the most reusable knowledge
- Before `/compact`: write session summary to `log.md`, compress `context.md` if >150 lines
- When the user signals they are done ("thanks", "done", "good", "bye", "ship it", "looks good", "that's all", "close this"): write log entry immediately without being asked, then confirm it is saved
- If meaningful work was done and no sync has happened: proactively offer to sync at a natural pause

## Sync is part of the job
Writing to the vault is not a separate chore — it is the last step of every meaningful task. Do not wait to be asked. A session that ends without a log entry is incomplete.

## context.md rules
- Hard cap: 150 lines. Compress, never delete.
- Decisions beyond 5 entries: compress each to one line
- Resolved open questions: remove immediately
- Architecture section: bullets only, no prose. Capture patterns, conventions, and non-obvious structure discovered during exploration — not just directory names. This is the cache that prevents re-reading the same files next session.
