# /brain graph <sub>

Query and maintain the project's knowledge graph (projects, sections, modules, decisions, questions, concepts, and their edges).

## Run

Use these instead of raw Grep/Glob whenever you need to find where something lives — see SKILL.md Rule 1.

- `{BRAIN} graph find <term> [--type <type>] [--limit N]` — search nodes by name/alias. Try this first.
- `{BRAIN} graph near <id-or-term> [--depth N] [--limit N]` — show a node's neighborhood (accepts a node id or a search term, resolved via `find`).
- `{BRAIN} graph path <a> <b>` — shortest path between two nodes, if any.
- `{BRAIN} graph top [--n N]` — the highest-degree (most-connected) nodes, a quick map of the graph's hubs.
- `{BRAIN} graph lint [--all-projects]` — concept health report: auto-applied manifest-dependency links, unlinked-mention candidates (confirm or dismiss), stale `## Used by` claims, dangling links, possible duplicate concepts.
- `{BRAIN} graph rebuild` — force a full rebuild of the graph cache (normally incremental).
- `{BRAIN} graph dismiss <slug>` — permanently dismiss a lint candidate slug (writes `.brain/dismissed.json`) so it stops being suggested. Use this instead of adding a link when a mention isn't actually a relationship worth documenting.
- `{BRAIN} graph ask <question>` — natural-language query over the graph, when a configured backend supports it (see `/brain config`'s `graph.backend`). Falls back to `find`/`near` if unavailable.

## Then

Nothing mechanical — these are read queries except `dismiss` and `rebuild`, which the CLI handles fully. When `lint` reports candidates, resolve them the same way `/brain sync` does: add a typed link, or `graph dismiss` it.

## Report

Relay the command's output as-is. For `lint`, call out anything auto-applied (it edited a shared concept note) separately from candidates still needing a decision.
