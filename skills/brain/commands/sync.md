# /brain sync

Force a vault write for the current project. Use before a risky change, before a long break, or before switching projects.

## Run

```bash
{BRAIN} sync-prepare
```

This prints, among other lines: `context.md: <N> lines (cap 150)`; `last log entry: Session <N> [placeholder|real]`; `next session: <N>`; today's commits and modified files; codemap freshness; graph size; up to 5 lint candidates (unlinked concept mentions); and unannotated directories.

## Then

1. **Rewrite `context.md`** (v1 rules): `## State` (2-3 sentences — what exists, what works, what's changing), `## Active Work` (what's in progress), `## Decisions` (add this session's, don't remove older ones yet), `## Open Questions` (remove resolved, add new). If the resulting file is over 150 lines, compress every `## Decisions` entry beyond the 5 most recent to one line: `- [<date>] <one-sentence summary>`. Apply the Linking rules to everything you touch.
2. **Resolve lint candidates** (up to 5, from `sync-prepare`'s output): for each, either confirm it — add one `uses:: [[concepts/<slug>|<Name>]]` line in `context.md`'s `## Architecture` section, directly above the `Full reference:` line (the same place `graph lint`'s auto-apply writes) — or, if it's not a real relationship, dismiss it:
   ```bash
   {BRAIN} graph dismiss <slug>
   ```
3. **Update `architecture.md`** — append any architectural discoveries from this session (new patterns, conventions, structural changes) as bullets to the relevant existing section, or a new one. Apply the Concept graph promotion rule (SKILL.md) to each: if it's the kind of fact you'd link to from more than one place, create/update its concept note and link it from the bullet.
4. **Append the log entry.** This one is yours to write in full — the `Changed:` line included; the plugin only fills that in on its own `(pre-compact)` / `(auto-close)` checkpoint entries. Read `sync-prepare`'s `last log entry: Session <N> [placeholder|real]` and `next session: <M>` lines: if `[placeholder]`, replace that entry (`(pre-compact)`/`(auto-close)`) in place using session number `<N>`; if `[real]`, append a new entry using `<M>`:
   ```markdown
   ## <YYYY-MM-DD> · Session <N or M>
   Completed: <what was accomplished>
   Changed: <files/systems touched, or "—">
   Decided: <one-line reasons, or "none">
   Next: <what comes next>
   ```
5. Run:
   ```bash
   {BRAIN} sync-finish
   ```
   This stamps `context.md`'s `updated:` frontmatter, updates the project-index `last-active` column, regenerates the codemap's generated layer, and rebuilds the graph cache. It also warns if `context.md` is still over the 150-line cap after your edits — go back and compress further if so.

## Report

Relay `sync-finish`'s output: `context.md: <N> lines (cap 150)` and `Brain synced: <slug>` (plus the over-cap warning if printed).
