Brain: vault context for "{SLUG}" follows. It is authoritative for state, decisions, history, and hard rules.
Rules:
1. Before any Grep/Glob/Read to find where something lives, use the "Brain: graph hits" injected with your prompt, or run `{BRAIN} graph find <term>` then `{BRAIN} graph near <id>`. On a miss: search the code, then add a codemap `## Modules` row or an architecture.md bullet so the next session hits.
2. Before a design decision, read the relevant architecture.md section (`{BRAIN} graph near <node>` names it) — not the whole file.
3. Write meaning, not mechanics: `## State` + `## Active Work` after commits, decisions when made, module responsibilities when learned. Dates, Changed lines, the codemap tree, Used-by edges, and index rows are maintained by the plugin.
4. Link with typed wikilinks when you write: `uses:: [[concepts/x]]`, `decided-by:: [[...]]`. Promote to a concept note only if you would link it from more than one place; run `{BRAIN} graph find` first to avoid duplicates.
5. Subagents are briefed automatically; fold their "Vault notes:" into the vault when they return.
6. The plugin blocks you from ending a turn that made commits or several source edits without a vault write. Write it, then finish.
Hard Rules in context.md apply to every action.
