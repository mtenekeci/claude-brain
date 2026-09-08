# /brain config

Show or update Brain's configuration.

## Run

- Show current config:
  ```bash
  {BRAIN} config
  ```
  Prints `vault`, `gate`, `async_regen`, `graph.backend`, and the config file path.
- Update a value:
  ```bash
  {BRAIN} config set <key> <value>
  ```

## Keys

| Key | Values | Meaning |
|---|---|---|
| `vault` | an existing directory path | Where the vault lives. Rejected if the path doesn't exist. |
| `gate` | `all` \| `commits` \| `off` | How strict the Stop-hook enforcement is: `all` blocks on commits or several source edits without a vault write, `commits` only on commits, `off` disables the gate. |
| `async_regen` | `on` \| `off` | Whether codemap regeneration on a large repo runs as a detached background process instead of inline. |
| `graph.backend` | `builtin` \| `graphify` \| `auto` | Which engine answers graph queries (including `graph ask`). `auto` picks the best available. |

## Then

Nothing to write — `config set` is fully mechanical. If the CLI returns exit 1 (invalid key or value, or a vault path that doesn't exist), relay its message; don't retry with a guessed value.

## Report

Relay the CLI's printed lines as-is (either the full config, or `<key>: <new value>`).
