# Claude Brain: Obsidian as Claude's Second Brain

**Date:** 2026-04-27  
**Status:** Approved  
**License:** MIT  

---

## Problem

Claude loses all project context between sessions. Every new session forces re-discovery — re-reading files, re-scanning architecture, re-establishing what's in progress. This costs tokens, time, and quality. Claude makes worse decisions when it can't remember what was decided two sessions ago.

Standard solutions (CLAUDE.md, memory files) are either global (not project-isolated) or manual (you maintain them). Neither is sustainable across multiple active projects.

---

## Goals

- Claude is fully context-aware from the first message of every session
- Claude reads and writes to the knowledge base autonomously — no user prompting required
- Multiple projects coexist in the vault without polluting each other
- Token usage is reduced, not increased, compared to re-discovery
- The vault is human-readable and editable in Obsidian at any time
- The system is installable on any machine via `git clone`
- Open source (MIT) for community benefit

---

## Non-Goals

- A global "dump everything" knowledge base — context is always project-scoped
- Vector search or embedding-based retrieval — plain markdown is sufficient
- An MCP server — direct filesystem access is simpler and equally effective
- Replacing CLAUDE.md entirely — this system generates and manages CLAUDE.md per project

---

## Chosen Approach: Hook-Driven Automation

Claude reads from the vault automatically via a generated `CLAUDE.md` in each project folder. Claude writes back at natural checkpoints during the session, instructed by the same `CLAUDE.md`. A `PreCompact` hook ensures vault state is saved before context compaction. A single `/brain` slash command handles initialization.

---

## Vault Structure

```
~/Documents/Claude Brain/claude-brain/
│
├── _system/
│   ├── BRAIN.md                    ← master operating instructions for Claude
│   └── project-index.md           ← registry: slug, type, path, last active date
│
├── projects/
│   └── <project-slug>/
│       ├── context.md             ← primary knowledge file (≤150 lines enforced)
│       ├── log.md                 ← append-only session log
│       └── map.canvas             ← Obsidian Canvas visual map (optional, never read by Claude)
│
└── .obsidian/
```

**Design rationale:**

- `_system/` uses underscore prefix to sort to top and signal system-managed content
- Each project is fully isolated — Claude loads only its own project folder
- `map.canvas` is human-facing only and out of scope for v1 — Obsidian renders backlinks from context.md as a graph automatically, which is sufficient
- The vault remains fully browsable in Obsidian with graph view, backlinks, and canvas

---

## Project File Anatomy

### `context.md` — the only file read in full at session start

```markdown
---
project: <slug>
type: code | topic
path: <absolute path to code folder, if code project>
updated: <date>
---

## State
What exists, what works, what is actively changing. 2-3 sentences maximum.

## Architecture
- Key files and their purpose
- Tech stack, patterns, conventions worth remembering

## Active Work
What is in progress right now.

## Decisions
Last 3-5 decisions with one-line rationale each.
Older decisions are compressed to a single summary line, never deleted.

## Open Questions
Current blockers, unknowns, things to investigate next.

## Constraints
Things Claude must never change, assume, or override.
```

**Enforcement rules:**
- Hard cap: 150 lines
- When approaching cap, Claude compresses old decisions (5+ entries → one summary line each)
- Resolved open questions are removed immediately
- Architecture section is bulleted, never prose

### `log.md` — append-only, only the last entry loaded at session start

```markdown
## YYYY-MM-DD · Session N
Completed: <what was finished>
Changed: <files or systems touched>
Decided: <any decisions made, with one-line reason>
Next: <what comes next>
```

Each entry is 5-8 lines. Loading only the last entry costs ~10 lines of tokens. Full history stays on disk for Tier 3 deep reads.

---

## Tiered Context Loading

Claude loads context in tiers based on what the task demands. It never blindly loads everything.

| Tier | What loads | When | Lines |
|------|-----------|------|-------|
| 1 — Always | `context.md` + last `log.md` entry | Every session start | ~160 |
| 2 — Decisions | Last 5 `log.md` entries | Before architectural decisions or pattern changes | +40 |
| 3 — Deep | Full `log.md` | Tracing history of a specific problem | +full |

This is defined in the generated `CLAUDE.md` so Claude knows the rules without being told each session.

**Token comparison:**

- Re-discovering codebase from scratch: 2,000–10,000+ lines
- Tier 1 session start: ~160 lines
- Tier 2 decision session: ~200 lines
- Tier 3 deep investigation: ~300–500 lines

---

## Session Lifecycle

### Session start (automatic)

```
Open project folder → Claude Code starts
    ↓
Claude Code auto-reads CLAUDE.md in project folder
    ↓
CLAUDE.md instructs: read context.md + last log entry
    ↓
Claude reads ~160 lines → fully context-aware
    ↓
Session begins
```

No user action required after `/brain init` ran once.

### During session (Claude-driven)

Claude writes back at three natural checkpoints, defined in the project `CLAUDE.md`:

| Trigger | Action |
|---------|--------|
| Significant task completed | Update `context.md` state section + append `log.md` entry |
| Architectural decision made | Update `context.md` decisions section |
| Before `/compact` | Write full session summary to `log.md`, compress `context.md` if >150 lines |

### Session close

There is no session-end event in Claude Code — the user simply closes the window. This is fine by design: Claude writes at task completion checkpoints during the session, so the vault is already up to date. The `PreCompact` hook provides the safety net for long sessions.

---

## The `/brain` Skill

### `/brain init`

Run once in a project folder (code projects) or from anywhere (topic projects).

**Flow:**
1. Claude prompts: project name, type (code/topic)
2. Derives slug from name (lowercase, hyphenated)
3. Creates `projects/<slug>/` in the vault
4. Writes `context.md` from template, seeded with current folder structure if code project
5. Writes `log.md` with initialization entry
6. Registers project in `_system/project-index.md`
7. Writes `CLAUDE.md` into current project folder (code projects only)
8. Writes `PreCompact` hook to `.claude/settings.json` in project folder

**After completion:** every future session in the folder is fully automatic.

### `/brain load <slug>`

For topic projects only (no code folder, no auto-loading CLAUDE.md). Run from any directory to load a topic project's context into the current session. Claude reads `context.md` + last `log.md` entry for the named project and holds it in working context for the session.

Example: `/brain load research-imtf-auth`

### `/brain sync`

Force a vault write mid-session. Use before a risky change, before a long break, or before switching projects. Claude writes current state immediately.

### `/brain status`

Print a summary of what is currently loaded from the vault this session. Used to verify the system is working or debug stale context.

---

## Generated `CLAUDE.md` (per project)

This file is written to the project's code folder by `/brain init`. It is the engine of the automation.

```markdown
# Brain: <project-name>

vault: ~/Documents/Claude Brain/claude-brain/projects/<slug>

## Session start protocol
1. Read `context.md` in full
2. Read last entry of `log.md` only
3. If about to make an architectural decision → read last 5 log entries (Tier 2)
4. Read full `log.md` only when tracing history of a specific problem (Tier 3)

## Write protocol
- After completing a significant task: update context.md state + append log.md entry
- After making an architectural decision: update context.md decisions section
- Before /compact: write session summary to log.md, compress context.md if >150 lines

## context.md rules
- Hard cap: 150 lines. Compress, never delete.
- Decisions beyond 5 entries: compress each to one line
- Resolved open questions: remove immediately
- Architecture section: bullets only, no prose
```

---

## Hook Configuration

One hook. Written to the project's `.claude/settings.json` by `/brain init`.

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

**Why only this hook:**

- `Stop` hook rejected — fires after every response, adds per-turn overhead
- `UserPromptSubmit` hook rejected — CLAUDE.md handles session-start reads automatically
- `PostToolUse` hook rejected — too granular, Claude's write protocol handles timing

---

## Repo Structure

```
claude-brain/                        ← GitHub repo root (MIT license)
├── skills/
│   └── brain.md                    ← /brain skill definition
├── templates/
│   ├── CLAUDE.md                   ← template written to each project folder
│   ├── context.md                  ← template for new project context
│   ├── log.md                      ← template for session log
│   └── BRAIN.md                    ← master vault operating instructions
├── hooks/
│   └── precompact.sh               ← PreCompact hook script
├── LICENSE                         ← MIT
└── README.md                       ← install guide + vault setup walkthrough
```

**Installation on any machine:**

```bash
git clone https://github.com/<user>/claude-brain ~/.claude/plugins/claude-brain
```

One line in Claude Code settings to register the plugin — then `/brain` is available everywhere.

---

## Open Source

Licensed MIT. The vault format (plain markdown) is not locked to this tool — users own their data unconditionally. Contributors can improve templates, add language-specific context seeds, or extend the skill without any license friction.
