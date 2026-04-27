---
name: brain
description: Use when the user types /brain, /brain init, /brain load, /brain sync, /brain status, or /brain config. Manages Claude's Obsidian second brain for persistent project context across sessions.
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

**Contextual wikilinks (apply during init seeding and sync only):**
When writing or updating vault content during `/brain init` Step G or `/brain sync`, scan prose sections (State, Active Work, Decisions, Open Questions) for plain mentions of known project slugs. Known slugs come from the `project-index.md` you already read — no extra file read.

For each slug found as a standalone word (not already inside `[[...]]`, not inside code blocks or frontmatter): replace with `[[projects/<slug>/context\|<slug>]]`.

This runs only on writes, never on session-start reads — zero token cost at load time.

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
   <bullets from file structure + manifest:
   - key directories and what they contain
   - tech stack and runtime
   - notable dependencies>

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

Target: `<current working directory>/.claude/settings.json`

The hook block to install:
```json
{
  "hooks": {
    "PreCompact": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "echo 'BRAIN SYNC REQUIRED: Before compacting, write session summary to log.md and update context.md. This is mandatory.'"
          }
        ]
      }
    ]
  }
}
```

Rules:
- If `.claude/settings.json` does not exist: create `.claude/` directory if needed, write the block above as the full file.
- If `.claude/settings.json` exists but has no `hooks` key: add the `hooks` object to the existing JSON.
- If `.claude/settings.json` exists with `hooks` but no `PreCompact` key: add the `PreCompact` array.
- If `PreCompact` already exists: check if a hook with the same command string is present. If yes, skip. If no, append the hook object to the array.
- Never overwrite non-hooks keys in an existing settings.json.

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
Hook:           PreCompact hook added to .claude/settings.json

Every future session in this folder will auto-load vault context.
```

If topic project, print:
```
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

Append to `VAULT_PROJECT/log.md`:
```markdown

## <YYYY-MM-DD> · Session <N+1>
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
