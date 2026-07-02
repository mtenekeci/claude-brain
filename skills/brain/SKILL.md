---
name: brain
description: Use when the user types /brain, /brain init, /brain load, /brain sync, /brain status, /brain config, /brain remove, or /brain disconnect. Manages Claude's Obsidian second brain for persistent project context across sessions.
---

# Brain — Obsidian Second Brain

## Config resolution (run at the start of every command)

Config file: `~/.claude/brain.config`

Format:
```json
{
  "vault": "/absolute/path/to/your/obsidian/vault"
}
```

**Steps:**
1. Check if `~/.claude/brain.config` exists.
2. If it exists: read the file, set `VAULT_ROOT` to the `vault` field value.
3. If it does NOT exist (first run): this is handled inside `/brain init` — see the "Resolve vault path" step there which auto-discovers vaults. For all other commands (`load`, `sync`, `status`), if config is missing, say: "Brain is not configured yet. Run `/brain init` first."

Derived constants (set after reading config):
```
VAULT_ROOT     = <vault field from config>
PLUGIN_DIR     = ${CLAUDE_PLUGIN_ROOT}
VAULT_SYSTEM   = <VAULT_ROOT>/_system
VAULT_PROJECTS = <VAULT_ROOT>/projects
VAULT_CONCEPTS = <VAULT_ROOT>/concepts
```

`PLUGIN_DIR` is Claude Code's built-in `${CLAUDE_PLUGIN_ROOT}` environment variable — it always points at the plugin's current install directory (marketplace cache, versioned or not, symlinked, or local dev) and is set automatically for every plugin invocation, so it never needs a "does this path exist" fallback. Two usage forms:
- **In Bash commands** (e.g. `cp` in the Hook health check): write `${CLAUDE_PLUGIN_ROOT}` literally in the command string — the shell resolves it when the Bash tool executes.
- **In Read instructions** (Read tool calls take a literal path, not shell syntax): resolve `PLUGIN_DIR` from the "Base directory for this skill" path shown in this invocation's context, stripping the trailing `/skills/brain` segment — then substitute that concrete path wherever `<PLUGIN_DIR>` appears below.

---

## Linking rules (apply when writing any vault file)

Always use Obsidian wikilinks when referencing other vault files. This builds the graph view automatically.

| What you're writing | Link format |
|---|---|
| Reference to a project's context | `[[projects/<slug>/context\|<slug>]]` |
| Reference to a project's architecture | `[[projects/<slug>/architecture\|<slug> architecture]]` |
| Reference to a project's log | `[[projects/<slug>/log\|<slug> log]]` |
| Reference to project index | `[[_system/project-index\|Project Index]]` |
| Cross-project reference in context.md | `[[projects/<other-slug>/context\|<other-slug>]]` |
| Reference to a concept note | `[[concepts/<concept-slug>\|<Concept Name>]]` |

**When to add links:**
- `context.md` — link any mentioned related projects using `[[projects/<slug>/context\|<slug>]]`; link to architecture.md at the bottom of `## Architecture` section
- `architecture.md` — link back to context.md in the breadcrumb; link to related projects if relevant; link to a concept note when the Concept graph promotion rule applies (see below)
- `log.md` — link to `context.md` at the top (already in template)
- `project-index.md` — every slug cell is a wikilink (handled in `/brain init` and `/brain sync`)
- Decisions section — if a decision relates to another project, link it; if it's a `decision`-type concept (reach beyond this project), link its concept note too

**Never use plain text** where a wikilink could go. Every connection you write becomes an edge in the Obsidian graph.

**Contextual wikilinks (apply on every vault write):**
Whenever writing or updating any prose section in a vault file — during `/brain init` Step G, `/brain sync`, or any mid-session write protocol update — scan for plain mentions of known project slugs and replace with wikilinks.

`KNOWN_SLUGS` source by context:
- `/brain init`: from `project-index.md` read during "Check for duplicate slug" — no extra read needed.
- `/brain sync`: from the explicit "Load known slugs" step at the start of sync.
- Mid-session write (e.g. Architecture update after code exploration): read `<VAULT_ROOT>/_system/project-index.md` to get current slugs before writing. One read, cached for the rest of the session.

For each slug found as a standalone word (not already inside `[[...]]`, not inside code blocks or frontmatter): replace with `[[projects/<slug>/context\|<slug>]]`.

This runs only on writes, never on session-start reads — zero token cost at load time.

---

## Concept graph (mindmap)

`VAULT_CONCEPTS` (`<VAULT_ROOT>/concepts/`) holds atomic notes for reusable architectural entities. Unlike `context.md`/`architecture.md` — one prose-heavy set per project — each concept note is small and addressable, and becomes a hub node in Obsidian's graph view, including hubs shared across multiple projects (e.g. a library two projects both depend on).

### Taxonomy

Only these four types get a concept note. Anything else stays an `architecture.md` bullet.

| Type | What it covers | Examples |
|---|---|---|
| `library` | An external dependency | Zustand, Stripe SDK, Redis client |
| `subsystem` | A named, composed piece of one project's architecture | "auth flow", "sync engine", "event bus" |
| `infra` | Infrastructure / deployment components | Postgres, CI pipeline, hosting platform |
| `decision` | A decision with reach beyond the project that made it | "all services share one Postgres instance" |

### Promotion rule

Apply this during the existing "non-obvious discovery → architecture.md bullet" trigger in the Autonomous write protocol below. It is not a separate pass, not a sync-time step, and not proactive graph-building.

When a discovery would normally become an `architecture.md` bullet, also ask: **would I plausibly write "see `[[X]]`" from more than one place** (another file, another decision, or another project)?

- **No** → `architecture.md` bullet only, as before. Most discoveries end here — this is the common case.
- **Yes** → it's a concept node:
  1. Derive `CONCEPT_SLUG`: lowercase, hyphenated form of the concept's name (e.g. "Zustand" → `zustand`, "Sync Engine" → `sync-engine`).
  2. Check whether `<VAULT_CONCEPTS>/<CONCEPT_SLUG>.md` already exists — this check is how cross-project and cross-file sharing happens. Never create a second note for the same entity.
     - Doesn't exist → create `<VAULT_CONCEPTS>/<CONCEPT_SLUG>.md` with this exact structure (fill in the bracketed fields):
       ```markdown
       ---
       concept: {Concept Name}
       type: {library|subsystem|infra|decision}
       updated: {YYYY-MM-DD}
       ---

       # {Concept Name}

       {1-3 sentence description — what it is, and why it matters to the projects below}

       ## Used by
       - [[projects/{slug}/context|{slug}]] — {one-line note on how this project uses it}
       ```
     - Exists → append a line to `## Used by` for this project/context (with a one-line note on how *this* context uses it). Do not rewrite other projects' existing lines.
  3. Reference it from the `architecture.md` bullet (or the `## Decisions` entry, for `decision`-type concepts): `... — see [[concepts/<CONCEPT_SLUG>|<Concept Name>]]`.

This is the only new write triggered by this feature — no separate sync pass, no new hook. The concept graph grows exactly in proportion to actual reuse.

### Concepts directory housekeeping

- `<VAULT_CONCEPTS>/` is created during `/brain init` (vault initialization) and self-healed by the Hook health check for vaults created before this feature existed.
- Concept notes are never deleted automatically. If a concept becomes unused (all `## Used by` entries removed), leave the note — it's cheap and may be reused later.

---

## Autonomous write protocol

These rules apply at all times — not just when `/brain` commands are invoked. They govern when Claude writes to the vault without being explicitly asked.

### When to write

**Non-negotiable checkpoints — enforced by hooks, act immediately:**

| Trigger | What to write | Timing |
|---|---|---|
| About to run `git push` | Run `git branch --show-current` and compare to the expected sub-branch named in `## Active Work`. If they differ, STOP — surface the mismatch to the user before pushing. Also re-read `## Hard Rules` to confirm nothing is being violated. | Before push executes |
| `git commit` runs (detected by PostToolUse hook on Bash tool) | Update `## State` + `## Active Work` in context.md | Before the next response |
| Subagent (Agent tool) completes (detected by PostToolUse hook) | If new patterns found → architecture.md bullet; if feature complete → full context.md update | Before the next response |
| You read a source file and discovered a non-obvious fact | Add to `architecture.md` before your next tool call (if `architecture.md` doesn't exist yet, add to `context.md ## Architecture` and create `architecture.md` at the next sync). Also apply the Concept graph promotion rule — if it's a library/subsystem/infra/decision someone would plausibly link to from elsewhere, create/update its note in `VAULT_CONCEPTS` and link it from the bullet. | Before the next tool call |
| A decision was made or confirmed | Add to `context.md ## Decisions` immediately. Do not wait for sync. | Immediately |
| An open question was resolved | Remove it from `context.md ## Open Questions` immediately. | Immediately |

**Advisory triggers — self-enforce these:**

| Trigger | What to write |
|---|---|
| You've made 15+ tool calls without a vault write | Pause. Ask: "Did I learn anything that belongs in Architecture, Decisions, or Open Questions?" If yes, write it now before continuing. |
| A discrete task completed (bug fix, feature, investigation, refactor) | Before writing your final response: update `## State` + `## Active Work`, append a `log.md` entry. |
| The user signals they are done ("thanks", "done", "good", "bye", "ship it", "looks good", "that's all", "close this") | Write log entry immediately without being asked, then confirm it is saved. |

**Superpowers skill integration — non-negotiable:**

| Trigger | Brain action | Timing |
|---|---|---|
| `brainstorming` skill invoked | Read context.md + last log entry before asking any questions (this IS Step 1 of brainstorming) | Before first clarifying question |
| Approaching approach proposals in brainstorming | Read architecture.md in full — proposing approaches is an architectural decision (Tier 2) | Before Step 4 |
| Design approved in brainstorming | Write approved decisions to `## Decisions` | Immediately |
| `subagent-driven-development` skill invoked | Read context.md + architecture.md before first implementer dispatch | Before first Agent call |
| Dispatching any subagent (Agent tool) | Brief it on the vault — see "Briefing subagents on the vault" below. It starts cold; no SessionStart hook fires for it. | In the dispatch prompt itself |
| Agent task completes during subagent-driven-development | Act on PostToolUse hook reminder — check architecture.md for new patterns, update Active Work if needed | Before next Agent dispatch |
| All subagent tasks complete | Full vault sync: State + Active Work + log entry | Before finishing-a-development-branch |

**Briefing subagents on the vault — non-negotiable for every dispatch:**

A subagent has no `SessionStart` hook — it never sees `context.md`/`architecture.md` unless the dispatch prompt puts it there. Every `Agent` tool call you make MUST:
1. Name the vault path (`<VAULT_ROOT>/projects/<slug>/`) and tell the subagent to read `context.md` (+ `architecture.md` for design/implementation tasks) before starting.
2. Inline any Hard Rule or Architecture fact specific to that subagent's slice of work directly into the prompt text — don't rely on it finding the file.
3. Ask it to report new patterns/decisions back in its final message. The subagent does not write to the vault; you do, once it returns — single-owner writes avoid races across parallel subagents.

### The key mental model

Vault writes are not a separate chore after the task — they are the final step of every meaningful task. A session that ends without a log entry is incomplete.

If you had to open a source file because the vault didn't have the answer, that is a vault gap. Write the answer to Architecture before you respond, so the next session doesn't pay the same cost.

### What "immediate" means

For Architecture bullets and Decisions: write before your next tool call. You just learned something — commit it to the vault while the context is fresh.

For task-completion writes (State + Active Work + log entry): write before you send your final response. The user reads "done" — the vault must reflect that too.

### Minimal vs full write

**Minimal** (small tasks — single file change, quick answer):
- One Architecture bullet if a source file was read and revealed something non-obvious
- One-line Active Work update if status changed
- No log entry required

**Full sync** (required when: multiple files read, a decision made, a bug diagnosed and fixed, or meaningful time spent):
- Update `## State`, `## Active Work`, any changed sections
- Append log entry to `log.md`
- Update `last-active` in `project-index.md`

When in doubt: write more, not less. Token cost of a vault write is trivial compared to the cost of re-discovering the same facts next session.

---

## Brain section health check

A reusable sub-procedure. Run this whenever CLAUDE.md is read to identify the current project (i.e. in `/brain sync` and `/brain status`). It self-heals outdated brain sections silently.

### What to check

After reading `CLAUDE.md` and extracting the slug, check whether the brain section (everything before the first `---` separator) contains `## Superpowers integration`, `## Briefing subagents on the vault`, and `## Concept graph`.

- If it does → brain section is current. Continue.
- If it does not → brain section is outdated. Run the update below.

### How to update

1. Extract the `vault:` line value from the existing brain section (e.g. `/Users/foo/Documents/claude-brain/projects/my-app`).
2. Build the new brain section using the current template:
   ```
   # Brain: <project display name or slug>

   vault: <vault line value>

   ## Context protocol
   On session start:
   1. Read `context.md` in full
   2. Read last entry of `log.md` only

   **A compacted conversation summary is not a vault read.** Even if the thread already contains dense, accurate-looking project context, you must still read `context.md` at session start. The summary does not contain Hard Rules or the full write protocol. Do not rationalize it away.

   **Branch reconciliation after resume.** Compaction summaries often freeze a stale branch name as "current" — treat them as untrusted on branch state. After reading `context.md`, if you are about to run any git operation (push, merge, PR), run `git branch --show-current` and reconcile against the expected sub-branch in `## Active Work`. If they differ, surface the mismatch to the user before acting.

   During the session — load more when needed, not upfront:
   3. Before any architectural decision or significant design choice → read `architecture.md` in full (Tier 2)
   4. Before any significant design choice → also read last 5 `log.md` entries (Tier 2)
   5. When asked about history, past decisions, or "what did we do about X" → read full `log.md` (Tier 3)
   6. When context.md feels incomplete for the current task → re-read it

   **Vault before code — always:**
   Before opening any source file to understand how something works, check the `context.md` Architecture section first. Only open the file if the vault doesn't have the answer. If you had to open the file because the vault was missing it — that is a vault gap: update Architecture after reading so the next session doesn't pay the same cost.

   Never answer from memory when the vault has the authoritative record.

   ## Write protocol

   **Non-negotiable checkpoints — enforced by hooks, act immediately:**

   | Trigger | What to write | Timing |
   |---|---|---|
   | `git commit` runs | Update `## State` + `## Active Work` in context.md | Before the next response |
   | About to run `git push` | Run `git branch --show-current` and compare to the expected sub-branch named in `## Active Work`. If they differ, STOP and surface the mismatch before pushing. Also re-read `## Hard Rules`. | Before push executes |
   | Subagent (Agent tool) completes | If new patterns found → architecture.md bullet; if feature complete → full context.md update | Before the next response |
   | Source file read revealed something non-obvious | One architecture.md bullet. If it's a library/subsystem/infra/decision someone would plausibly link to from elsewhere ("see [[X]]" from >1 place), also create/update its note in `<vault-root>/concepts/` (see ## Concept graph) and link it from the bullet. | Before the next tool call |
   | Decision made | Add to `## Decisions` | Immediately |
   | Open question resolved | Remove from `## Open Questions` | Immediately |

   **Advisory triggers — self-enforce these:**

   | When | Write |
   |---|---|
   | 15+ tool calls since last vault write | Pause — check if architecture.md, Decisions, or Open Questions need updating |
   | Discrete task completed (bug fix, feature, investigation) | Update State + Active Work + append log entry, before final response |
   | User signals done ("thanks", "done", "good", "bye", "ship it", "looks good") | Write log entry immediately, confirm saved |

   **Minimal write** (small task, single file): one entry added to `architecture.md` if something non-obvious was discovered. No log entry needed.

   **Full write** (multiple files read, decision made, bug fixed, meaningful work): update State + Active Work + all changed sections, append log entry.

   Before `/compact`: write session summary to `log.md`, compress `context.md` if >150 lines.

   ## Sync is part of the job
   Writing to the vault is not a separate chore — it is the last step of every meaningful task. Do not wait to be asked. A session that ends without a log entry is incomplete.

   ## context.md rules
   - Hard cap: 150 lines. Compress, never delete.
   - Decisions beyond 5 entries: compress each to one line
   - Resolved open questions: remove immediately
   - Architecture section: 3-5 bullet summary only — the most critical facts for immediate orientation. All detail lives in `architecture.md`. Always ends with: `Full reference: [[projects/<slug>/architecture|Architecture]]`

   ## architecture.md rules
   - No line cap — depth is the point.
   - Add a new entry whenever a non-obvious pattern, convention, or structure is discovered.
   - Sections grow over time — never compress or delete, only add and correct.
   - Loaded on demand (Tier 2) — before architectural decisions, not at session start.
   - Bullets that reference a shared library, subsystem, infra component, or cross-reaching decision should link to its concept note: `— see [[concepts/<slug>|<Name>]]` (see ## Concept graph).

   ## Concept graph

   `<vault-root>/concepts/` holds atomic notes for reusable architectural entities — libraries, named subsystems, infra components, and decisions with reach beyond this project. These become hub nodes in Obsidian's graph view, including hubs shared across multiple projects.

   **Taxonomy** — only these four types get a concept note: `library`, `subsystem` (a named, composed piece of the architecture, e.g. "auth flow"), `infra`, `decision` (with reach beyond this project). Anything else stays an architecture.md bullet.

   **Promotion rule** — applied at the same moment as the existing "non-obvious discovery → architecture.md bullet" trigger, not as a separate pass. Ask: would I plausibly write "see `[[X]]`" from more than one place (another file, decision, or project)?
   - No → architecture.md bullet only, as before.
   - Yes → derive `CONCEPT_SLUG` (lowercase, hyphenated name), then check `<vault-root>/concepts/<CONCEPT_SLUG>.md`:
     - Doesn't exist → create `<vault-root>/concepts/<CONCEPT_SLUG>.md` with this structure:
       ```
       ---
       concept: {Concept Name}
       type: {library|subsystem|infra|decision}
       updated: {YYYY-MM-DD}
       ---

       # {Concept Name}

       {1-3 sentence description}

       ## Used by
       - [[projects/{slug}/context|{slug}]] — {one-line note}
       ```
     - Exists → append this project to `## Used by` (don't rewrite other entries — this is how cross-project sharing works).
     - Link it from the architecture.md bullet (or `## Decisions` entry): `— see [[concepts/<CONCEPT_SLUG>|<Concept Name>]]`.

   Concept notes are never deleted automatically.

   ## Superpowers integration

   When superpowers skills run in this project, these checkpoints are non-negotiable:

   **brainstorming skill** (hook fires on invocation):
   - Before asking any clarifying questions → read context.md + last log entry. This IS Step 1 "Explore project context" — not a preliminary, the actual step.
   - Before proposing approaches → read architecture.md in full (Tier 2 trigger: this is a design decision).
   - When design is approved → write decisions to `## Decisions` immediately, before the spec is committed.

   **subagent-driven-development skill** (hook fires on invocation):
   - Before dispatching the first implementer → read context.md + architecture.md.
   - After each subagent task completes (Agent PostToolUse hook reminder) → act on it before dispatching the next subagent. Continuous execution is not a reason to skip.
   - After ALL tasks complete → full vault sync (State + Active Work + log entry) before finishing-a-development-branch.

   ## Briefing subagents on the vault

   A dispatched subagent (Agent tool) starts cold — no `SessionStart` hook fires for it, so it has never seen `context.md` or `architecture.md` unless you put that in front of it. Every implementer/researcher prompt you write MUST:
   1. **Name the vault path** (`<vault>/projects/<slug>/`) and instruct the subagent to read `context.md` — and `architecture.md` too, if the task involves non-trivial design or touches existing patterns — before starting work.
   2. **Inline the sharp edges directly** — any Hard Rule or Architecture fact specific to that subagent's slice of work goes in the prompt text itself, verbatim. Don't gamble on the subagent finding it.
   3. **Ask it to report back** any new pattern, convention, or decision it discovered, in its final message. The subagent does not write to the vault — you do, once it returns. This keeps vault writes single-owner and avoids concurrent-write races across parallel subagents.
   ```
3. In the existing `CLAUDE.md`, replace everything from the first line up to and including the first `---` separator with the new brain section followed by `\n---\n`.
4. Write the file back. Do not touch anything after the `---` separator.
5. Print one line: `Brain: CLAUDE.md updated to latest template.`

---

## Hook health check

A reusable sub-procedure. Run this whenever CLAUDE.md is read to identify the current project (i.e. in `/brain sync` and `/brain status`). Ensures all hook scripts exist and are registered.

### Step 1 — Ensure all 4 hook scripts are installed

Run the following bash commands to copy and make executable (do not embed script content inline — always copy from the plugin hooks directory):

```bash
cp "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh" ~/.claude/brain-session-start.sh
cp "${CLAUDE_PLUGIN_ROOT}/hooks/precompact.sh" ~/.claude/brain-precompact.sh
cp "${CLAUDE_PLUGIN_ROOT}/hooks/session-end.sh" ~/.claude/brain-session-end.sh
cp "${CLAUDE_PLUGIN_ROOT}/hooks/post-tool-use.sh" ~/.claude/brain-post-tool-use.sh
chmod +x ~/.claude/brain-session-start.sh ~/.claude/brain-precompact.sh ~/.claude/brain-session-end.sh ~/.claude/brain-post-tool-use.sh
```

This always runs — `${CLAUDE_PLUGIN_ROOT}` is set by Claude Code for every plugin invocation, so there's no path-existence fallback needed (a prior version of this step silently skipped when a hardcoded, version-specific path didn't exist, which meant hook updates never actually deployed).

### Step 1.5 — Configure git hooks path if needed

If a `.githooks/` directory exists in the current project root:

```bash
git config core.hooksPath .githooks
```

This activates committed git hooks (e.g. the pre-commit guard that blocks direct commits to `main`). Skip silently if `.githooks/` does not exist.

### Step 2 — Skip permission checks

All permissions (vault-level and project-level) are set once during `/brain init`. They do not need to be checked or repaired on every health check run. If permissions are missing, the user will be prompted when the operation that needs them runs — at which point they can approve or re-run `/brain init`.

### Step 3 — Ensure `architecture.md`, `## Hard Rules`, and `concepts/` exist

**Part A: architecture.md**

Check if `<VAULT_ROOT>/projects/<slug>/architecture.md` exists.

If it does NOT exist (old project initialized before architecture.md was introduced):
1. Read the current `## Architecture` section from `context.md`.
2. Create `architecture.md` using the standard template header (see `/brain init` step 3), then add a `## Key Patterns & Conventions` section populated from the Architecture bullets extracted from `context.md`.
3. In `context.md`, replace the full `## Architecture` section content with a 3-5 bullet summary and the wikilink: `Full reference: [[projects/<slug>/architecture|Architecture]]`
4. Write both files.

**Part B: Hard Rules section**

Check if `context.md` contains `## Hard Rules`.

If it does NOT exist (old project initialized before Hard Rules was added):
1. Read `context.md`.
2. Insert a new `## Hard Rules` section immediately before `## Constraints`, with placeholder text: `None documented yet.`
3. Write `context.md` back.

**Part C: concepts/ directory**

Check if `<VAULT_CONCEPTS>` (`<VAULT_ROOT>/concepts/`) exists.

If it does NOT exist (vault created before the concept graph feature): create it with `mkdir -p <VAULT_CONCEPTS>`. No file population needed — it starts empty and grows via the Concept graph promotion rule.

### Step 4 — Ensure all 4 hooks are registered in `.claude/settings.json`

Read `<current working directory>/.claude/settings.json`.

For each of the 4 hook event types (`SessionStart`, `PreCompact`, `SessionEnd`, `PostToolUse`): check if a hook entry with the corresponding `~/.claude/brain-*.sh` command is already present. If not, add it using the same rules as `/brain init` (add under `hooks` key, preserve existing entries, never overwrite non-hooks keys).

### Step 5 — Report

If any scripts were written, registrations added, or permissions repaired, print one line:
`Brain: updated (added: <list of what changed>).`

If everything was already current, print nothing.

---

## /brain init

Initialize a new project in the vault and wire up session automation.

### Resolve vault path

Check if `~/.claude/brain.config` exists.

If it already exists: read it, set `VAULT_ROOT` from the `vault` field. Skip everything below.

If it does NOT exist (first run):

**Step 1 — Detect OS**

Run: `uname -s`
- Output `Darwin` → macOS
- Output `Linux` → Linux
- Otherwise → treat as Linux

**Step 2 — Scan for existing Obsidian vaults**

Search for directories containing a `.obsidian/` subdirectory in these locations (in order):

macOS scan paths:
```
~/Documents/
~/
~/Desktop/
~/Library/Mobile Documents/iCloud~md~obsidian/Documents/
```

Linux scan paths:
```
~/Documents/
~/
```

For each scan path, run (example for `~/Documents/`):
```bash
find ~/Documents -maxdepth 2 -name ".obsidian" -type d 2>/dev/null | sed 's|/.obsidian$||'
```

Collect all results into a list of vault candidates. De-duplicate. Remove any path that is itself inside another candidate (avoid listing both a vault and its parent).

**Step 3 — Present discovery results**

Case A — No vaults found:
Ask: "No Obsidian vaults found. Enter your vault path (default: `~/Documents/claude-brain`):"
If the user presses Enter or provides no input, use `~/Documents/claude-brain`.

Case B — Exactly one vault found at `<path>`:
Ask: "Found Obsidian vault at `<path>`. Use this? [Y/n]"
- If yes (or Enter): use `<path>`.
- If no: ask "Enter your vault path (default: `~/Documents/claude-brain`):" and use input or default.

Case C — Multiple vaults found:
Print:
```
Found multiple Obsidian vaults:
  1. /path/to/vault-one
  2. /path/to/vault-two
  3. Enter a different path
```
Ask: "Which vault should Brain use? (enter number)"
- If user picks 1 or 2 (etc.): use that path.
- If user picks the "Enter a different path" option: ask for the path manually.

**Step 4 — Save config**

Expand `~` to the absolute home directory path.
Write `~/.claude/brain.config`:
```json
{
  "vault": "<absolute vault path>"
}
```
Set `VAULT_ROOT` to that path.

**Step 5 — Grant vault permissions**

Read `~/.claude/settings.json`. Add the following entries to `permissions.allow` if not already present:
- `Read(<VAULT_ROOT>/**)`
- `Write(<VAULT_ROOT>/**)`
- `Edit(<VAULT_ROOT>/**)`
- `Read(<HOME>/.claude/brain.config)`
- `Read(<HOME>/.claude/settings.json)`
- `Edit(<HOME>/.claude/settings.json)`
- `Bash(cat ~/.claude/brain.config*)`
- `Bash(ls <VAULT_ROOT>/**)`
- `Bash(find <VAULT_ROOT>/**)`
- `Bash(mkdir -p <VAULT_ROOT>/**)`
- `Bash(cp "${CLAUDE_PLUGIN_ROOT}"/hooks/**)`
- `Bash(chmod +x ~/.claude/brain-*)`
- `Bash(mkdir -p <PROJECT_PATH>/.claude)`
- `Bash(cat <PROJECT_PATH>/.claude/settings.json*)`
- `Write(<PROJECT_PATH>/.claude/settings.json)`
- `Edit(<PROJECT_PATH>/.claude/settings.json)`

Rules (same pattern as PreCompact hook installation):
- If `~/.claude/settings.json` does not exist: create it with only the permissions block.
- If it exists but has no `permissions` key: add it.
- If `permissions` exists but no `allow` key: add it as an empty array first.
- For each entry: check if it is already in the array before appending. Skip if present.
- Never overwrite non-permissions keys.

This is a one-time setup — subsequent `/brain init` calls for new projects in the same vault skip this silently since the entries are already present.

### Gather project details

Ask the user in sequence:
1. "What is the project name?"
2. "Code project (tied to a folder) or topic project?" — expected answer: `code` or `topic`

Derive slug: lowercase the name, replace spaces and non-alphanumeric characters with hyphens, collapse consecutive hyphens to one.
Examples: `"My App"` → `my-app`, `"IMTF Auth Redesign"` → `imtf-auth-redesign`

### Ensure vault is initialized

Check if `<VAULT_ROOT>/_system/` exists.

If it does NOT exist:
1. Create directory `<VAULT_ROOT>/_system/`
2. Create directory `<VAULT_ROOT>/projects/`
3. Read `<PLUGIN_DIR>/templates/BRAIN.md` verbatim.
   Write it to `<VAULT_ROOT>/_system/BRAIN.md`.
4. Write `<VAULT_ROOT>/_system/project-index.md`:
   ```markdown
   # Project Index

   | project | type | path | last-active |
   |---------|------|------|-------------|
   ```

Regardless of whether `_system/` already existed, ensure `<VAULT_ROOT>/concepts/` exists (`mkdir -p` — see ## Concept graph; starts empty, grows via the promotion rule). This covers vaults configured before v1.5.0.

### Check for duplicate slug

Read `<VAULT_ROOT>/_system/project-index.md`.
If the derived slug already appears in the table as a row value, stop and say:
> "Project '`<slug>`' already exists in the vault. Use `/brain status` to see its current state, or choose a different name."

### Create project in vault

1. Create directory: `<VAULT_ROOT>/projects/<slug>/`

2. Seed `context.md` — gather existing project knowledge before writing:

   **Step A — Detect if this is an existing project**

   Run:
   ```bash
   git -C . rev-parse --is-inside-work-tree 2>/dev/null && echo "has_git" || echo "no_git"
   find . -maxdepth 1 -not -name '.' -not -name '.git' -not -name '.claude' 2>/dev/null | wc -l
   ```
   If `has_git` OR file count > 2 → existing project. Use full seeding below.
   If brand new empty folder → use template with shallow listing (skip to Step G).

   **Step B — Read project manifest / tech stack**

   Try each in order, use the first that exists:
   ```bash
   cat package.json 2>/dev/null
   cat pyproject.toml 2>/dev/null
   cat Cargo.toml 2>/dev/null
   cat go.mod 2>/dev/null
   cat composer.json 2>/dev/null
   cat pom.xml 2>/dev/null
   cat build.gradle 2>/dev/null
   ```
   Extract: project name (if different from slug), language/runtime, key dependencies.

   **Step C — Read README**

   ```bash
   cat README.md 2>/dev/null || cat README.rst 2>/dev/null || cat README 2>/dev/null
   ```
   Extract: project purpose, description, any documented features.

   **Step D — Read git history and remote**

   ```bash
   git log --oneline -30 2>/dev/null
   git log --oneline --since="90 days ago" 2>/dev/null | wc -l
   git branch -a 2>/dev/null
   git remote get-url origin 2>/dev/null
   ```
   Extract: what has been built (commit messages), how active the project is, feature branches. If a remote URL is returned, store it as `REPO_URL` — used in the `repo:` frontmatter field and breadcrumb link. If no remote, `REPO_URL` is unset.

   **Step E — Read existing CLAUDE.md**

   ```bash
   cat CLAUDE.md 2>/dev/null
   ```
   If it exists, extract any documented decisions, constraints, or context already written there. This is the highest-signal source — treat it as ground truth.

   **Step E2 — Optional deep architecture scan (existing projects only)**

   Ask: "Run deep architecture scan? Reads up to 10 key source files to seed the Architecture section with real patterns and conventions. Recommended for existing projects. [Y/n]"

   If no: skip to Step F.

   If yes:

   1. Find entry points — the files most likely to reveal overall structure:
   ```bash
   find . -maxdepth 4 \( -name "index.ts" -o -name "index.tsx" -o -name "main.ts" -o -name "main.tsx" -o -name "app.ts" -o -name "app.tsx" -o -name "server.ts" -o -name "index.js" -o -name "main.py" -o -name "app.py" -o -name "main.go" \) \
     ! -path "*/node_modules/*" ! -path "*/.git/*" ! -path "*/dist/*" ! -path "*/build/*" \
     2>/dev/null | head -5
   ```

   2. Find recently touched source files — highest signal for active patterns:
   ```bash
   git log --name-only --format="" -30 2>/dev/null \
     | grep -E "\.(ts|tsx|js|jsx|py|go|rs|rb|java|kt|swift)$" \
     | grep -v -E "(node_modules|\.test\.|\.spec\.|dist/|build/)" \
     | sort -u | head -8
   ```

   3. Combine both lists, deduplicate, cap at 10 files total. Read each file.

   4. From all files read, extract into `DEEP_SCAN_NOTES`:
      - Key abstractions and their responsibilities (not just names — what they do and why)
      - Patterns used consistently across the codebase (naming, data flow, error handling)
      - Non-obvious conventions a new session would need to know (e.g. "all DB calls go through X wrapper", "auth is enforced in Y not Z")
      - Anything that would prevent a wrong assumption

   Store `DEEP_SCAN_NOTES` for use in Step G. Skip to Step F.

   **Step F — Read Claude's memory for this project**

   Compute the memory path: take the absolute current working directory, remove the leading `/`, replace all remaining `/` with `-`.
   Example: `/Users/alex/Projects/my-app` → `Users-alex-Projects-my-app`
   Memory path: `~/.claude/projects/<encoded-path>/memory/`

   ```bash
   ls ~/.claude/projects/<encoded-path>/memory/ 2>/dev/null
   cat ~/.claude/projects/<encoded-path>/memory/*.md 2>/dev/null
   ```
   If memory files exist, extract any project facts, decisions, or context stored there.

   **Step G — Synthesize and write context.md**

   Construct the breadcrumb line:
   - Base: `← [[_system/project-index|Project Index]] | [[projects/<slug>/log|Session Log]]`
   - If `REPO_URL` is set: append ` | [GitHub ↗](<REPO_URL>)`

   Using all gathered sources, write `<VAULT_ROOT>/projects/<slug>/context.md` with the following structure. Fill every section with real information — no placeholder text for existing projects:

   ```markdown
   ---
   project: <slug>
   type: <code or topic>
   path: <absolute path or —>
   repo: <REPO_URL or — if none>
   updated: <YYYY-MM-DD>
   up: "[[_system/project-index]]"
   ---

   <breadcrumb line>

   ## State
   <2-3 sentences synthesized from README + git log + CLAUDE.md:
   what the project is, what is working, what stage it is at>

   ## Architecture
   <3-5 bullet summary of the most critical facts a new session needs immediately: tech stack, entry points, key patterns.>
   Full reference: [[projects/<slug>/architecture|Architecture]]

   ## Active Work
   <from last 5-10 git commits or CLAUDE.md active work:
   what appears to be currently in progress>

   ## Decisions
   <from CLAUDE.md, git commit messages, memory:
   up to 5 notable past decisions with one-line rationale each.
   If none found, write "None documented yet.">

   ## Open Questions
   <from CLAUDE.md or memory if any were recorded.
   If none found, write "None yet.">

   ## Hard Rules
   <from CLAUDE.md, git hooks, CI config: non-negotiable workflow rules.
   Examples: "PR required for main branch", "All tests must pass", "Staging before production".
   If none found, write "None documented yet.">

   ## Constraints
   <from CLAUDE.md constraints section or memory if any: technical limitations.
   Examples: "Node 18+", "PostgreSQL 14 only", "Max 1MB file upload".
   If none found, write "None documented yet.">
   ```

   After writing, apply contextual wikilinks (see Linking rules) to all prose sections.

   For a brand new empty project (Step A returned no existing work): use the template defaults with a shallow top-level file listing under Architecture.

3. Write `architecture.md`:

   Create `<VAULT_ROOT>/projects/<slug>/architecture.md` with the following structure:

   ```markdown
   ---
   project: <slug>
   type: architecture
   updated: <YYYY-MM-DD>
   up: "[[projects/<slug>/context|<slug>]]"
   ---

   ← [[projects/<slug>/context|<slug> context]] | [[projects/<slug>/log|Session Log]]

   # <Project Display Name> — Architecture Reference

   > Living document. Update when a new major component, pattern, or constraint is added.

   ---
   ```

   Then append sections populated from the gathered sources (Steps B–F). Include as many sections as are meaningful for the project. Typical sections:

   - `## Technology Stack` — table of layers → technologies
   - `## Repository Layout` — annotated directory tree (code block)
   - `## Key Patterns & Conventions` — non-obvious rules a new session must know to avoid wrong assumptions (e.g. "all DB calls go through X", "auth is enforced in Y not Z", naming conventions)
   - `## Data Flow` — how data moves through the system (if non-trivial)
   - Additional domain-specific sections as needed (Routes, Schema, Integrations, CI/CD, etc.)

   If DEEP_SCAN_NOTES exist: use them to populate Key Patterns & Conventions and any domain-specific sections with real extracted facts — not generic placeholders.

   For a brand new empty project: write only the header and a `## Technology Stack` placeholder section.

   No line cap on `architecture.md`. Depth is the point.

   Apply contextual wikilinks (see Linking rules) to all prose sections.

4. Write `log.md`:
   - Read `<PLUGIN_DIR>/templates/log.md`
   - Replace `{date}` with today's date in `YYYY-MM-DD` format
   - Replace `{slug}` with the slug
   - If existing project: replace the "Project initialized" Completed line with a one-sentence summary of what was found (e.g. "Seeded from existing project — 47 commits, React/TypeScript app for X")
   - Write the result to `<VAULT_ROOT>/projects/<slug>/log.md`

4. Append to `<VAULT_ROOT>/_system/project-index.md`:
   ```
   | [[projects/<slug>/context\|<slug>]] | <type> | <absolute path or —> | <YYYY-MM-DD> |
   ```
   The `\|` escapes the pipe inside the Obsidian wikilink so the table renders correctly. The link points to the project's `context.md` and displays as the slug.

### If code project: write CLAUDE.md to project folder

1. Read `<PLUGIN_DIR>/templates/CLAUDE.md`
2. Replace `{project-name}` with the display name
3. Replace `{slug}` with the slug
4. Replace `{vault-root}` with the absolute `VAULT_ROOT` path
5. Target path: `<current working directory>/CLAUDE.md`
   - If `CLAUDE.md` does not exist: write the file directly
   - If `CLAUDE.md` already exists: prepend the brain section followed by `\n---\n` before the existing content. Do not remove existing content.

### If code project: install PreCompact hook

The PreCompact hook writes a `(pre-compact)` checkpoint entry to `log.md` via bash before the compact, then tells Claude to fill it in. This guarantees the session is recorded even if Claude doesn't act on the reminder.

**Step 1 — Install the hook script to a stable path**

Run:

```bash
cp "${CLAUDE_PLUGIN_ROOT}/hooks/precompact.sh" ~/.claude/brain-precompact.sh
chmod +x ~/.claude/brain-precompact.sh
```

**Step 2 — Add the PreCompact hook to `.claude/settings.json`**

Target: `<current working directory>/.claude/settings.json`

Hook command: `<HOME>/.claude/brain-precompact.sh`

Rules:
- If `.claude/settings.json` does not exist: create `.claude/` directory if needed, write the full hooks block.
- If it exists but has no `hooks` key: add it.
- If `hooks` exists but no `PreCompact` key: add it.
- If `PreCompact` already exists: check if a hook with this command is present. If yes, skip. If no, append.
- Never overwrite non-hooks keys.

### If code project: install PostToolUse hook

The PostToolUse hook has three triggers: (1) counts source file reads and reminds Claude to update architecture.md every 3 reads; (2) detects `git commit` Bash calls and immediately prompts Claude to update context.md State + Active Work; (3) detects Agent tool completions (superpowers tasks) and prompts an architecture/context sync check.

Run:

```bash
cp "${CLAUDE_PLUGIN_ROOT}/hooks/post-tool-use.sh" ~/.claude/brain-post-tool-use.sh
chmod +x ~/.claude/brain-post-tool-use.sh
```

Add to `<current working directory>/.claude/settings.json`:

```json
"PostToolUse": [
  {
    "matcher": "",
    "hooks": [
      {
        "type": "command",
        "command": "<HOME>/.claude/brain-post-tool-use.sh"
      }
    ]
  }
]
```

Apply same rules as other hooks: add under `hooks` key, skip if already present.

### If code project: install SessionStart hook

The SessionStart hook fires before Claude sees the first user message. Its stdout is injected into Claude's context, ensuring the vault is read at session start — not left as an advisory instruction Claude may skip.

Run:

```bash
cp "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh" ~/.claude/brain-session-start.sh
chmod +x ~/.claude/brain-session-start.sh
```

Add to `<current working directory>/.claude/settings.json`:

```json
"SessionStart": [
  {
    "matcher": "",
    "hooks": [
      {
        "type": "command",
        "command": "<HOME>/.claude/brain-session-start.sh"
      }
    ]
  }
]
```

Apply same rules as other hooks: add under `hooks` key, skip if already present.

### If code project: install SessionEnd hook

The SessionEnd hook writes a meaningful auto-close log entry when a session ends without a manual `/brain sync`. If commits were made today, the `Completed` field lists them (up to 5); otherwise it notes that no commits were made. The `Changed` field is built from committed + unstaged files. The next `/brain sync` can replace this with fuller detail if needed.

**Step 1 — Install the hook script to a stable path**

Run:

```bash
cp "${CLAUDE_PLUGIN_ROOT}/hooks/session-end.sh" ~/.claude/brain-session-end.sh
chmod +x ~/.claude/brain-session-end.sh
```

**Step 2 — Add the SessionEnd hook to `.claude/settings.json`**

Add to the same `<current working directory>/.claude/settings.json` used for PreCompact:

```json
"SessionEnd": [
  {
    "matcher": "",
    "hooks": [
      {
        "type": "command",
        "command": "<HOME>/.claude/brain-session-end.sh"
      }
    ]
  }
]
```

Apply the same rules as PreCompact: add under `hooks` key, skip if already present.

### If code project and `.githooks/` present: configure git hooks path

If a `.githooks/` directory exists in the project root:

```bash
git config core.hooksPath .githooks
```

This activates committed git hooks (e.g. branch protection). Skip silently if `.githooks/` does not exist.

### Confirm

Print:
```
Brain initialized for <project-name> (<slug>)

Vault:          <VAULT_ROOT>
Context:        <VAULT_ROOT>/projects/<slug>/context.md
Log:            <VAULT_ROOT>/projects/<slug>/log.md
```

If code project, also print:
```
CLAUDE.md:      <current working directory>/CLAUDE.md
Hooks:          PostToolUse + SessionStart + PreCompact + SessionEnd hooks added to .claude/settings.json
Git hooks:      core.hooksPath set to .githooks (if .githooks/ present)
Permissions:    Vault read/write granted in ~/.claude/settings.json

Every future session in this folder will auto-load vault context.
```

If topic project, print:
```
Permissions:    Vault read/write granted in ~/.claude/settings.json
To load this project in any session: /brain load <slug>
```

---

## /brain load <slug> [<slug2> ...]

Load one or more topic projects' context into the current session. For topic projects only — code projects auto-load via CLAUDE.md.

Accepts multiple space-separated slugs. A slug may also name a **concept** (see Concept graph) instead of a project — loading a concept slug expands to every project listed in that concept's `## Used by` section, as shorthand for loading a related group at once (e.g. `/brain load imatch-data-flow` loads `classic`, `adapter`, and `modern` if that concept's `## Used by` lists all three).

1. Resolve vault path (see Config resolution at top).
2. If `ARGUMENTS` is empty: ask "Which project or concept slug should I load? (run `/brain status` to list projects, or check `<VAULT_CONCEPTS>` for concept groups)" and stop.
3. Parse `ARGUMENTS` on whitespace into `REQUESTED` (the list of slugs given).
4. Resolve each entry in `REQUESTED`:
   - If `<VAULT_ROOT>/projects/<entry>/context.md` exists → resolves to that one project. Project slugs take precedence over a same-named concept.
   - Else if `<VAULT_CONCEPTS>/<entry>.md` exists → read its `## Used by` section, extract every linked project slug from the `[[projects/<slug>/context|<slug>]]` lines, and resolve `<entry>` to that whole set. Remember `<entry>` as a concept expansion — its note gets surfaced in step 8.
   - Else → record `<entry>` in `MISSING`.
5. Deduplicate the combined resolved project-slug list (`RESOLVED`) — the same project may be reached via more than one requested entry.
6. If `RESOLVED` is empty (nothing resolved): report `Not found: <entries in MISSING>. Available projects are listed in <VAULT_ROOT>/_system/project-index.md; concept groups are in <VAULT_CONCEPTS>.` and stop — do not proceed to load.
7. For each slug in `RESOLVED`: read `<VAULT_ROOT>/projects/<slug>/context.md` in full, and read `log.md` — find the last `## ` header and extract from that header to the end of the file (the last session entry).
8. For each entry that resolved via a concept expansion (step 4): also read that concept note (`<VAULT_CONCEPTS>/<entry>.md`) in full — it's the shared-architecture doc that motivated grouping these projects, so surface it, not just the slug list it produced.
9. Hold everything read in working context for this session.
10. Report, in this order:
    - If `MISSING` is non-empty: `Not found: <missing1>, <missing2>` (skip-and-warn — proceed with whatever did resolve).
    - `Loaded: <slug1>, <slug2>, <slug3>` (the final `RESOLVED` list actually loaded).
    - For each concept expansion: `Via concept '<entry>': <its resolved slugs>` followed by that concept note's description.
    - For each loaded project (labeled by slug if more than one): its `## State` section content.

---

## /brain sync

Force a vault write for the current project. Use before a risky change, before a long break, or before switching projects.

### Resolve vault path

See Config resolution at top.

### Identify current project

Check the current working directory for a `CLAUDE.md` file.
If found: read the `vault:` line, extract the slug as the last path segment.
If not found: ask "Which project slug should I sync? (run `/brain status` to list all)"

Set `VAULT_PROJECT = <VAULT_ROOT>/projects/<slug>`

Run **Brain section health check** (see above).
Run **Hook health check** (see above).

### Load known slugs

Read `<VAULT_ROOT>/_system/project-index.md` and extract all project slugs from the table. Store as `KNOWN_SLUGS` — used for contextual wikilinks when updating content.

### Update architecture.md

If architectural facts were discovered this session (new patterns, conventions, or structural changes), append them to the relevant section in `VAULT_PROJECT/architecture.md`. Update the frontmatter `updated:` field.

If `architecture.md` does not exist: run the Step 3 repair from the Hook health check to create it from context.md's Architecture section.

### Update context.md

Read `VAULT_PROJECT/context.md`. Then rewrite these sections:

- `## State` — 2-3 sentences: what exists, what works, what is actively changing right now
- `## Active Work` — what is currently in progress
- `## Decisions` — add any decisions made this session (do not remove existing entries yet)
- `## Open Questions` — remove any questions that were resolved this session; add new ones
- `## Architecture` — keep as a 3-5 bullet summary. If the wikilink to architecture.md is missing, add it: `Full reference: [[projects/<slug>/architecture|Architecture]]`

Line count check: count lines in the updated file.
If count > 150:
- In `## Decisions`, find all entries beyond the 5 most recent. Replace each with a one-line summary: `- [<date>] <one-sentence summary of that decision>`

Update the frontmatter `updated:` field to today's date in `YYYY-MM-DD`.

Apply contextual wikilinks (see Linking rules) to all updated prose sections.

Write the result back to `VAULT_PROJECT/context.md`.

### Append to log.md

Count existing `## ` entries in `log.md` to determine the current session number N.

Check if the last entry is a placeholder written by a hook — `(pre-compact)` or `(auto-close)`:
- If yes: replace that entry in-place with the proper sync content below. N stays the same — the placeholder already counted this session.
- If no: append a new entry. Use N+1 as the session number.

Entry format:
```markdown

## <YYYY-MM-DD> · Session <N or N+1>
Completed: <what was accomplished this session>
Changed: <files or systems touched, or "—" if none>
Decided: <decisions made with one-line reason, or "none">
Next: <what comes next>
```

### Update project-index.md

In `<VAULT_ROOT>/_system/project-index.md`, find the row for this slug and update the `last-active` column to today's date.

### Confirm

Print:
```
Brain synced: <slug>
context.md:   <N> lines (cap: 150)
Session:      <N+1> logged to log.md
```

---

## /brain status

Show the current brain state for this session.

### Resolve vault path

See Config resolution at top.

### Identify current project

Check CLAUDE.md in current directory for the `vault:` line, extract slug as last path segment.
If no project found: read `<VAULT_ROOT>/_system/project-index.md` and print all registered projects, then ask which to inspect.

Run **Brain section health check** (see above).
Run **Hook health check** (see above).

### Read and display

Read `VAULT_PROJECT/context.md`.
Count lines in `VAULT_PROJECT/log.md`, count `## ` entries.

Print:
```
Brain status: <project-name> (<slug>)
Type:         <code or topic>
Vault:        <VAULT_ROOT>
Updated:      <updated date from frontmatter>
Sessions:     <N>
Context size: <line count> / 150 lines

── State ──────────────────────────────
<## State section content>

── Active Work ────────────────────────
<## Active Work section content>

── Open Questions ─────────────────────
<## Open Questions section content>

── Last Session ───────────────────────
<last log.md entry>
```

---

## /brain config

Show or update the vault path.

### /brain config (no args) — show current config

1. Check if `~/.claude/brain.config` exists.
2. If yes: read and print:
   ```
   Brain config: ~/.claude/brain.config
   Vault: <vault path>
   ```
3. If no: "Brain is not configured. Run `/brain init` to set up."

### /brain config set <path>

Update the vault path.

1. Expand `~` to absolute home directory path.
2. Check that the path exists as a directory. If not: "Path does not exist: `<path>`. Create the directory or check the path and try again."
3. Write `~/.claude/brain.config`:
   ```json
   {
     "vault": "<absolute path>"
   }
   ```
4. Print:
   ```
   Vault path updated: <path>
   Config saved to ~/.claude/brain.config
   ```

---

## /brain remove <slug>

Permanently delete a project from the vault. Removes vault files and the project-index row. Also cleans up CLAUDE.md and the PreCompact hook in the project folder if reachable.

1. Resolve vault path (see Config resolution at top).
2. Check that `<VAULT_ROOT>/projects/<slug>/` exists. If not: "Project '`<slug>`' not found in vault."
3. Read `<VAULT_ROOT>/projects/<slug>/context.md` — extract the `path:` frontmatter value as `PROJECT_PATH`. If `path:` is `—`, set `PROJECT_PATH` to unset.
4. Ask for confirmation:
   ```
   This will permanently delete:
     Vault:   <VAULT_ROOT>/projects/<slug>/
     Index:   row removed from project-index.md
   <if PROJECT_PATH set:>
     Also:    CLAUDE.md brain section + PreCompact hook removed from <PROJECT_PATH>

   Type '<slug>' to confirm:
   ```
   Wait for exact match. If input does not match, abort: "Cancelled."
5. Delete `<VAULT_ROOT>/projects/<slug>/` and all contents.
6. In `<VAULT_ROOT>/_system/project-index.md`, remove the row containing `<slug>`.
7. If `PROJECT_PATH` is set and `<PROJECT_PATH>/CLAUDE.md` exists:
   - Read the file. The brain section is the block from the first line up to and including the first `---` separator line.
   - If the brain section is the entire file: delete `<PROJECT_PATH>/CLAUDE.md`.
   - If content follows the `---` separator: remove only the brain section and the separator line, keep the rest.
8. If `PROJECT_PATH` is set and `<PROJECT_PATH>/.claude/settings.json` exists:
   - Read the file. Remove the PreCompact hook object whose `command` contains `BRAIN SYNC REQUIRED`.
   - If the `PreCompact` array is now empty, remove the `PreCompact` key. If `hooks` is now empty, remove the `hooks` key.
   - Write the cleaned JSON back.
9. Print:
   ```
   Removed: <slug>
   Vault files deleted.
   Index row removed.
   <if CLAUDE.md cleaned:> CLAUDE.md brain section removed from <PROJECT_PATH>
   <if hook removed:> PreCompact hook removed from <PROJECT_PATH>/.claude/settings.json
   ```

---

## /brain disconnect <slug>

Stop tracking a project without deleting vault history. Removes the CLAUDE.md brain section and PreCompact hook from the project folder, leaving vault files intact.

1. Resolve vault path (see Config resolution at top).
2. Check that `<VAULT_ROOT>/projects/<slug>/context.md` exists. If not: "Project '`<slug>`' not found in vault."
3. Read `<VAULT_ROOT>/projects/<slug>/context.md` — extract the `path:` frontmatter value as `PROJECT_PATH`.
   If `path:` is `—` or unset: "This project has no folder path set — nothing to disconnect from. Vault files are untouched."
4. Check that `<PROJECT_PATH>/CLAUDE.md` exists. If not: "No CLAUDE.md found at `<PROJECT_PATH>` — project may already be disconnected. Vault files are untouched."
5. Read `<PROJECT_PATH>/CLAUDE.md`. The brain section is the block from the first line up to and including the first `---` separator line.
   - If the brain section is the entire file: delete `<PROJECT_PATH>/CLAUDE.md`.
   - If content follows the `---` separator: remove only the brain section and the separator line, keep the rest.
6. If `<PROJECT_PATH>/.claude/settings.json` exists:
   - Remove the PreCompact hook object whose `command` contains `BRAIN SYNC REQUIRED`.
   - If the `PreCompact` array is now empty, remove the `PreCompact` key. If `hooks` is now empty, remove the `hooks` key.
   - Write the cleaned JSON back.
7. Print:
   ```
   Disconnected: <slug>
   CLAUDE.md brain section removed from <PROJECT_PATH>
   <if hook removed:> PreCompact hook removed.
   Vault files untouched — history preserved at <VAULT_ROOT>/projects/<slug>/
   To reconnect later: /brain init (choose the same slug)
   ```
