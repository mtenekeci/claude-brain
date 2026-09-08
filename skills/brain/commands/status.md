# /brain status

Show the current brain state for this session.

## Run

```bash
{BRAIN} status
```

## Then

Nothing to write — this is a read-only report. If the exit code is 2 (no project resolved for this directory), it means either the vault isn't configured or this folder has no working brain connection:

- Not configured → tell the user to run `/brain init`.
- Configured but this folder isn't connected (or `CLAUDE.md` is broken/pointing at a different slug) → offer the repair path:
  ```bash
  {BRAIN} repair --slug <slug>
  ```
  (`/brain init --name <same> --type code` would be blocked by the duplicate-slug rule — `repair` is the intended fix: it rewrites only the slim `CLAUDE.md` block for the existing vault project and re-ensures the codemap. It never touches vault content, and it refuses if the folder is connected to a *different* slug.) Ask the user for the slug if it isn't obvious from context (check the project-index or the folder name).

## Report

Relay the CLI's output as-is: project name/slug/type, vault path, graph backend, updated date, session count, context size (vs 150-line cap), hook count (plugin-shipped — whatever the CLI prints), codemap freshness, graph size, concept health line, any orphaned v1 hook scripts, then the `── State ──`, `── Active Work ──`, `── Open Questions ──`, `── Last Session ──` sections.
