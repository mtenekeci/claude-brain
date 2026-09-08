# /brain init

Initialize a new project in the vault (or repair the current folder's connection to one).

## Run

1. `{BRAIN} config` — if it reports no vault configured, run vault discovery:
   ```bash
   find ~/Documents ~ ~/Desktop -maxdepth 2 -name ".obsidian" -type d 2>/dev/null
   find ~/Library/Mobile\ Documents/iCloud~md~obsidian/Documents -maxdepth 2 -name ".obsidian" -type d 2>/dev/null
   ```
   Strip `/.obsidian` from each hit to get vault candidates, de-duplicate, drop any path nested inside another candidate.
2. **Ask the user**, in this order:
   - Vault path: no candidates → ask for a path, default `~/Documents/claude-brain`. One candidate → confirm it, else ask for a path. Multiple → number them plus "enter a different path", ask which.
   - "What is the project name?"
   - "Code project (tied to a folder) or topic project?" — expects `code` or `topic`.
   - For a code project in an existing (non-empty/git) folder: "Run deep architecture scan? Reads up to 10 entry-point files to seed Architecture. [Y/n]"
3. Run:
   ```bash
   {BRAIN} init --name "<name>" --type <code|topic> --vault "<vault path, only if config was unset>" --packet
   ```
   `--packet` prints a seeding packet (manifest, README, git log, existing CLAUDE.md, Claude memory, deps, entry points) after the confirmation lines — this is the raw material for Step 4.

## Then

The CLI already wrote `context.md`, `architecture.md` (stub), `log.md`, the project-index row, the slim `CLAUDE.md` block, and a codemap. Your job is the prose it cannot write:

1. Read the printed seeding packet. Synthesize and rewrite `context.md`'s `## State` (what the project is / does, current stage), `## Active Work`, `## Decisions` (up to 5, from git log / CLAUDE.md / memory — else "None yet."), `## Open Questions`, `## Hard Rules` (from CI config, git hooks, CLAUDE.md), `## Constraints`. Keep `## Architecture` to a 3-5 bullet summary ending `Full reference: [[projects/<slug>/architecture|Architecture]]`.
2. If deep scan was requested: read up to 10 entry-point / recently-touched source files, then write `architecture.md`'s `## Technology Stack`, `## Repository Layout`, `## Key Patterns & Conventions` (and any domain-specific sections) with what you actually found — no placeholders.
3. Run `{BRAIN} map --annotate` — for each unannotated top directory it lists, add a `## Modules` row to `codemap.md` (module name, path, one-line responsibility, links) and a `## Where to look` row for any question a new session would ask.
4. Apply the Linking rules (see SKILL.md) to every section you just wrote.

For a brand-new empty folder: skip the deep scan, use template defaults, and note the shallow top-level listing under Architecture.

## Report

Relay exactly the confirmation lines the CLI printed (`Brain initialized for...`, `Vault:`, `Context:`, `Log:`, and for code projects `CLAUDE.md:`/`Codemap:`/`Permissions:`).
