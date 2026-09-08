# /brain remove <slug> / /brain disconnect <slug>

`remove` permanently deletes a project from the vault. `disconnect` stops tracking it without deleting vault history.

## Run — remove

```bash
{BRAIN} remove <slug>
```

Without `--confirm`, this only prints what would happen and exits 1 — it never deletes on the first call. Once the user has seen that and explicitly confirms, re-run with:

```bash
{BRAIN} remove <slug> --confirm <slug>
```

`--confirm` must match `<slug>` exactly. This deletes `VAULT_ROOT/projects/<slug>/`, removes its project-index row, and — if the project's folder is still connected to that same slug (never to a *different* one) — strips the `CLAUDE.md` brain block there too and removes legacy hooks.

## Run — disconnect

```bash
{BRAIN} disconnect <slug>
```

No confirmation needed — it only removes the `CLAUDE.md` brain block from the connected folder. Vault files (`context.md`, `log.md`, `architecture.md`) are left untouched. Refuses if the folder has no path on record, isn't connected, or is connected to a different slug.

## Then

Nothing to write — both are fully mechanical CLI operations with no prose step.

## Report

Relay the CLI's output as-is:
- `remove` (unconfirmed): the "This will permanently delete..." + "Type '<slug>' to confirm" lines.
- `remove` (confirmed): `Removed: <slug>`, `Vault files deleted.`, `Index row removed.`, and any CLAUDE.md/hook-removal or "left untouched" warning line.
- `disconnect`: `Disconnected: <slug>`, `CLAUDE.md brain section removed from <path>`, `Vault files untouched...` — or the specific refusal message (not found / no path / already disconnected / connected to another slug).
