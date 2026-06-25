# claude-brain

`claude-brain` is a Claude Code plugin that gives Claude a persistent Obsidian-backed second brain for project context, decisions, architecture notes, and session logs.

It is designed for long-running projects where each new Claude session should start with the same compact, authoritative context instead of rediscovering the repository from scratch.

## What it does

- Adds a `/brain` command to Claude Code.
- Creates one vault entry per project under an Obsidian vault.
- Auto-loads `context.md` and the latest session log at the start of each session.
- Prompts Claude to update the vault when decisions, architecture facts, commits, compactions, or session ends happen.
- Keeps detailed architecture notes in `architecture.md` and append-only history in `log.md`.
- Maintains optional atomic concept notes in `concepts/` so reusable ideas become graph nodes in Obsidian.
- Installs project hooks that self-heal when `/brain sync` or `/brain status` runs.

## Requirements

- [Claude Code](https://claude.ai/code)
- [Obsidian](https://obsidian.md), or any folder you want to use as a markdown vault
- macOS, Linux, or another shell environment with `bash`, `python3`, and `git`

## Install

Add the marketplace and install the plugin from inside Claude Code:

```text
/plugin marketplace add mtenekeci/claude-brain
/plugin install brain@claude-brain
```

After installation, `/brain` is available in Claude Code sessions on the machine.

## Quick start

From a code project:

```bash
cd ~/Projects/my-app
claude
/brain init
```

`/brain init` asks for the project name and type, then:

- Creates a project folder in your configured vault.
- Writes the project brain section into the project's `CLAUDE.md`.
- Installs Claude Code hooks in `.claude/settings.json`.
- Grants Claude Code the vault permissions needed for reads and writes.

Every future Claude Code session in that project loads the vault context automatically.

## Commands

| Command | Purpose |
|---|---|
| `/brain init` | Connect the current project or topic to the vault. |
| `/brain load <slug>` | Load an existing topic or project context manually. |
| `/brain sync` | Force a vault write and refresh installed brain assets. |
| `/brain status` | Show configuration, hook health, vault paths, and sync status. |
| `/brain config` | Show the configured vault path. |
| `/brain config set <path>` | Change the vault path. |
| `/brain remove <slug>` | Delete a project from the vault after confirmation. |
| `/brain disconnect <slug>` | Remove hooks and project integration without deleting vault history. |

## Vault layout

```text
<vault>/
├── _system/
│   ├── BRAIN.md
│   └── project-index.md
├── concepts/
│   └── <concept>.md
└── projects/
    └── <slug>/
        ├── context.md
        ├── architecture.md
        └── log.md
```

`context.md` is intentionally compact and session-start friendly. `architecture.md` is the deeper reference. `log.md` is append-only history.

## How context loading works

`claude-brain` uses tiered context loading:

| Tier | When | What Claude reads |
|---|---|---|
| Tier 1 | Session start | `context.md` plus the latest `log.md` entry |
| Tier 2 | Architecture or design decisions | Full `architecture.md` plus recent log entries |
| Tier 3 | Historical questions | Full `log.md` |

The goal is to keep routine session startup small while still preserving deeper history when it matters.

## Repository layout

| Path | Purpose |
|---|---|
| `.claude-plugin/plugin.json` | Claude Code plugin manifest. |
| `.claude-plugin/marketplace.json` | Marketplace listing metadata. |
| `skills/brain/SKILL.md` | Full `/brain` command behavior. |
| `hooks/*.sh` | Claude Code hooks installed into connected projects. |
| `templates/*.md` | Files written into vaults and projects during setup. |
| `.githooks/pre-commit` | Local branch-protection hook for this repository. |

## Public repository hygiene

This repository should contain plugin source, templates, hooks, and public documentation only.

Do not commit generated per-project runtime state such as `.claude/`, `.codex/`, root `CLAUDE.md`, root `AGENTS.md`, IDE metadata, local vault files, or secrets. The repository `.gitignore` excludes these paths.

The plugin intentionally writes local machine paths into connected projects because Claude Code hooks need absolute command paths. Those generated files are useful locally but should not be tracked in this public source repository.

## Development notes

- `skills/brain/SKILL.md` is the authoritative behavior spec for all `/brain` subcommands.
- The version is stored in `.claude-plugin/plugin.json`.
- Public-facing metadata should use `mehmet@tenekeci.ch`.
- Run `/brain sync` in a connected project after upgrading the plugin to refresh copied hook scripts and templates.

## License

MIT. See [LICENSE](LICENSE).
