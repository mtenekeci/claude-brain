# /brain load <slug...>

Load one or more additional project or topic contexts into the current session, on top of whatever auto-loaded already. A code project's own context still auto-loads via `CLAUDE.md` at session start — use this to pull in *other* projects (e.g. sibling projects in a monorepo) or a concept group.

A slug may name a project directly, or a **concept** — loading a concept slug expands to every project in that concept's `## Used by` section (e.g. loading `imatch-data-flow` loads every project that concept lists).

## Run

If no slugs were given, ask: "Which project or concept slug should I load? (run `/brain status` to list projects, or check the vault's `concepts/` dir for groups)" and stop.

```bash
{BRAIN} load <slug1> [<slug2> ...]
```

## Then

Nothing — the CLI resolves projects/concepts (validating concept `## Used by` links against real `context.md` files, reporting stale ones), reads the full `context.md` and last `log.md` entry for each resolved project, and prints everything. Hold what it printed in working context for the rest of the session.

## Report

Relay the CLI's output as-is: any `Not found: ...` line, `Loaded: ...`, any `Via concept '<entry>': ...` expansion lines with the concept's description, then each project's `context.md` and last log entry.
