# claude-brain

A Claude Code plugin that gives Claude a persistent second brain in your own Obsidian vault:
project state, decisions, architecture notes, a session log, a code map, and a knowledge graph
derived from all of it. Every session starts briefed, and every session leaves the vault a
little better than it found it.

Everything is plain markdown on your disk. Nothing leaves your machine, there are no packages
to install, and the graph is a derived index over your notes, never a second source of truth.

## Why

Without memory, every session re-discovers the project: it greps for where things live,
re-reads files to work out what was decided, and repeats mistakes it made last week. That
costs tokens, time, and accuracy.

With brain, a session opens with a compact briefing (what the project is, what is in flight,
what was decided, the hard rules) and can ask a graph where something lives instead of
searching blind. When the session commits code, it is required to write down what changed
before it ends, so the record never drifts from the repository.

## What a session looks like

Before your first message, Claude sees roughly this (trimmed):

```text
Brain: vault context for "my-app" follows. It is authoritative for state, decisions, history, and hard rules.
Rules:
1. Before any Grep/Glob/Read to find where something lives, use the "Brain: graph hits" ...
...
## State
Next.js 15 storefront, Postgres via Prisma, deployed on Fly. v2.3 shipped 2026-08-30.
## Active Work
Checkout redesign on `feat/checkout-v2` — cart step done, payment step in progress.
## Decisions
- Server actions over API routes for mutations (2026-08-12) — decided-by:: [[concepts/nextjs-app-router]]
## Hard Rules
- Never commit directly to `main`.
...
## 2026-09-05 · Session 41
Completed: Payment step form validation ...

Brain: most-connected nodes — `graph near <id>` for a neighborhood, `graph find <term>` before grepping code:
project my-app  projects/my-app/context.md  — my-app  (18)
concept postgresql  concepts/postgresql.md  — PostgreSQL  (6)
module checkout  src/checkout/  — Checkout flow  (5)
...
Brain: graph health — clean
```

Then, on a prompt such as *"where is the coupon validation and what did we decide about it?"*:

```text
Brain: graph hits for "coupon, validation" —
file src/checkout/coupon.ts  src/checkout/coupon.ts  — coupon.ts
decision my-app/coupons-are-validated-server-side  projects/my-app/context.md  — Coupons are validated server-side
```

And if Claude reaches for `Grep` anyway when the graph already has the answer, it gets a
one-line *"Brain: graph already knows"* hint first.

## What it does

- **Injects context at session start.** `context.md`, the last `log.md` entry, the most
  connected graph nodes, and a concept-health line, all within a fixed budget.
- **Retrieves per prompt.** Each prompt is matched against the graph and the relevant files,
  symbols, modules, concepts, and decisions are injected as a short block. Repeats are
  deduplicated per session.
- **Hints before searches.** A `Grep`/`Glob` the graph can answer gets a note before it runs.
- **Maintains a code map.** A generated file/symbol/import/dependency layer per project, plus
  curated `## Modules` and `## Where to look` tables Claude fills in as it learns the code.
- **Briefs subagents.** Each subagent starts with the project's identity and Hard Rules and
  reports its findings under a `Vault notes:` heading for the parent to fold into the vault.
- **Enforces the write.** A turn that landed commits (or several source edits) without a vault
  update is blocked once at `Stop`. It never fires inside a subagent or on a turn that ends in
  a question to you.
- **Checkpoints.** If a session compacts or ends without a sync, a log entry is written with
  the commits made, so nothing is lost.
- **Keeps concepts honest.** A lint reports concept notes nothing links to, stale `## Used by`
  claims, dangling wikilinks, and likely duplicates; manifest dependencies that match a concept
  are linked automatically.
- **Guards pushes.** A `git push` to a branch other than the one the project records, or to
  `main` when the Hard Rules forbid it, is denied with an explanation.

## Requirements

- [Claude Code](https://claude.ai/code) (tested with 2.1)
- Python 3.9+ (standard library only)
- `git` for code projects
- [Obsidian](https://obsidian.md), or any folder you are happy to treat as a markdown vault

## Install

From inside Claude Code:

```text
/plugin marketplace add mtenekeci/claude-brain
/plugin install brain@claude-brain
```

The plugin ships its own hooks. Nothing is copied into `~/.claude`, and no per-project hook
registration is needed. Upgrading from v1 is automatic; see [Migration from v1](#migration-from-v1).

## Quick start

```bash
cd ~/Projects/my-app
claude
/brain init
```

`/brain init` asks for the vault path (once, on first use), the project name, and whether it
is a **code** project (tied to a folder) or a **topic** project (notes only). It then:

- creates `<vault>/projects/<slug>/` with `context.md`, `architecture.md`, `log.md`, `codemap.md`
- adds a row to `<vault>/_system/project-index.md`
- writes a short `CLAUDE.md` block naming the slug, with no absolute paths, so it survives a
  machine or username change
- grants Claude Code read/write permission for the vault
- hands Claude a seeding packet (git history, README, existing notes) to write the first
  `## State`, `## Architecture`, and `## Hard Rules` from

Every later session in that folder loads the vault automatically. From then on the loop is:

1. **Work.** Claude reads the briefing, queries the graph, and edits code. As it learns where
   things live it adds `## Modules` rows and architecture bullets so the next session hits.
2. **Commit.** The `Stop` gate makes sure `## State` and `## Active Work` are updated before
   the turn ends. Decisions go under `## Decisions` when they are made.
3. **`/brain sync`** when you want a proper record: it rewrites `context.md`, resolves concept
   candidates, appends a log entry, and refreshes the code map and graph. If you never run it,
   the session-end checkpoint writes a mechanical entry for you.

## The vault

```text
<vault>/
├── _system/
│   ├── BRAIN.md              operating instructions for the vault
│   └── project-index.md      one row per project
├── concepts/                 shared notes: libraries, subsystems, infra, decisions
│   ├── postgresql.md
│   └── nextauth.md
└── projects/
    └── my-app/
        ├── context.md        State, Architecture, Active Work, Decisions, Open Questions, Hard Rules
        ├── architecture.md   longer-form notes, read on demand by section
        ├── log.md            one entry per session
        ├── codemap.md        generated code layer + curated Modules / Where to look tables
        └── .brain/           graph cache and dismissed lint candidates (plugin-owned)
```

Every cross-reference is an Obsidian wikilink, so the vault's graph view stays connected. A
**typed** link carries meaning that the plugin's graph understands:

```markdown
uses:: [[concepts/postgresql|PostgreSQL]]
decided-by:: [[projects/my-app/context#Decisions]]
see:: [[concepts/nextauth|NextAuth]]
depends-on:: [[projects/api/context|api]]
implements:: [[concepts/oauth|OAuth]]
```

Concept notes are shared across projects. Claude promotes something to a concept only when it
would link to it from more than one place; everything else stays an `architecture.md` bullet.

## What happens on each hook

| Event | What brain does |
|---|---|
| `SessionStart` (startup, resume, compact, fork) | Migrates a v1 project if needed, refreshes the code map, injects the protocol, `context.md`, the last log entry, the top graph nodes, and a health line. |
| `UserPromptSubmit` | Matches the prompt against the graph and injects up to three neighborhoods. Recognises a returning subagent's `Vault notes:`. |
| `PreToolUse` (`Bash`, `Grep`, `Glob`) | Denies a push to the wrong branch; hints when the graph already knows what a search is for. |
| `PostToolUse` (`Bash`, `Read`, `Edit`, `Write`, `Agent`) | Notices commits and source edits for the gate, nudges an architecture note after several source reads, reminds the parent to fold in a subagent's notes. |
| `SubagentStart` | Briefs the subagent with the project identity and Hard Rules. |
| `Stop` | Blocks once if the turn committed without a vault write (see `gate`). |
| `PreCompact` | Writes a checkpoint log entry before context is compacted. |
| `SessionEnd` | Writes an auto-close entry if the session never synced. |

Hooks never raise and never block a session on failure; outside a brain project they are silent.
Everything slow (git, graph builds, file I/O) runs before a per-session lock is taken, so hooks
stay well inside Claude Code's time budget: session start measures 0.15 to 0.3 s on a 700-file
repository.

## What gets injected

Session start is budgeted; the point is a briefing, not a document dump.

| At | What | Budget |
|---|---|---|
| SessionStart | The write protocol | ≤ 25 lines |
| SessionStart | `context.md`, verbatim | ≤ 150 lines (advisory, reported by `/brain sync`) and ≤ 16 KB (hard) |
| SessionStart | The last `log.md` entry only | one entry, ≤ 16 KB |
| SessionStart | Most-connected graph nodes + a concept-health line | ≤ 12 nodes, ≤ 45 lines total |
| Each prompt | Graph hits for terms in the prompt | ≤ 3 nodes, ≤ 20 lines |
| Grep/Glob | "graph already knows" hint | ≤ 9 lines |
| Subagent start | Project identity + Hard Rules | ≤ 14 lines |

The line cap is advisory; the **byte** cap is enforced, because lines are a poor proxy for
size. When a note is over 16 KB the injection is cut at the last section boundary that fits
and says so (`Brain: context.md truncated at 16 KB — trim it (/brain sync)`); `/brain status`
and `/brain sync` report the file's real size.

`architecture.md` is **not** injected. It is read on demand, by section: `graph near <id>`
names the section and line to read.

## Commands

| Command | What it does |
|---|---|
| `/brain init` | Connect this folder (or a topic) to the vault. |
| `/brain load <slug> [<slug> ...]` | Load other projects' context into this session. A concept slug expands to every project that concept links together. |
| `/brain sync` | Reconcile and write: rewrite `context.md`, resolve concept candidates, append a log entry, refresh the code map and graph. |
| `/brain status` | Project, vault, backend, session count, context size, code-map freshness, graph size, concept health, leftover v1 scripts. |
| `/brain map` | Check or regenerate the code map; `--annotate` lists directories with no `## Modules` row. |
| `/brain graph <sub>` | Query the graph (see below). |
| `/brain config` | Show or change configuration. |
| `/brain repair --slug <slug>` | Rewrite a lost `CLAUDE.md` block for an existing vault project. Never touches vault content. |
| `/brain remove <slug>` | Delete a project from the vault, after typed confirmation. |
| `/brain disconnect <slug>` | Unhook a folder but keep all vault history. |

### `graph` subcommands

| Subcommand | What it does |
|---|---|
| `graph find <term>` | Search nodes by name, alias, id or path. Use this before Grep. |
| `graph near <id-or-term>` | One node's neighborhood, grouped by edge type. Accepts a search term. |
| `graph path <a> <b>` | Shortest path between two node ids. |
| `graph top [--n N]` | Highest-degree nodes: the hubs of the project. |
| `graph ask <question>` | Natural-language query, when a backend supports it (see graphify below). |
| `graph lint [--all-projects]` | Concept health: auto-applied dependency links, unlinked mentions, stale `## Used by` claims, dangling links, likely duplicates. |
| `graph dismiss <slug>` | Permanently stop suggesting a lint candidate. |
| `graph rebuild` | Force a full rebuild of the graph cache. |

The same commands are available from a shell as
`python3 "$CLAUDE_PLUGIN_ROOT/brain/__main__.py" <command>`; that is what the skill runs.

## Configuration

Configuration lives in one file, `~/.claude/brain.config`. Change it with
`/brain config set <key> <value>`; show it with `/brain config`.

| Key | Values | Default | Meaning |
|---|---|---|---|
| `vault` | an existing directory | — | Where the vault lives. Rejected if the path does not exist. |
| `gate` | `all`, `commits`, `off` | `all` | How strict the `Stop` gate is. `all` blocks on commits or several uncommitted source edits without a vault write; `commits` blocks on commits only; `off` disables it. |
| `async_regen` | `on`, `off` | `on` | Whether code-map regeneration runs as a detached background process. `off` keeps everything in the foreground, at the cost of a slower session start on a large repository. |
| `graph.backend` | `builtin`, `graphify`, `auto` | `auto` | Which engine supplies the graph's code layer. |

The gate blocks a turn at most once, and never inside a subagent. A turn that ends in a
question to the user is never soft-blocked.

## The push guard

A `git push` whose target branch is not the one `context.md` records, or is `main`/`master`
when the project's Hard Rules forbid it, is denied at `PreToolUse` with an explanation. The
command is parsed rather than pattern-matched, so a push wrapped in a shell keyword, a
subshell, a command substitution, `sudo`/`env`/`timeout`, or a one-level `bash -c` is still
seen; a push it cannot resolve to concrete branches is denied too, with a note asking for a
plain `git push <remote> <branch>`.

It is a speed bump against pushes made by habit, not a sandbox: a shell fed on stdin, a
heredoc body, or a push inside a script file all run outside its reach, and nothing about it
should be relied on as a security boundary.

## How the graph works

Nodes are derived from two layers.

**The vault layer** reads your markdown:

| Node type | Comes from |
|---|---|
| `project` | `context.md` frontmatter |
| `section` | each `##`/`###` heading in `architecture.md` |
| `decision` / `question` | each bullet under `## Decisions` / `## Open Questions` |
| `concept` | each note in `<vault>/concepts/` |

**The code layer** is generated from the repository (`git ls-files`) plus the curated tables
in `codemap.md`:

| Node type | Comes from |
|---|---|
| `file` | every tracked source file |
| `symbol` | exported/top-level declarations in each file (TypeScript, JavaScript, Python, Go, Rust, Ruby, Java, Kotlin, Swift, C#, Scala, Vue, Svelte) |
| `module` | each row of `codemap.md`'s `## Modules` table |

Edges come from wikilinks (`links-to`, or the typed kinds above), from imports and manifest
dependencies (`imports`, `depends-on`), from containment (`contains`), and from mentions of a
concept's name or alias in prose (`mentions`).

`codemap.md` has two halves. Everything above the `brain:generated:end` marker is regenerated
by `map --regen` and must not be hand-edited. Everything below it is yours:

```markdown
## Modules
| module | path | responsibility | links |
|---|---|---|---|
| Auth flow | src/auth/ | Session cookies and refresh | uses:: [[concepts/nextauth|NextAuth]] |

## Where to look
| question | path |
|---|---|
| where are sessions stored? | src/auth/session.ts |
```

A `path` of `.` means the repository root. `/brain map --annotate` lists directories with
three or more source files and no `## Modules` row yet.

The graph is cached per project under `<vault>/projects/<slug>/.brain/` and rebuilt whenever
any input file changes. On a repository with 3000 or more tracked files, session start writes
the curated scaffold and defers the generated layer to a background `map --regen`, so the
session-start budget is not spent on it; the injection says so when this happens. With
`async_regen: off` that build runs in the foreground instead, still bounded by the same
file-count limit.

## Migration from v1

Migration is automatic and happens on the first session in each connected project. It:

1. Backs up the existing `CLAUDE.md` to `CLAUDE.md.brain-bak`, always, before rewriting it.
2. Replaces the v1 brain block with the slim block (`brain: <slug>`). Any YAML frontmatter and
   your own notes in the file are preserved.
3. Removes the v1 `brain-*.sh` hook entries from the project's `.claude/settings.json`.
4. Fixes a stale `path:` in `context.md` if the folder moved.
5. Creates `codemap.md` if the project does not have one.

It says what it did in a one-line `Brain: migrated ...` notice, and does nothing on later runs.

Two things to expect once:

- **A doubled session start.** On the very first upgraded session the old per-project hooks
  are still registered in `.claude/settings.json` when the session begins, so both the v1
  script and the v2 plugin hook fire. Migration strips the old entries during that same
  session; every session after it is clean.
- **Leftover scripts.** v1 copied four hook scripts to `~/.claude/`
  (`brain-session-start.sh`, `brain-post-tool-use.sh`, `brain-precompact.sh`,
  `brain-session-end.sh`). `/brain status` lists any that remain, marking which are still
  referenced by a project or by your own `settings.json`; `/brain status --clean-orphans`
  deletes only the unreferenced ones. Those four names are the only files it will ever touch.

Migration itself rewrites nothing in the vault except the `path:` field above. Separately,
the first v2 session runs the concept lint, which auto-applies up to five manifest-dependency
links (a `uses::` line in `context.md` and a `## Used by` row in the matching concept note).
It says so in the health line, and `/brain graph dismiss <slug>` stops any of them coming back.

## graphify (optional)

graphify, a separate Claude Code skill, can supply a richer code layer than the builtin
one. It is entirely optional and never triggered
implicitly: brain only reads a `graphify-out/graph.json` that a `/graphify` run already
produced.

- `graph.backend: auto` (the default) uses graphify when its output exists and the tool is
  runnable, and the builtin layer otherwise.
- `graph.backend: graphify` uses it whenever the export file exists.
- `graph.backend: builtin` ignores it entirely.

The builtin layer is always the fallback: an export that is missing, unreadable or
unparseable degrades to builtin silently rather than failing the session. To force a re-read
after fixing an export, run `/brain graph rebuild`. `/brain status` prints the backend that
was actually used. `graph ask` requires the graphify backend; without it, it falls back to
`find`/`near`.

## Development

```bash
python3 -m unittest discover -s tests           # unit tests, standard library only
python3 -W error::ResourceWarning -m unittest discover -s tests
CLAUDE_PROJECT_DIR=$PWD python3 -m unittest discover -s tests
```

The suite must be green in all three forms. `tests/SMOKE.md` describes the live smoke test:
it runs the real `claude` binary against these hooks inside a temporary sandbox (its own
vault, repo and `BRAIN_CONFIG`), never against your real vault or settings. Run it before
cutting a release or changing anything under `hooks/`.

| Path | Role |
|---|---|
| `brain/` | The runtime: `hooks.py` (all eight hook handlers), `cli.py`, `graph.py`, `codemap.py`, `lint.py`, `retrieve.py`, `vault.py`, `backends/` |
| `hooks/hooks.json` | Hook registrations shipped with the plugin |
| `skills/brain/` | `SKILL.md` router plus one procedure file per command |
| `templates/` | Files written into vaults and projects |
| `tests/` | Unit tests and the live smoke procedure |

Bump `version` in `.claude-plugin/plugin.json` on any user-facing change and add a
`CHANGELOG.md` entry. Public metadata uses `mehmet@tenekeci.ch`.

## License

MIT. See [LICENSE](LICENSE).
