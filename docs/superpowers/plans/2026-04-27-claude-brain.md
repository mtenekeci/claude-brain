# Claude Brain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code plugin that uses an Obsidian vault as Claude's persistent second brain — auto-loading project context at session start and autonomously writing back at natural checkpoints.

**Architecture:** A `skills/brain.md` skill file handles all four `/brain` commands. Four template files in `templates/` are copied and populated during `/brain init`. A single `PreCompact` hook script in `hooks/` protects against context loss before compaction. Claude's own CLAUDE.md in each project folder drives the read/write automation — no daemon, no server.

**Tech Stack:** Bash (hook script), Markdown (skill + templates), JSON (settings.json merge), Claude Code plugin system

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `LICENSE` | Create | MIT license |
| `hooks/precompact.sh` | Create | Shell script echoing the PreCompact injection message |
| `templates/BRAIN.md` | Create | Master vault operating instructions, copied to vault `_system/` on first init |
| `templates/context.md` | Create | Project context template with `{slug}`, `{type}`, `{path}`, `{date}` placeholders |
| `templates/log.md` | Create | Session log template with `{date}`, `{slug}` placeholders |
| `templates/CLAUDE.md` | Create | Per-project automation instructions, copied to each code project folder |
| `skills/brain.md` | Create | The `/brain` skill — all four commands with complete step-by-step instructions |
| `README.md` | Create | Install guide, vault setup, usage reference |

---

## Task 1: Repo skeleton and MIT LICENSE

**Files:**
- Create: `LICENSE`
- Create: `hooks/` (directory)
- Create: `templates/` (directory)
- Create: `skills/` (directory)

- [ ] **Step 1: Verify working directory**

```bash
pwd
ls /Users/mehmet.tenekeci/Documents/Projects/claude-brain/
```

Expected: shows `docs/` folder, nothing else yet.

- [ ] **Step 2: Create directory structure**

```bash
mkdir -p /Users/mehmet.tenekeci/Documents/Projects/claude-brain/hooks
mkdir -p /Users/mehmet.tenekeci/Documents/Projects/claude-brain/templates
mkdir -p /Users/mehmet.tenekeci/Documents/Projects/claude-brain/skills
```

- [ ] **Step 3: Write LICENSE**

Write to `/Users/mehmet.tenekeci/Documents/Projects/claude-brain/LICENSE`:

```
MIT License

Copyright (c) 2026 Mehmet Tenekeci

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 4: Initialize git repo**

```bash
cd /Users/mehmet.tenekeci/Documents/Projects/claude-brain && git init
```

Expected: `Initialized empty Git repository in .../claude-brain/.git/`

- [ ] **Step 5: Commit**

```bash
cd /Users/mehmet.tenekeci/Documents/Projects/claude-brain && git add LICENSE && git commit -m "chore: initialize repo with MIT license"
```

---

## Task 2: PreCompact hook script (test-first)

**Files:**
- Create: `hooks/precompact.sh`

- [ ] **Step 1: Write the test script**

Write to `/Users/mehmet.tenekeci/Documents/Projects/claude-brain/hooks/test_precompact.sh`:

```bash
#!/bin/bash
OUTPUT=$(bash "$(dirname "$0")/precompact.sh")
EXPECTED="BRAIN SYNC REQUIRED: Before compacting, write session summary to log.md and update context.md. This is mandatory."

if [ "$OUTPUT" = "$EXPECTED" ]; then
  echo "PASS: precompact hook outputs correct message"
  exit 0
else
  echo "FAIL"
  echo "  Expected: $EXPECTED"
  echo "  Got:      $OUTPUT"
  exit 1
fi
```

- [ ] **Step 2: Run the test — verify it fails (precompact.sh does not exist yet)**

```bash
bash /Users/mehmet.tenekeci/Documents/Projects/claude-brain/hooks/test_precompact.sh
```

Expected: exits with error — `precompact.sh: No such file or directory`

- [ ] **Step 3: Write hooks/precompact.sh**

Write to `/Users/mehmet.tenekeci/Documents/Projects/claude-brain/hooks/precompact.sh`:

```bash
#!/bin/bash
echo "BRAIN SYNC REQUIRED: Before compacting, write session summary to log.md and update context.md. This is mandatory."
```

- [ ] **Step 4: Make both scripts executable**

```bash
chmod +x /Users/mehmet.tenekeci/Documents/Projects/claude-brain/hooks/precompact.sh
chmod +x /Users/mehmet.tenekeci/Documents/Projects/claude-brain/hooks/test_precompact.sh
```

- [ ] **Step 5: Run the test — verify it passes**

```bash
bash /Users/mehmet.tenekeci/Documents/Projects/claude-brain/hooks/test_precompact.sh
```

Expected:
```
PASS: precompact hook outputs correct message
```

- [ ] **Step 6: Commit**

```bash
cd /Users/mehmet.tenekeci/Documents/Projects/claude-brain && git add hooks/ && git commit -m "feat: add PreCompact hook script"
```

---

## Task 3: templates/BRAIN.md

**Files:**
- Create: `templates/BRAIN.md`

- [ ] **Step 1: Write templates/BRAIN.md**

Write to `/Users/mehmet.tenekeci/Documents/Projects/claude-brain/templates/BRAIN.md`:

```markdown
# Claude Brain — Vault Operating Instructions

This vault is managed by Claude using the claude-brain plugin.

## Vault structure

- `_system/` — system files managed by the plugin, do not delete
- `projects/<slug>/` — one isolated folder per project

## Per-project files

- `context.md` — compiled living knowledge, hard cap 150 lines
- `log.md` — append-only session log, only last entry loaded at session start

## Rules for Claude

- Never load a project folder other than the one relevant to the current session
- `context.md` hard cap is 150 lines — compress older content, never delete
- `log.md` is append-only — never modify past entries
- After writing to a project, always update `last-active` in `_system/project-index.md`

## Tiered loading

- Tier 1 (always): `context.md` in full + last `log.md` entry (~160 lines)
- Tier 2 (before architectural decisions): last 5 `log.md` entries (+40 lines)
- Tier 3 (tracing a specific historical problem): full `log.md`

Per-project automation lives in the `CLAUDE.md` written to each project's code folder.
```

- [ ] **Step 2: Verify no placeholder text remains**

```bash
grep -n '{' /Users/mehmet.tenekeci/Documents/Projects/claude-brain/templates/BRAIN.md
```

Expected: no output (no curly-brace placeholders in this file).

- [ ] **Step 3: Commit**

```bash
cd /Users/mehmet.tenekeci/Documents/Projects/claude-brain && git add templates/BRAIN.md && git commit -m "feat: add vault BRAIN.md template"
```

---

## Task 4: templates/context.md

**Files:**
- Create: `templates/context.md`

- [ ] **Step 1: Write templates/context.md**

Write to `/Users/mehmet.tenekeci/Documents/Projects/claude-brain/templates/context.md`:

```markdown
---
project: {slug}
type: {type}
path: {path}
updated: {date}
---

## State
Project initialized. No sessions recorded yet.

## Architecture
- (populated from project folder scan on init — edit as needed)

## Active Work
Nothing in progress yet.

## Decisions
None yet.

## Open Questions
None yet.

## Constraints
(add anything Claude must never change, assume, or override)
```

- [ ] **Step 2: Verify exactly four placeholders exist**

```bash
grep -o '{[^}]*}' /Users/mehmet.tenekeci/Documents/Projects/claude-brain/templates/context.md
```

Expected output (one per line):
```
{slug}
{type}
{path}
{date}
```

- [ ] **Step 3: Commit**

```bash
cd /Users/mehmet.tenekeci/Documents/Projects/claude-brain && git add templates/context.md && git commit -m "feat: add context.md template"
```

---

## Task 5: templates/log.md

**Files:**
- Create: `templates/log.md`

- [ ] **Step 1: Write templates/log.md**

Write to `/Users/mehmet.tenekeci/Documents/Projects/claude-brain/templates/log.md`:

```markdown
## {date} · Session 1
Completed: Project initialized in vault
Changed: —
Decided: Created claude-brain entry for {slug}
Next: Begin first working session
```

- [ ] **Step 2: Verify exactly two placeholders exist**

```bash
grep -o '{[^}]*}' /Users/mehmet.tenekeci/Documents/Projects/claude-brain/templates/log.md
```

Expected:
```
{date}
{slug}
```

- [ ] **Step 3: Commit**

```bash
cd /Users/mehmet.tenekeci/Documents/Projects/claude-brain && git add templates/log.md && git commit -m "feat: add log.md template"
```

---

## Task 6: templates/CLAUDE.md

**Files:**
- Create: `templates/CLAUDE.md`

- [ ] **Step 1: Write templates/CLAUDE.md**

Write to `/Users/mehmet.tenekeci/Documents/Projects/claude-brain/templates/CLAUDE.md`:

```markdown
# Brain: {project-name}

vault: ~/Documents/Claude Brain/claude-brain/projects/{slug}

## Session start protocol
1. Read `context.md` in full
2. Read last entry of `log.md` only
3. If about to make an architectural decision → read last 5 `log.md` entries (Tier 2)
4. Read full `log.md` only when tracing history of a specific problem (Tier 3)

## Write protocol
- After completing a significant task: update `context.md` state + append `log.md` entry
- After making an architectural decision: update `context.md` decisions section
- Before `/compact`: write session summary to `log.md`, compress `context.md` if >150 lines

## context.md rules
- Hard cap: 150 lines. Compress, never delete.
- Decisions beyond 5 entries: compress each to one line
- Resolved open questions: remove immediately
- Architecture section: bullets only, no prose
```

- [ ] **Step 2: Verify exactly two placeholders exist**

```bash
grep -o '{[^}]*}' /Users/mehmet.tenekeci/Documents/Projects/claude-brain/templates/CLAUDE.md
```

Expected:
```
{project-name}
{slug}
```

- [ ] **Step 3: Commit**

```bash
cd /Users/mehmet.tenekeci/Documents/Projects/claude-brain && git add templates/CLAUDE.md && git commit -m "feat: add CLAUDE.md template"
```

---

## Task 7: skills/brain.md

**Files:**
- Create: `skills/brain.md`

This is the core skill. It tells Claude exactly how to execute all four commands. Read it fully before verifying.

- [ ] **Step 1: Write skills/brain.md**

Write to `/Users/mehmet.tenekeci/Documents/Projects/claude-brain/skills/brain.md`:

````markdown
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
````

- [ ] **Step 2: Verify all four commands are present**

```bash
grep -c "^## /brain" /Users/mehmet.tenekeci/Documents/Projects/claude-brain/skills/brain.md
```

Expected: `4`

- [ ] **Step 3: Verify no unfilled placeholder text**

```bash
grep -n "TBD\|TODO\|fill in\|implement later\|similar to" /Users/mehmet.tenekeci/Documents/Projects/claude-brain/skills/brain.md
```

Expected: no output.

- [ ] **Step 4: Verify VAULT_ROOT constant is present**

```bash
grep "VAULT_ROOT" /Users/mehmet.tenekeci/Documents/Projects/claude-brain/skills/brain.md
```

Expected: line showing `VAULT_ROOT = ~/Documents/Claude Brain/claude-brain`

- [ ] **Step 5: Commit**

```bash
cd /Users/mehmet.tenekeci/Documents/Projects/claude-brain && git add skills/brain.md && git commit -m "feat: add /brain skill with init, load, sync, status commands"
```

---

## Task 8: README.md

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README.md**

Write to `/Users/mehmet.tenekeci/Documents/Projects/claude-brain/README.md`:

```markdown
# claude-brain

Claude's Obsidian second brain — persistent, project-isolated context across sessions with autonomous read/write. Zero token overhead compared to re-discovery.

## How it works

- `/brain init` — run once in a project folder. Creates a vault entry and writes a `CLAUDE.md` that auto-loads context every session.
- Every new session: Claude reads `context.md` + the last session log (~160 lines total) automatically.
- During work: Claude updates the vault at natural checkpoints (task complete, decision made, before `/compact`).
- You never tell Claude to load or save context — it manages itself.

## Requirements

- [Claude Code](https://claude.ai/code) CLI installed
- [Obsidian](https://obsidian.md) with a vault at `~/Documents/Claude Brain/claude-brain/`

## Install

```bash
git clone https://github.com/<your-username>/claude-brain ~/.claude/plugins/claude-brain
```

Then register the plugin in `~/.claude/settings.json`:

```json
{
  "plugins": ["~/.claude/plugins/claude-brain"]
}
```

Restart Claude Code. The `/brain` command is now available in every session.

## Vault setup

The vault directory must exist before first use:

1. Open Obsidian
2. Create a new vault named `claude-brain` at `~/Documents/Claude Brain/`
3. Run `/brain init` in any project folder — the `_system/` structure is created automatically on first run

## Usage

### Initialize a code project

```
cd ~/Projects/my-app
claude
/brain init
```

Claude asks for the project name and type, then:
- Creates `~/Documents/Claude Brain/claude-brain/projects/my-app/`
- Writes `CLAUDE.md` to `~/Projects/my-app/`
- Installs the `PreCompact` hook in `.claude/settings.json`

Every future session in `~/Projects/my-app/` auto-loads vault context.

### Initialize a topic project (no code folder)

Run `/brain init` from any directory and choose `topic` when asked. To load context later:

```
/brain load imtf-auth-redesign
```

### Check current brain state

```
/brain status
```

### Force a vault write

```
/brain sync
```

## Vault structure

```
~/Documents/Claude Brain/claude-brain/
├── _system/
│   ├── BRAIN.md              ← vault operating instructions
│   └── project-index.md      ← registry of all projects
└── projects/
    └── <slug>/
        ├── context.md        ← compiled project knowledge (≤150 lines)
        └── log.md            ← append-only session log
```

## Token impact

| Scenario | Lines loaded |
|----------|-------------|
| Session start (Tier 1) | ~160 |
| Before architectural decision (Tier 2) | ~200 |
| Deep history trace (Tier 3) | ~300–500 |
| Re-discovering from scratch | 2,000–10,000+ |

## License

MIT
```

- [ ] **Step 2: Verify required sections exist**

```bash
grep -c "^## " /Users/mehmet.tenekeci/Documents/Projects/claude-brain/README.md
```

Expected: `7` or more (How it works, Requirements, Install, Vault setup, Usage, Vault structure, Token impact, License).

- [ ] **Step 3: Commit**

```bash
cd /Users/mehmet.tenekeci/Documents/Projects/claude-brain && git add README.md && git commit -m "docs: add README with install guide and usage reference"
```

---

## Task 9: Initialize vault _system/ folder

**Files:**
- Create: `~/Documents/Claude Brain/claude-brain/_system/BRAIN.md`
- Create: `~/Documents/Claude Brain/claude-brain/_system/project-index.md`

The vault already exists with `.obsidian/` config. This task seeds the `_system/` folder so the vault is ready before any `/brain init` runs.

- [ ] **Step 1: Create _system/ directory**

```bash
mkdir -p ~/Documents/Claude\ Brain/claude-brain/_system
mkdir -p ~/Documents/Claude\ Brain/claude-brain/projects
```

- [ ] **Step 2: Copy BRAIN.md template into vault**

```bash
cp /Users/mehmet.tenekeci/Documents/Projects/claude-brain/templates/BRAIN.md \
   ~/Documents/Claude\ Brain/claude-brain/_system/BRAIN.md
```

- [ ] **Step 3: Verify the copy**

```bash
cat ~/Documents/Claude\ Brain/claude-brain/_system/BRAIN.md
```

Expected: shows the BRAIN.md content with no `{placeholders}`.

- [ ] **Step 4: Write project-index.md**

Write to `~/Documents/Claude Brain/claude-brain/_system/project-index.md`:

```markdown
# Project Index

| slug | type | path | last-active |
|------|------|------|-------------|
```

- [ ] **Step 5: Verify vault structure**

```bash
find ~/Documents/Claude\ Brain/claude-brain/_system/ -type f
find ~/Documents/Claude\ Brain/claude-brain/projects/ -type f 2>/dev/null || echo "(empty — correct)"
```

Expected:
```
.../claude-brain/_system/BRAIN.md
.../claude-brain/_system/project-index.md
(empty — correct)
```

- [ ] **Step 6: Commit vault init note**

Add a note to the repo that the vault must be set up — this is already covered by README.md. No additional file needed.

```bash
cd /Users/mehmet.tenekeci/Documents/Projects/claude-brain && git add -A && git status
```

Expected: nothing new to commit (vault files live outside the repo).

---

## Task 10: End-to-end smoke test

Verify `/brain init` works correctly for a code project by running it manually in a test directory.

- [ ] **Step 1: Create a temporary test project directory**

```bash
mkdir -p /tmp/brain-test-project
```

- [ ] **Step 2: Open Claude Code in the test directory and run /brain init**

In Claude Code (terminal), navigate to `/tmp/brain-test-project` and run:
```
/brain init
```

When prompted:
- Project name: `brain-smoke-test`
- Type: `code`

- [ ] **Step 3: Verify vault entry was created**

```bash
ls ~/Documents/Claude\ Brain/claude-brain/projects/brain-smoke-test/
```

Expected:
```
context.md
log.md
```

- [ ] **Step 4: Verify context.md has no unfilled placeholders**

```bash
grep '{' ~/Documents/Claude\ Brain/claude-brain/projects/brain-smoke-test/context.md
```

Expected: no output.

- [ ] **Step 5: Verify context.md frontmatter is correct**

```bash
head -6 ~/Documents/Claude\ Brain/claude-brain/projects/brain-smoke-test/context.md
```

Expected (approximate):
```
---
project: brain-smoke-test
type: code
path: /tmp/brain-test-project
updated: 2026-04-27
---
```

- [ ] **Step 6: Verify CLAUDE.md was written to test project folder**

```bash
cat /tmp/brain-test-project/CLAUDE.md
```

Expected: contains `vault: ~/Documents/Claude Brain/claude-brain/projects/brain-smoke-test` and all four protocol sections.

- [ ] **Step 7: Verify PreCompact hook was installed**

```bash
cat /tmp/brain-test-project/.claude/settings.json
```

Expected: JSON containing `PreCompact` hook with the `BRAIN SYNC REQUIRED` message.

- [ ] **Step 8: Verify project-index.md was updated**

```bash
cat ~/Documents/Claude\ Brain/claude-brain/_system/project-index.md
```

Expected: contains a row for `brain-smoke-test`.

- [ ] **Step 9: Clean up test directory**

```bash
rm -rf /tmp/brain-test-project
```

Remove the test entry from vault (optional — can be left as first real entry):
```bash
rm -rf ~/Documents/Claude\ Brain/claude-brain/projects/brain-smoke-test
```

And remove from project-index.md: edit the file to remove the `brain-smoke-test` row.

---

## Task 11: Final commit and tag

- [ ] **Step 1: Verify all expected files exist**

```bash
find /Users/mehmet.tenekeci/Documents/Projects/claude-brain -not -path '*/.git/*' -type f | sort
```

Expected files:
```
.../LICENSE
.../README.md
.../docs/superpowers/plans/2026-04-27-claude-brain.md
.../docs/superpowers/specs/2026-04-27-obsidian-second-brain-design.md
.../hooks/precompact.sh
.../hooks/test_precompact.sh
.../skills/brain.md
.../templates/BRAIN.md
.../templates/CLAUDE.md
.../templates/context.md
.../templates/log.md
```

- [ ] **Step 2: Run hook test one final time**

```bash
bash /Users/mehmet.tenekeci/Documents/Projects/claude-brain/hooks/test_precompact.sh
```

Expected: `PASS: precompact hook outputs correct message`

- [ ] **Step 3: Final commit**

```bash
cd /Users/mehmet.tenekeci/Documents/Projects/claude-brain && git add -A && git commit -m "feat: complete claude-brain v1 — skill, templates, hook, README"
```

- [ ] **Step 4: Tag v1.0.0**

```bash
cd /Users/mehmet.tenekeci/Documents/Projects/claude-brain && git tag v1.0.0
```

---

## Self-Review

### Spec coverage check

| Spec requirement | Covered by task |
|---|---|
| Vault `_system/` + `projects/<slug>/` structure | Task 9 (vault init) + Task 7 (`/brain init`) |
| `context.md` template with 6 sections + frontmatter | Task 4 |
| `log.md` template, append-only, last entry only | Task 5 |
| Tiered context loading in generated CLAUDE.md | Task 6 |
| Session start auto-read via CLAUDE.md | Task 6 + Task 7 |
| Write-back at 3 checkpoints | Task 6 (CLAUDE.md template) + Task 7 (skill write protocol) |
| `/brain init` — full 8-step flow | Task 7 |
| `/brain load <slug>` — topic projects | Task 7 |
| `/brain sync` — force write | Task 7 |
| `/brain status` — state display | Task 7 |
| PreCompact hook, one hook only | Task 2 + Task 7 |
| Generated CLAUDE.md written to project folder | Task 6 + Task 7 |
| `_system/BRAIN.md` master instructions | Task 3 + Task 9 |
| `_system/project-index.md` registry | Task 9 + Task 7 |
| Repo structure (skills/, templates/, hooks/) | Task 1 |
| MIT LICENSE | Task 1 |
| README install guide | Task 8 |
| Duplicate slug protection | Task 7 |
| CLAUDE.md merge (existing file) | Task 7 |
| settings.json merge (existing file) | Task 7 |
| 150-line cap enforcement | Task 7 (sync) + Task 6 (CLAUDE.md rules) |

All spec requirements covered. No gaps found.
