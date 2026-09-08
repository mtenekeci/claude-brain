# Changelog

All notable changes to claude-brain are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## 2.0.0

A rewrite of the runtime. v1 was a markdown behavioural spec plus four bash hook scripts
copied into `~/.claude` and registered per project; v2 is a stdlib-Python package the plugin
ships and runs itself, with a derived knowledge graph and a per-project code map on top.

Upgrading is automatic — see Migration below. No vault content changes shape, and nothing in
your vault is rewritten by the upgrade.

### Added

- **Knowledge graph.** Nodes are derived from the vault (`project`, `section`, `decision`,
  `question`, `concept`) and from the repository (`file`, `symbol`, `module`); edges come from
  wikilinks, with `uses::`, `depends-on::`, `decided-by::`, `implements::` and `see::` carrying
  meaning. Cached per project and rebuilt whenever an input file changes.
- **`/brain graph`** — `find`, `near`, `path`, `top`, `ask`, `lint`, `dismiss`, `rebuild`.
- **Per-prompt retrieval.** Each prompt is tokenised and matched against the graph; up to three
  neighborhoods are injected as a "Brain: graph hits" block, deduplicated across the session.
- **Search hints.** A `Grep`/`Glob` call the graph can already answer gets a
  "Brain: graph already knows" note before the search runs.
- **`/brain map`** and `codemap.md` — a generated file/symbol/import/dependency layer plus
  curated `## Modules` and `## Where to look` tables. `map --annotate` lists directories that
  still have no `## Modules` row.
- **Concept lint.** Manifest dependencies that match a concept note are linked automatically;
  unlinked mentions are reported as candidates you confirm or `graph dismiss`. Stale
  `## Used by` claims, dangling links and likely duplicate concepts are reported too.
- **Stop gate.** A turn that landed commits — or, in `gate: all`, several uncommitted source
  edits — without a vault write is blocked once, so the record cannot silently drift from the
  code. Never fires inside a subagent, and never on a turn that ends in a question.
- **Subagent briefing.** `SubagentStart` gives each subagent the project's identity and Hard
  Rules and asks it to report findings under a `Vault notes:` heading.
- **`/brain repair --slug <slug>`** — rebuilds a lost `CLAUDE.md` block for an existing vault
  project. It never touches vault content and refuses if the folder belongs to another slug.
- **`/brain status --clean-orphans`** — deletes leftover v1 `~/.claude/brain-*.sh` scripts that
  no project still references.
- **Config knobs** `gate` (`all` | `commits` | `off`), `async_regen` (`on` | `off`) and
  `graph.backend` (`builtin` | `graphify` | `auto`), all via `/brain config set`.
- **Optional graphify backend.** When a `/graphify` run has produced `graphify-out/graph.json`,
  it can supply the code layer and answer `graph ask`. Never triggered implicitly; the builtin
  layer is always the fallback.
- **`CHANGELOG.md`** (this file).

### Changed

- **Hooks ship with the plugin.** `hooks/hooks.json` registers all eight events against
  `${CLAUDE_PLUGIN_ROOT}`. Nothing is copied to `~/.claude`, and there is no per-project hook
  registration or hook-health check any more.
- **`CLAUDE.md` carries no absolute paths.** The project block is now a `brain: <slug>` line;
  the vault root lives only in `~/.claude/brain.config`. A machine or username change no longer
  silently breaks every hook.
- **Python runtime, standard library only.** All hook logic lives in `brain/`, invoked as
  `python3 "${CLAUDE_PLUGIN_ROOT}/brain/__main__.py"` — there is no bash hook layer left.
- **`SKILL.md` is a router.** It holds the shared rules and points at one procedure file per
  command under `skills/brain/commands/`, so a session reads only the procedure it needs.
- **Session state is per session, locked.** Counters live in one JSON file per `session_id`
  under the plugin data dir, guarded by an exclusive lock. Every hook does its slow work
  (git, graph, file I/O) *before* taking that lock.
- **Session start is budgeted.** Protocol ≤ 25 lines, graph and health additions ≤ 45 lines,
  `context.md` capped at 150 lines by `/brain sync`. `architecture.md` is no longer injected —
  it is read on demand, by section.
- **`/brain sync` is CLI-assisted.** `sync-prepare` reports what needs writing (log state,
  today's commits, code-map freshness, lint candidates, unannotated directories) and
  `sync-finish` does the mechanical part (dates, index row, code map, graph cache).
- **Large repositories defer the code map.** At 3000 or more tracked files, session start
  writes the curated scaffold and hands the generated layer to a detached `map --regen`; the
  injection says so. With `async_regen: off` the build stays in the foreground instead.
- Vault and code-map writes are atomic (temp file plus rename), so an interrupted session can
  no longer leave a truncated `context.md`.
- **`PostToolUse` reminders are delivered as `additionalContext`.** Measured during the release
  smoke: a `PostToolUse` hook's plain stdout is transcript-only and never reaches the turn, so
  the commit reminder, the read nudge and the subagent vault-notes reminder were all being
  written where nothing could act on them. They now ride
  `hookSpecificOutput.additionalContext`, which was verified live to arrive.

### Removed

- **The `SubagentStop` hook.** Measured, not assumed: its output is fed back into the *finished
  subagent's* own loop, not into the parent turn, so a reminder sent there lands where nobody
  can act on it. The two channels that do reach the parent replace it — `PostToolUse` on a
  foreground `Agent`/`Task` call, and the `<task-notification>` prompt a background agent's
  completion submits. v2 registers eight events, not nine.
- The v1 bash hooks (`hooks/*.sh`) and the `~/.claude/brain-*.sh` copies they were installed as.
- The per-project hook health check, which existed only to repair that copying.

### Migration

Automatic, idempotent, and run on the first session in each connected project:

1. `CLAUDE.md` is backed up verbatim to `CLAUDE.md.brain-bak` before anything is rewritten —
   the v1 brain block could contain hand-written notes.
2. The v1 block is replaced by the slim `brain: <slug>` block.
3. v1 `brain-*.sh` hook entries are removed from the project's `.claude/settings.json`.
4. A stale `path:` in `context.md` is corrected if the folder moved.
5. `codemap.md` is created if the project has none.

A one-line `Brain: migrated ...` notice reports what was done; later sessions do nothing.

Two one-time effects to expect:

- **A doubled session start.** On the first upgraded session the v1 hooks are still registered
  when the session begins, so both they and the plugin's own SessionStart fire. Migration
  strips the old entries during that session; every session after it is clean.
- **Leftover scripts.** `~/.claude/brain-*.sh` files remain on disk. `/brain status` lists them
  and marks which are still referenced; `/brain status --clean-orphans` removes the rest.

Vault content is never modified by migration.

## 1.6.0 and earlier

See the git history. v1 was a `/brain` skill plus four bash hooks
(`session-start`, `post-tool-use`, `precompact`, `session-end`) copied into `~/.claude` and
registered in each project's `.claude/settings.json`.
