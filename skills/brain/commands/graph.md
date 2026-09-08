# /brain graph <sub>

Query and maintain the project's knowledge graph (projects, sections, modules, decisions, questions, concepts, and their edges).

## Run

Use these instead of raw Grep/Glob whenever you need to find where something lives — see SKILL.md Rule 1.

- `{BRAIN} graph find <term> [--type <type>] [--limit N]` — search nodes by name/alias. Try this first.
- `{BRAIN} graph near <id-or-term> [--depth N] [--limit N]` — show a node's neighborhood (accepts a node id or a search term, resolved via `find`).
- `{BRAIN} graph path <a> <b>` — shortest path between two nodes, if any. `<a>`/`<b>` must be exact node ids (unlike `near`, `path` does not resolve a search term) — run `graph find` first to get them.
- `{BRAIN} graph top [--n N]` — the highest-degree (most-connected) nodes, a quick map of the graph's hubs.
- `{BRAIN} graph lint [--all-projects]` — concept health report: auto-applied manifest-dependency links, unlinked-mention candidates (confirm or dismiss), stale `## Used by` claims, dangling links, possible duplicate concepts. With `--all-projects` each entry is prefixed with the project it belongs to (`<project>: <concept-slug>`) — the prefix is a label, not part of the slug, so pass only the part after `: ` to `graph dismiss`. Two further notes: `dismiss` writes the *current* project's `.brain/dismissed.json`, so a candidate reported against another project has to be dismissed from that project; and the other projects are read without their repo checked out, so their graph caches are rewritten against the builtin code layer — a graphify-backed project rebuilds its cache on its next own load. Harmless, just not free.
- `{BRAIN} graph rebuild` — force a full rebuild of the graph cache (normally incremental).
- `{BRAIN} graph dismiss <slug>` — permanently dismiss a lint candidate slug (writes `.brain/dismissed.json`) so it stops being suggested. Use this instead of adding a link when a mention isn't actually a relationship worth documenting.
- `{BRAIN} graph ask <question>` — natural-language query over the graph, when a configured backend supports it (see `/brain config`'s `graph.backend`). Falls back to `find`/`near` if unavailable.

## Then

Nothing mechanical — these are read queries except `dismiss` and `rebuild`, which the CLI handles fully. When `lint` reports candidates, resolve them the same way `/brain sync` does: add a typed link, or `graph dismiss` it. When it reports **dangling links**, fix the target or remove the link — they are real broken links (a `[[…]]` inside backticks or a fenced block is a syntax example and is never reported). When resolving a candidate means creating a concept note that does not exist yet, start it from `${CLAUDE_PLUGIN_ROOT}/templates/concept.md` and write it to `VAULT_ROOT/concepts/<concept-slug>.md`.

## Report

Relay the command's output as-is. For `lint`, call out anything auto-applied (it edited a shared concept note) separately from candidates still needing a decision.
