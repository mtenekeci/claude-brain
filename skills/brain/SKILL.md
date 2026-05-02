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
PLUGIN_DIR     = ~/.claude/plugins/claude-brain
VAULT_SYSTEM   = <VAULT_ROOT>/_system
VAULT_PROJECTS = <VAULT_ROOT>/projects
```

---

## Linking rules (apply when writing any vault file)

Always use Obsidian wikilinks when referencing other vault files. This builds the graph view automatically.

| What you're writing | Link format |
|---|---|
| Reference to a project's context | `[[projects/<slug>/context\|<slug>]]` |
| Reference to a project's log | `[[projects/<slug>/log\|<slug> log]]` |
| Reference to project index | `[[_system/project-index\|Project Index]]` |
| Cross-project reference in context.md | `[[projects/<other-slug>/context\|<other-slug>]]` |

**When to add links:**
- `context.md` — link any mentioned related projects using `[[projects/<slug>/context\|<slug>]]`
- `log.md` — link to `context.md` at the top (already in template)
- `project-index.md` — every slug cell is a wikilink (handled in `/brain init` and `/brain sync`)
- Decisions section — if a decision relates to another project, link it

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

## Autonomous write protocol

These rules apply at all times — not just when `/brain` commands are invoked. They govern when Claude writes to the vault without being explicitly asked.

### When to write

| Trigger | What to write |
|---|---|
| You read a source file and discovered a non-obvious fact (a pattern, convention, or structure) | One bullet added to `context.md ## Architecture` before your next tool call. The Architecture section is a cache — every fact you write here prevents a future session from re-reading that file. |
| A decision was made or confirmed | Add to `context.md ## Decisions` immediately. Do not wait for sync. |
| An open question was resolved | Remove it from `context.md ## Open Questions` immediately. |
| You've made 15+ tool calls without a vault write | Pause. Ask: "Did I learn anything that belongs in Architecture, Decisions, or Open Questions?" If yes, write it now before continuing. |
| A discrete task completed (bug fix, feature, investigation, refactor) | Before writing your final response: update `## State` + `## Active Work`, append a `log.md` entry. |
| The user signals they are done ("thanks", "done", "good", "bye", "ship it", "looks good", "that's all", "close this") | Write log entry immediately without being asked, then confirm it is saved. |

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
- `Read(<HOME>/.claude/brain.config)`

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
3. Read `~/.claude/plugins/claude-brain/templates/BRAIN.md` verbatim.
   Write it to `<VAULT_ROOT>/_system/BRAIN.md`.
4. Write `<VAULT_ROOT>/_system/project-index.md`:
   ```markdown
   # Project Index

   | project | type | path | last-active |
   |---------|------|------|-------------|
   ```

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
   Example: `/Users/mehmet/Projects/my-app` → `Users-mehmet-Projects-my-app`
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
   <bullets from file structure + manifest: key directories, tech stack, runtime, notable dependencies.
   If DEEP_SCAN_NOTES exist: add bullets for each pattern, abstraction, and convention found — not just directory names. These are the facts that prevent a future session from re-reading the same files.>

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

   ## Constraints
   <from CLAUDE.md constraints section or memory if any.
   If none found, write "None documented yet.">
   ```

   After writing, apply contextual wikilinks (see Linking rules) to all prose sections.

   For a brand new empty project (Step A returned no existing work): use the template defaults with a shallow top-level file listing under Architecture.

3. Write `log.md`:
   - Read `~/.claude/plugins/claude-brain/templates/log.md`
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

1. Read `~/.claude/plugins/claude-brain/templates/CLAUDE.md`
2. Replace `{project-name}` with the display name
3. Replace `{slug}` with the slug
4. Replace `{vault-root}` with the absolute `VAULT_ROOT` path
5. Target path: `<current working directory>/CLAUDE.md`
   - If `CLAUDE.md` does not exist: write the file directly
   - If `CLAUDE.md` already exists: prepend the brain section followed by `\n---\n` before the existing content. Do not remove existing content.

### If code project: install PreCompact hook

The PreCompact hook writes a `(pre-compact)` checkpoint entry to `log.md` via bash before the compact, then tells Claude to fill it in. This guarantees the session is recorded even if Claude doesn't act on the reminder.

**Step 1 — Install the hook script to a stable path**

Write the following script to `<HOME>/.claude/brain-precompact.sh`:

```bash
#!/bin/bash
# Brain PreCompact hook — writes a git-enriched checkpoint entry, then tells
# Claude to fill in Completed and Decided with session knowledge.
# Degrades gracefully if Claude doesn't act — git context is still useful.

set -euo pipefail

VAULT=$(python3 - <<'PY'
import json, os
cfg = os.path.expanduser("~/.claude/brain.config")
if os.path.exists(cfg):
    print(json.load(open(cfg))["vault"])
PY
2>/dev/null) || true

SLUG=$(awk -F'/' '/^vault:/{print $NF}' CLAUDE.md 2>/dev/null | tr -d '[:space:]') || true

if [ -z "$VAULT" ] || [ -z "$SLUG" ]; then
  echo "BRAIN SYNC: Update log.md and context.md before compacting."
  exit 0
fi

LOG="$VAULT/projects/$SLUG/log.md"
if [ ! -f "$LOG" ]; then
  echo "BRAIN SYNC: Update log.md and context.md before compacting."
  exit 0
fi

if tail -10 "$LOG" | grep -q "(pre-compact\|auto-close)"; then
  echo "BRAIN SYNC: Checkpoint already in log.md — update Completed and Decided fields with real session details, then update context.md."
  exit 0
fi

TODAY=$(date +%Y-%m-%d)
COMMITTED=$(git log --since="$TODAY 00:00" --name-only --format="" 2>/dev/null \
  | grep -v "^$" | sort -u | head -8) || true
MODIFIED=$(git status --short 2>/dev/null | awk '{print $2}' | head -5) || true
CHANGED=$(printf "%s\n%s" "$COMMITTED" "$MODIFIED" \
  | grep -v "^$" | sort -u | tr '\n' ' ' | sed 's/ $//' | head -c 200) || true
[ -z "$CHANGED" ] && CHANGED="—"

N=$(grep -c "^## " "$LOG" 2>/dev/null || echo "0")

printf "\n## %s · Session %d (pre-compact)\nCompleted: —\nChanged: %s\nDecided: none\nNext: —\n" \
  "$TODAY" "$((N+1))" "$CHANGED" >> "$LOG"

echo "BRAIN SYNC: Checkpoint written to log.md (Session $((N+1))) with git context. NOW update: (1) Completed — what was accomplished, (2) Decided — any decisions made, (3) context.md State and Active Work. Do this before the compact proceeds."
```

Then make it executable: `chmod +x <HOME>/.claude/brain-precompact.sh`

If `~/.claude/brain-precompact.sh` already exists: skip (do not overwrite).

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

The PostToolUse hook counts source file reads per session and reminds Claude to update vault Architecture after every 3 source files — fires at exactly the right moment, mid-session, when knowledge is fresh.

Write the following script to `<HOME>/.claude/brain-post-tool-use.sh`:

```bash
#!/bin/bash
set -euo pipefail

INPUT=$(cat)

TOOL_NAME=$(python3 -c "
import json, sys
try:
    d = json.loads(sys.argv[1])
    print(d.get('tool_name', ''))
except:
    pass
" "$INPUT" 2>/dev/null) || true

[ "$TOOL_NAME" = "Read" ] || exit 0

FILE_PATH=$(python3 -c "
import json, sys
try:
    d = json.loads(sys.argv[1])
    print(d.get('tool_input', {}).get('file_path', ''))
except:
    pass
" "$INPUT" 2>/dev/null) || true
[ -z "$FILE_PATH" ] && exit 0

EXT="${FILE_PATH##*.}"
case "$EXT" in
  ts|tsx|js|jsx|py|go|rs|rb|java|kt|swift|vue|svelte|c|cpp|cs|php|scala) ;;
  *) exit 0 ;;
esac

VAULT=$(python3 -c "
import json, os
cfg = os.path.expanduser('~/.claude/brain.config')
if os.path.exists(cfg):
    print(json.load(open(cfg))['vault'])
" 2>/dev/null) || true
[ -n "$VAULT" ] && [[ "$FILE_PATH" == "$VAULT"* ]] && exit 0

PROJECT_HASH=$(printf '%s' "$PWD" | md5 -q 2>/dev/null || printf '%s' "$PWD" | md5sum | cut -c1-8)
COUNTER_FILE="/tmp/brain-reads-${PROJECT_HASH}-$(date +%Y%m%d)"
COUNT=0
[ -f "$COUNTER_FILE" ] && COUNT=$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)
COUNT=$((COUNT + 1))
echo "$COUNT" > "$COUNTER_FILE"

if [ $((COUNT % 3)) -eq 0 ] && [ "$COUNT" -le 9 ]; then
  SLUG=$(awk -F'/' '/^vault:/{print $NF}' CLAUDE.md 2>/dev/null | tr -d '[:space:]') || true
  CONTEXT_PATH=""
  [ -n "$VAULT" ] && [ -n "$SLUG" ] && CONTEXT_PATH=" ($VAULT/projects/$SLUG/context.md)"
  echo "Brain: $COUNT source files read this session. Before continuing, update the Architecture section in context.md${CONTEXT_PATH} with what you've learned — so future sessions don't re-read these files."
fi
```

Make it executable: `chmod +x <HOME>/.claude/brain-post-tool-use.sh`

If `~/.claude/brain-post-tool-use.sh` already exists: skip (do not overwrite).

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

Write the following script to `<HOME>/.claude/brain-session-start.sh`:

```bash
#!/bin/bash
# Brain SessionStart hook — injects vault file paths into Claude's context
# before the first user prompt. Claude reads these files before responding.

VAULT=$(python3 - <<'PY'
import json, os
cfg = os.path.expanduser("~/.claude/brain.config")
if os.path.exists(cfg):
    print(json.load(open(cfg))["vault"])
PY
2>/dev/null) || true
[ -z "$VAULT" ] && exit 0

SLUG=$(awk -F'/' '/^vault:/{print $NF}' CLAUDE.md 2>/dev/null | tr -d '[:space:]') || true
[ -z "$SLUG" ] && exit 0

CONTEXT="$VAULT/projects/$SLUG/context.md"
LOG="$VAULT/projects/$SLUG/log.md"

[ -f "$CONTEXT" ] || exit 0

echo "Brain: read these files now before responding to any message:
1. $CONTEXT (full)
2. $LOG — find the last ## heading and read to end of file only"
```

Make it executable: `chmod +x <HOME>/.claude/brain-session-start.sh`

If `~/.claude/brain-session-start.sh` already exists: skip (do not overwrite).

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

The SessionEnd hook writes a git-enriched auto-close log marker when a session ends without a manual `/brain sync`. The next `/brain sync` replaces it with real content.

**Step 1 — Install the hook script to a stable path**

Write the following script to `<HOME>/.claude/brain-session-end.sh` (use the absolute home path, not `~`):

```bash
#!/bin/bash
# Brain SessionEnd hook — writes a session marker enriched with git context
# when the session ends without a manual /brain sync.
# The next /brain sync overwrites this entry with real content.

set -euo pipefail

VAULT=$(python3 - <<'PY'
import json, os
cfg = os.path.expanduser("~/.claude/brain.config")
if os.path.exists(cfg):
    print(json.load(open(cfg))["vault"])
PY
2>/dev/null) || true
[ -z "$VAULT" ] && exit 0

SLUG=$(awk -F'/' '/^vault:/{print $NF}' CLAUDE.md 2>/dev/null | tr -d '[:space:]') || true
[ -z "$SLUG" ] && exit 0

LOG="$VAULT/projects/$SLUG/log.md"
[ -f "$LOG" ] || exit 0

tail -10 "$LOG" | grep -q "(auto-close)" && exit 0

# Collect changed files: committed today + currently modified
TODAY=$(date +%Y-%m-%d)
COMMITTED=$(git log --since="$TODAY 00:00" --name-only --format="" 2>/dev/null \
  | grep -v "^$" | sort -u | head -8) || true
MODIFIED=$(git status --short 2>/dev/null | awk '{print $2}' | head -5) || true
CHANGED=$(printf "%s\n%s" "$COMMITTED" "$MODIFIED" \
  | grep -v "^$" | sort -u | tr '\n' ' ' | sed 's/ $//' | head -c 200) || true
[ -z "$CHANGED" ] && CHANGED="—"

N=$(grep -c "^## " "$LOG" 2>/dev/null || echo "0")
DATE=$TODAY

printf "\n## %s · Session %d (auto-close)\nCompleted: Session ended without sync — run /brain sync to record details\nChanged: %s\nDecided: none\nNext: —\n" \
  "$DATE" "$((N+1))" "$CHANGED" >> "$LOG"
```

Then make it executable:
```bash
chmod +x <HOME>/.claude/brain-session-end.sh
```

If `~/.claude/brain-session-end.sh` already exists: skip (do not overwrite — the user may have customised it).

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
Permissions:    Vault read/write granted in ~/.claude/settings.json

Every future session in this folder will auto-load vault context.
```

If topic project, print:
```
Permissions:    Vault read/write granted in ~/.claude/settings.json
To load this project in any session: /brain load <slug>
```

---

## /brain load <slug>

Load a topic project's context into the current session. For topic projects only — code projects auto-load via CLAUDE.md.

1. Resolve vault path (see Config resolution at top).
2. Set `VAULT_PROJECT = <VAULT_ROOT>/projects/<slug>`
3. Check if `VAULT_PROJECT/context.md` exists.
   If not: "Project '`<slug>`' not found. Available projects are listed in `<VAULT_ROOT>/_system/project-index.md`. Run `/brain init` to create a new one."
4. Read `VAULT_PROJECT/context.md` in full.
5. Read `VAULT_PROJECT/log.md` — find the last `## ` header in the file and extract from that header to the end of the file. This is the last session entry.
6. Hold both in working context for this session.
7. Print:
   ```
   Loaded: <slug>

   <contents of ## State section>
   ```

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

### Load known slugs

Read `<VAULT_ROOT>/_system/project-index.md` and extract all project slugs from the table. Store as `KNOWN_SLUGS` — used for contextual wikilinks when updating content.

### Update context.md

Read `VAULT_PROJECT/context.md`. Then rewrite these sections:

- `## State` — 2-3 sentences: what exists, what works, what is actively changing right now
- `## Active Work` — what is currently in progress
- `## Decisions` — add any decisions made this session (do not remove existing entries yet)
- `## Open Questions` — remove any questions that were resolved this session; add new ones

Line count check: count lines in the updated file.
If count > 150:
- In `## Decisions`, find all entries beyond the 5 most recent. Replace each with a one-line summary: `- [<date>] <one-sentence summary of that decision>`
- In `## Architecture`, remove any bullet that describes something no longer in the codebase

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
