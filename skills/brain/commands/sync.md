# /brain sync

Force a vault write for the current project. Use before a risky change, before a long break, or before switching projects.

## Run

```bash
{BRAIN} sync-prepare
```

This prints: the slug, `context.md` line count (cap 150), the last log entry's session number and whether it's a placeholder (`(pre-compact)`/`(auto-close)`), today's commits and modified files, codemap freshness, graph size, up to 5 lint candidates (unlinked concept mentions), and unannotated directories.

## Then

1. **Rewrite `context.md`** (v1 rules): `## State` (2-3 sentences — what exists, what works, what's changing), `## Active Work` (what's in progress), `## Decisions` (add this session's, don't remove older ones yet), `## Open Questions` (remove resolved, add new). If the resulting file is over 150 lines, compress every `## Decisions` entry beyond the 5 most recent to one line: `- [<date>] <one-sentence summary>`. Apply the Linking rules to everything you touch.
2. **Resolve lint candidates** (up to 5, from `sync-prepare`'s output): for each, either add a typed link (`uses:: [[concepts/<slug>|<Name>]]`) in `## Architecture`, or if it's not a real relationship, dismiss it:
   ```bash
   {BRAIN} graph dismiss <slug>
   ```
3. **Append the log entry** — count `## ` entries in `log.md` for session N. If the last entry is a placeholder (`(pre-compact)`/`(auto-close)`), replace it in place (N stays); otherwise append a new one as N+1:
   ```markdown
   ## <YYYY-MM-DD> · Session <N>
   Completed: <what was accomplished>
   Changed: <files/systems touched, or "—">
   Decided: <one-line reasons, or "none">
   Next: <what comes next>
   ```
4. Run:
   ```bash
   {BRAIN} sync-finish
   ```
   This stamps `context.md`'s `updated:` frontmatter, updates the project-index `last-active` column, regenerates the codemap's generated layer, and rebuilds the graph cache. It also warns if `context.md` is still over the 150-line cap after your edits — go back and compress further if so.

## Report

Relay `sync-finish`'s output: `context.md: <N> lines (cap: 150)` and `Brain synced: <slug>` (plus the over-cap warning if printed).
