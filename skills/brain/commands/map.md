# /brain map

Check or regenerate the codemap's generated code layer, and find directories that still need a human-written `## Modules` row.

## Run

- Check freshness only:
  ```bash
  {BRAIN} map
  ```
  Prints `fresh`, `stale — run map --regen`, or `unknown (not a git repo)`, plus file count and head sha.
- Regenerate the generated layer (files, symbols, imports, deps) without touching the curated `## Modules` / `## Where to look` tables:
  ```bash
  {BRAIN} map --regen
  ```
  Add `--force` to rebuild even when nothing looks stale.
- Find directories missing curated annotation:
  ```bash
  {BRAIN} map --annotate
  ```
  Lists top-level and top-two-level directories with 3+ source files not covered by any `## Modules` row (path + file count), or "all major directories have a Modules row".

## Then

For each directory `--annotate` lists (top ones first — it's capped at 10), read enough of it to write one `## Modules` row in `codemap.md`:

```
| module | path | responsibility | links |
```

`module` is a short name, `path` the directory, `responsibility` one line on what it does, `links` any wikilinks to concept notes or other projects it relates to. If you know a question a future session would ask about this area ("where does X live?"), add a `## Where to look` row too:

```
| question | path |
```

Never touch the generated layer above the curated block — only `map --regen` writes that.

## Report

State whether the codemap was fresh/stale/regenerated, and list which directories you annotated (or that none needed it).
