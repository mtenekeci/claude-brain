# Brain: {project-name}

vault: ~/Documents/Claude Brain/claude-brain/projects/{slug}

## Session start protocol
1. Read `context.md` in full
2. Read last entry of `log.md` only
3. If about to make an architectural decision → read last 5 `log.md` entries (Tier 2)
4. Read full `log.md` only when tracing history of a specific problem (Tier 3)

## Write protocol
- After completing a significant task: update `context.md` state + append `log.md` entry
- After making an architectural decision: update `context.md` decisions section
- Before `/compact`: write session summary to `log.md`, compress `context.md` if >150 lines

## context.md rules
- Hard cap: 150 lines. Compress, never delete.
- Decisions beyond 5 entries: compress each to one line
- Resolved open questions: remove immediately
- Architecture section: bullets only, no prose
