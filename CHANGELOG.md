# Changelog

All notable changes to claude-brain are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## 2.0.4

`UserPromptSubmit` was repeatedly killed at its deadline — "UserPromptSubmit hook timed out after
5s — output discarded" — which drops that turn's entire graph retrieval. Measured on this repo the
handler costs ~50 ms warm and ~70 ms with the graph cache deleted (a full rebuild is ~25 ms), so
the retrieval work was not what missed the deadline. The cause was on the other side of the
session lock: every event except `SessionEnd` waited for it indefinitely, so one slow holder
turned each peer into a hook that ran until Claude Code killed it. Bursts of parallel
`Edit`/`Write`/`Bash` calls — many `PostToolUse` hooks arriving on one session id at once — are
where that contention comes from.

### Changed

- Waiting for the session lock is bounded per event (`hooks._LOCK_WAIT`), sized to leave the
  handler the rest of that event's hook timeout. On expiry the event logs
  `<event> skipped: session lock busy after <n>s` to `brain.log` and returns nothing, rather than
  waiting to be killed — the same output is lost either way, and the skip does not also stall the
  turn. Peers hold the lock for ~1 ms, since each handler does its slow work in `prepare()`
  beforehand, so the budgets are ~1000× the expected contention. `Stop` fails open: its gate
  needs session state to decide, so blocking on none would block turn end on no evidence, and the
  `stop_hook_active` re-entry would still find none.
- `UserPromptSubmit`'s hook timeout is raised from 5 s to 15 s, so a burst has room to drain
  before the deadline. No prompt pays extra latency for it: the graph load happens before the
  lock, and the larger deadline is only ever reached in the pathological case.

## 2.0.3

The Stop gate re-fired against a vault that was already up to date. It counted a vault write
only when it arrived through the `Edit`/`Write`/`MultiEdit` tools, so an update written through
the shell — a heredoc, `sed -i`, `{BRAIN} sync` — left `commits_since_vault_write` armed and the
next commit blocked again. The one-block-per-turn cap hid it inside a turn, which is why it
surfaced as an occasional "Stop hook error" rather than as a consistent one.

### Fixed

- Vault writes are now arbitrated on mtime rather than on the tool that made them, matching how
  commit detection already arbitrates on HEAD: any forward move of the newest `.md` mtime under
  the vault project directory counts, whatever wrote it. `.brain/` is excluded so the plugin's
  own graph-cache regeneration cannot clear the gate, and both the commit handler's `branch:`
  frontmatter write and tool-mediated vault edits re-baseline, so the plugin never reads its own
  writes — or the same edit twice — as a vault update.

## 2.0.2

Concept relevance. Measured on a 21-concept vault: only 2–3 of the 12 "most-connected nodes"
injected at session start belonged to the current project, and a prompt containing the word
"concepts" or "projects" retrieved the vault's busiest concepts regardless of topic.

### Changed

- `graph top` (and the SessionStart hub list) is scoped to the current project: the project's
  own neighbourhood — anchor plus two hops over every edge type except `mentions` — ranks
  first; vault-wide hubs only fill whatever room is left. The header now names the project.
- Retrieval and `graph find` no longer substring-match a vault note's absolute path, so
  directory names (`concepts`, `projects`, the vault root's own path components) are not
  hits. Repo-relative code paths (`src/auth`) still match.
- Concept hits and hub lines carry the note's first sentence (`— Docker · Container runtime
  used for…`, capped at 120 characters) so a hit answers "what is this" without a Read.

### Added

- `graph lint`, `sync-prepare` and the session-start health line report concept notes whose
  frontmatter lacks the `concept:` and `type:` keys the template requires.

## 2.0.1

### Fixed

- `PreCompact`: the checkpoint message asked for the entry to be enriched "before the compact
  proceeds", which no model turn can do — Claude Code compacts immediately after the hook.
  The message now says to enrich after compaction, and SessionStart (`compact`/`resume`)
  nudges Claude when the last `log.md` entry is still a `(pre-compact)`/`(auto-close)`
  checkpoint with placeholder Completed/Decided lines — the first turn that can act on it.
- SessionStart no longer prints `(expected: unset)` after compaction when `context.md`
  declares no branch.

## 2.0.0

A rewrite of the runtime. v1 was a markdown behavioural spec plus four bash hook scripts
copied into `~/.claude` and registered per project; v2 is a stdlib-Python package the plugin
ships and runs itself, with a derived knowledge graph and a per-project code map on top.

Upgrading is automatic — see Migration below. No vault content changes shape. The upgrade
itself rewrites only a stale `path:` in `context.md`; the first v2 session then runs the
concept lint, which auto-applies up to five manifest-dependency links (a `uses::` line in
`context.md` and a `## Used by` row in the matching concept note) and reports every one of
them — `/brain graph dismiss <slug>` makes a link stay gone.

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
- **`/brain status` no longer writes to the vault.** It used to auto-apply pending
  manifest-dependency links like SessionStart and `sync-prepare`; being display-only, it now
  reports them as pending instead (`/brain sync` still applies them).

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
