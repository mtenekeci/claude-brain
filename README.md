# claude-brain

Claude's Obsidian second brain — persistent, project-isolated context across sessions with autonomous read/write. Zero token overhead compared to re-discovery.

## How it works

- `/brain init` — run once in a project folder. Creates a vault entry and writes a `CLAUDE.md` that auto-loads context every session.
- Every new session: Claude reads `context.md` + the last session log (~160 lines total) automatically.
- During work: Claude updates the vault at natural checkpoints (task complete, decision made, before `/compact`).
- You never tell Claude to load or save context — it manages itself.

## Requirements

- [Claude Code](https://claude.ai/code) CLI installed
- [Obsidian](https://obsidian.md) with a vault at `~/Documents/claude-brain/`

## Install

In any Claude Code session:

```
/plugin marketplace add mtenekeci/claude-brain
/plugin install brain@mtenekeci/claude-brain
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
