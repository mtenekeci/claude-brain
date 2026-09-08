# claude-brain

A Claude Code plugin that gives Claude a persistent, Obsidian-backed second brain: project
state, decisions, architecture notes, a session log, and a derived knowledge graph over all
of it — loaded automatically at the start of every session.

The problem it solves is rediscovery. Without it, each new session re-greps the repository to
work out what the project is, what was decided, and where things live. With it, Claude starts
with a compact briefing and can query a graph instead of searching blind.

## What it does

- **Injects context at session start** — `context.md`, the last log entry, and the most
  connected nodes of the project's graph, before your first message.
- **Retrieves per prompt** — every prompt is matched against the graph; relevant modules,
  concepts, decisions and files are injected as a short "Brain: graph hits" block.
- **Hints before you search** — a `Grep`/`Glob` call gets a "Brain: graph already knows" note
  when the graph already has the answer.
- **Briefs subagents** — each subagent starts with the project's identity and Hard Rules and
  is asked to report findings under a `Vault notes:` heading, which you fold into the vault.
- **Enforces the write** — a turn that landed commits (or several source edits) without a
  vault update is blocked once at `Stop`, so the record does not drift from the code.
- **Checkpoints** — `PreCompact` and `SessionEnd` write a log entry if you never synced.
- **Maintains a code map** — a generated file/symbol/import layer plus curated `## Modules`
  and `## Where to look` tables you write, per project, in the vault.

Everything is plain markdown in your own vault. The graph is a derived index, rebuilt from
those files on demand — never a second source of truth.

## Requirements

- [Claude Code](https://claude.ai/code)
- Python 3.9+ (standard library only — no packages to install)
- `git` for code projects
- [Obsidian](https://obsidian.md), or any folder you are happy to treat as a markdown vault

## Install

From inside Claude Code:

```text
/plugin marketplace add mtenekeci/claude-brain
/plugin install brain@claude-brain
```

The plugin ships its own hooks. Nothing is copied into `~/.claude`, and no per-project hook
registration is needed.

## Quick start

```bash
cd ~/Projects/my-app
claude
/brain init
```

`/brain init` asks for the vault path (once, on first use), the project name, and whether it
is a **code** project (tied to a folder) or a **topic** project. It then:

- creates `<vault>/projects/<slug>/` with `context.md`, `architecture.md`, `log.md`, `codemap.md`
- adds a row to `<vault>/_system/project-index.md`
- writes a short `CLAUDE.md` block naming the slug (no absolute paths, so it survives a
  machine or username change)
- grants Claude Code read/write permission for the vault
- prints a seeding packet Claude uses to fill in the initial prose

Every later session in that folder loads the vault automatically.

## What gets injected

Session start is budgeted; the point is a briefing, not a document dump.

| At | What | Budget |
|---|---|---|
| SessionStart | The write protocol | ≤ 25 lines |
| SessionStart | `context.md`, verbatim | ≤ 150 lines (enforced by `/brain sync`) |
| SessionStart | The last `log.md` entry only | one entry |
| SessionStart | Most-connected graph nodes + a concept-health line | ≤ 12 nodes, ≤ 45 lines total |
| Each prompt | Graph hits for terms in the prompt | ≤ 3 nodes, ≤ 20 lines |
| Grep/Glob | "graph already knows" hint | ≤ 9 lines |
| Subagent start | Project identity + Hard Rules | ≤ 14 lines |

`architecture.md` is **not** injected. It is read on demand, by section — `graph near <id>`
names the section and line to read.

Repeated hits are deduplicated per session, so the same node is not re-injected on every turn.

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
| `/brain remove <slug>` | Delete a project from the vault, after typed confirmation. |
| `/brain disconnect <slug>` | Unhook a folder but keep all vault history. |

### `graph` subcommands

| Subcommand | What it does |
|---|---|
| `graph find <term>` | Search nodes by name, alias, id or path. Use this before Grep. |
| `graph near <id-or-term>` | One node's neighborhood, grouped by edge type. Accepts a search term. |
| `graph path <a> <b>` | Shortest path between two node ids. |
| `graph top [--n N]` | Highest-degree nodes — the hubs of the project. |
| `graph ask <question>` | Natural-language query, when a backend supports it (see graphify below). |
| `graph lint [--all-projects]` | Concept health: auto-applied dependency links, unlinked mentions, stale `## Used by` claims, dangling links, likely duplicates. |
| `graph dismiss <slug>` | Permanently stop suggesting a lint candidate. |
| `graph rebuild` | Force a full rebuild of the graph cache. |

There is also `/brain repair --slug <slug>`, for the case where the vault entry exists but the
folder's `CLAUDE.md` was lost — it rewrites only that block and never touches vault content.

## Configuration

Configuration lives in one file, `~/.claude/brain.config`. Change it with
`/brain config set <key> <value>`; show it with `/brain config`.

| Key | Values | Default | Meaning |
|---|---|---|---|
| `vault` | an existing directory | — | Where the vault lives. Rejected if the path does not exist. |
| `gate` | `all`, `commits`, `off` | `all` | How strict the `Stop` gate is. `all` blocks on commits or several uncommitted source edits without a vault write; `commits` blocks on commits only; `off` disables it. |
| `async_regen` | `on`, `off` | `on` | Whether code-map regeneration runs as a detached background process. `off` keeps everything in the foreground — no background processes, at the cost of a slower session start on a large repo. |
| `graph.backend` | `builtin`, `graphify`, `auto` | `auto` | Which engine supplies the graph's code layer. |

The gate blocks a turn at most once, and never inside a subagent. A turn that ends in a
question to the user is never soft-blocked.

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
| `symbol` | exported/top-level declarations in each file |
| `module` | each row of `codemap.md`'s `## Modules` table |

Edges come from wikilinks. A plain `[[projects/x/context]]` is a `links-to` edge; a **typed**
link carries meaning and is what `graph lint` looks for:

```markdown
uses:: [[concepts/postgresql|PostgreSQL]]
decided-by:: [[projects/my-app/context#Decisions]]
see:: [[concepts/nextauth|NextAuth]]
depends-on:: [[projects/api/context|api]]
implements:: [[concepts/oauth|OAuth]]
```

Obsidian renders these as ordinary links, so the graph view stays connected while brain gets
the edge type for free.

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
session-start budget is never at risk; the injection says so when this happens.

## Migration from v1

Migration is automatic and happens on the first session in each connected project. It:

1. Backs up the existing `CLAUDE.md` to `CLAUDE.md.brain-bak` — always, before rewriting it,
   because the old brain block could contain hand-written notes.
2. Replaces the v1 brain block with the slim block (`brain: <slug>`) — no absolute paths, so
   the file survives a machine or username change.
3. Removes the v1 `brain-*.sh` hook entries from the project's `.claude/settings.json`.
4. Fixes a stale `path:` in `context.md` if the folder moved.
5. Creates `codemap.md` if the project does not have one.

It says what it did in a one-line `Brain: migrated ...` notice, and does nothing on later runs.

Two things to expect once:

- **A doubled session start.** On the very first upgraded session the old per-project hooks
  are still registered in `.claude/settings.json` when the session begins, so both the v1
  script and the v2 plugin hook fire. Migration strips the old entries during that same
  session; every session after it is clean.
- **Leftover scripts.** v1 copied hook scripts to `~/.claude/brain-*.sh`. `/brain status`
  lists any that remain, marking which are still referenced by some project.
  `/brain status --clean-orphans` deletes only the unreferenced ones.

Vault content is never touched by migration.

## graphify (optional)

`graphify` — a separate Claude Code skill — can supply a richer code layer than the builtin one.
It is entirely optional and is never triggered implicitly — brain only reads a
`graphify-out/graph.json` that a `/graphify` run already produced.

- `graph.backend: auto` (the default) uses graphify when its output exists and the tool is
  runnable, and the builtin layer otherwise.
- `graph.backend: graphify` uses it whenever the export file exists.
- `graph.backend: builtin` ignores it entirely.

The builtin layer is always the fallback: an export that is missing, unreadable or
unparseable degrades to builtin silently rather than failing the session. The cache still
records `graphify` as the *selected* backend in that case, so a later fixed export is picked
up; to force a re-read immediately, run `/brain graph rebuild`. `/brain status` prints the
backend that was actually used.

`graph ask` requires the graphify backend; without it, it falls back to `find`/`near`.

## Development

```bash
python3 -m unittest discover -s tests           # unit tests, standard library only
python3 -W error::ResourceWarning -m unittest discover -s tests
CLAUDE_PROJECT_DIR=$PWD python3 -m unittest discover -s tests
```

The suite must be green in all three forms. `tests/SMOKE.md` describes the live smoke test —
it runs the real `claude` binary against these hooks inside a temporary sandbox (its own
vault, repo and `BRAIN_CONFIG`), never against your real vault or settings. Run it before
cutting a release or changing anything under `hooks/`.

| Path | Role |
|---|---|
| `brain/` | The runtime: `hooks.py` (all eight hook handlers), `cli.py`, `graph.py`, `codemap.py`, `lint.py`, `retrieve.py`, `vault.py` |
| `hooks/hooks.json` | Hook registrations shipped with the plugin |
| `skills/brain/` | `SKILL.md` router plus one procedure file per command |
| `templates/` | Files written into vaults and projects |
| `tests/` | Unit tests and the live smoke procedure |

Bump `version` in `.claude-plugin/plugin.json` on any user-facing change. Public metadata uses
`mehmet@tenekeci.ch`.

## License

MIT. See [LICENSE](LICENSE).
