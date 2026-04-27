---
name: brain
description: Use when the user types /brain, /brain init, /brain load, /brain sync, or /brain status. Manages Claude's Obsidian second brain for persistent project context across sessions.
---

# Brain — Obsidian Second Brain

## Constants

```
VAULT_ROOT     = ~/Documents/Claude Brain/claude-brain
PLUGIN_DIR     = ~/.claude/plugins/claude-brain
VAULT_SYSTEM   = ~/Documents/Claude Brain/claude-brain/_system
VAULT_PROJECTS = ~/Documents/Claude Brain/claude-brain/projects
```

---

## /brain init

Initialize a new project in the vault and wire up session automation.

### Gather project details

Ask the user in sequence:
1. "What is the project name?"
2. "Code project (tied to a folder) or topic project?" — expected answer: `code` or `topic`

Derive slug: lowercase the name, replace spaces and non-alphanumeric characters with hyphens, collapse consecutive hyphens to one.
Examples: `"My App"` → `my-app`, `"IMTF Auth Redesign"` → `imtf-auth-redesign`

### Ensure vault is initialized

Check if `~/Documents/Claude Brain/claude-brain/_system/` exists.

If it does NOT exist:
1. Create directory `~/Documents/Claude Brain/claude-brain/_system/`
2. Create directory `~/Documents/Claude Brain/claude-brain/projects/`
3. Read `~/.claude/plugins/claude-brain/templates/BRAIN.md` verbatim.
   Write it to `~/Documents/Claude Brain/claude-brain/_system/BRAIN.md`.
4. Write `~/Documents/Claude Brain/claude-brain/_system/project-index.md`:
   ```markdown
   # Project Index

   | slug | type | path | last-active |
   |------|------|------|-------------|
   ```

### Check for duplicate slug

Read `_system/project-index.md`.
If the derived slug already appears in the table as a row value, stop and say:
> "Project '`<slug>`' already exists in the vault. Use `/brain status` to see its current state, or choose a different name."

### Create project in vault

1. Create directory: `~/Documents/Claude Brain/claude-brain/projects/<slug>/`

2. Write `context.md`:
   - Read `~/.claude/plugins/claude-brain/templates/context.md`
   - Replace `{slug}` with the slug
   - Replace `{type}` with `code` or `topic`
   - Replace `{path}` with the absolute current working directory (if code project), or `—` (if topic)
   - Replace `{date}` with today's date in `YYYY-MM-DD` format
   - If code project: list the top-level files and folders in the current directory as bullets under `## Architecture`, replacing the placeholder comment
   - Write the result to `~/Documents/Claude Brain/claude-brain/projects/<slug>/context.md`

3. Write `log.md`:
   - Read `~/.claude/plugins/claude-brain/templates/log.md`
   - Replace `{date}` with today's date in `YYYY-MM-DD` format
   - Replace `{slug}` with the slug
   - Write the result to `~/Documents/Claude Brain/claude-brain/projects/<slug>/log.md`

4. Append to `_system/project-index.md`:
   ```
   | <slug> | <type> | <absolute path or —> | <YYYY-MM-DD> |
   ```

### If code project: write CLAUDE.md to project folder

1. Read `~/.claude/plugins/claude-brain/templates/CLAUDE.md`
2. Replace `{project-name}` with the display name
3. Replace `{slug}` with the slug
4. Target path: `<current working directory>/CLAUDE.md`
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

Vault context:  ~/Documents/Claude Brain/claude-brain/projects/<slug>/context.md
Vault log:      ~/Documents/Claude Brain/claude-brain/projects/<slug>/log.md
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

1. Set `VAULT_PROJECT = ~/Documents/Claude Brain/claude-brain/projects/<slug>`
2. Check if `VAULT_PROJECT/context.md` exists.
   If not: "Project '`<slug>`' not found. Available projects are listed in `_system/project-index.md`. Run `/brain init` to create a new one."
3. Read `VAULT_PROJECT/context.md` in full.
4. Read `VAULT_PROJECT/log.md` — find the last `## ` header in the file and extract from that header to the end of the file. This is the last session entry.
5. Hold both in working context for this session.
6. Print:
   ```
   Loaded: <slug>

   <contents of ## State section>
   ```

---

## /brain sync

Force a vault write for the current project. Use before a risky change, before a long break, or before switching projects.

### Identify current project

Check the current working directory for a `CLAUDE.md` file.
If found: read the `vault:` line, extract the slug as the last path segment.
If not found: ask "Which project slug should I sync? (run `/brain status` to list all)"

Set `VAULT_PROJECT = ~/Documents/Claude Brain/claude-brain/projects/<slug>`

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

In `_system/project-index.md`, find the row for this slug and update the `last-active` column to today's date.

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

### Identify current project

Same logic as `/brain sync` — check CLAUDE.md in current directory for the `vault:` line.
If no project found: read `_system/project-index.md` and print all registered projects, then ask which to inspect.

### Read and display

Read `VAULT_PROJECT/context.md`.
Count lines in `VAULT_PROJECT/log.md`, count `## ` entries.

Print:
```
Brain status: <project-name> (<slug>)
Type:         <code or topic>
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
