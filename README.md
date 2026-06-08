# claude-brain

Claude's Obsidian second brain — persistent, project-isolated context across sessions with autonomous read/write. Zero token overhead compared to re-discovery.

## How it works

- `/brain init` — run once in a project folder. Creates a vault entry and writes a `CLAUDE.md` that auto-loads context every session.
- Every new session: Claude reads `context.md` + the last session log (~160 lines total) automatically.
- During work: Claude updates the vault proactively — immediately after a `git commit`, when a subagent finishes, when a decision is made, when architectural facts are discovered, or after completing a task. No prompting needed.
- Before `git push`, Claude checks the current branch against what's recorded in `## Active Work` and flags any mismatch before pushing — and re-checks `## Hard Rules` so risky actions don't slip through.
- You never tell Claude to load or save context — it manages itself.

## Requirements

- [Claude Code](https://claude.ai/code) CLI installed
- [Obsidian](https://obsidian.md) (vault can be anywhere — auto-discovered on first run)

## Install

In any Claude Code session:

```
/plugin marketplace add mtenekeci/claude-brain
/plugin install brain@claude-brain
```

The `/brain` command is now available in every session on this machine.

## Vault setup

1. Open Obsidian and create a vault anywhere you like
2. Run `/brain init` — on first run it **auto-discovers** Obsidian vaults in common locations:
   - If one vault found → asks you to confirm it
   - If multiple found → lets you pick from a list
   - If none found → asks for the path (default: `~/Documents/claude-brain`)
3. The `_system/` structure is created automatically inside your chosen vault

The vault path is saved to `~/.claude/brain.config` and reused for all future commands. To change it later:

```
/brain config set /path/to/your/vault
```

To check the current config:

```
/brain config
```

## Usage

### Initialize a code project

```
cd ~/Projects/my-app
claude
/brain init
```

Claude asks for the project name and type, then:
- Creates `~/Documents/claude-brain/projects/my-app/`
- Writes `CLAUDE.md` to `~/Projects/my-app/`
- Installs 4 hooks in `.claude/settings.json`: `SessionStart`, `PostToolUse`, `PreCompact`, `SessionEnd`
- Grants vault read/write/edit permissions in `~/.claude/settings.json`

Every future session in `~/Projects/my-app/` auto-loads vault context without permission prompts.

### Initialize a topic project (no code folder)

Run `/brain init` from any directory and choose `topic` when asked. To load context later:

```
/brain load auth-redesign
```

### Check current brain state

```
/brain status
```

### Force a vault write

```
/brain sync
```

Both `/brain sync` and `/brain status` also self-heal the project automatically: they update the `CLAUDE.md` brain section and hook scripts to the latest version if outdated, and repair any missing vault permissions.

### Remove a project from the vault

Permanently deletes vault files and removes the project from the index. Also cleans up `CLAUDE.md` and hooks from the project folder if reachable. Requires typing the slug to confirm.

```
/brain remove my-app
```

### Disconnect a project without deleting history

Keeps all vault history intact. Removes only the `CLAUDE.md` brain section and all 4 hooks from the project folder — stops auto-loading without losing notes.

```
/brain disconnect my-app
```

### Change vault location

```
/brain config set /new/path/to/vault
```

## Vault structure

```
~/Documents/claude-brain/
├── _system/
│   ├── BRAIN.md              ← vault operating instructions
│   └── project-index.md      ← registry of all projects
└── projects/
    └── <slug>/
        ├── context.md        ← state, active work, decisions (≤150 lines)
        ├── architecture.md   ← detailed architecture reference (no line cap)
        └── log.md            ← append-only session log
```

## Token impact

| Scenario | Lines loaded |
|----------|-------------|
| Session start (Tier 1) | ~160 (context.md + last log entry) |
| Before an architectural decision (Tier 2) | + `architecture.md` in full + last 5 `log.md` entries |
| Deep history trace (Tier 3) | + full `log.md` |
| Re-discovering from scratch | 2,000–10,000+ |

## License

MIT
