# Live smoke test (manual, isolated)

This procedure exercises the real `claude` binary against the Python hooks in
`brain/` + `hooks/hooks.json`, entirely inside a scratch sandbox. It never
touches this repo's own `CLAUDE.md`, `.claude/settings.json`, or the real
vault — run it before cutting a release or merging a hooks change.

## 1. Build the sandbox

```bash
S=$(mktemp -d)

# Scratch vault, same shape tests/helpers.make_vault produces.
python3 - "$S" <<'EOF'
import sys
sys.path.insert(0, "/Users/mtenekeci/Documents/Projects/claude-brain")
from tests.helpers import make_vault
make_vault(sys.argv[1], slug="smoke")
EOF
# make_vault's context.md already carries:
#   ## Hard Rules
#   - Never commit directly to `main`.

# Scratch project repo with a *legacy* CLAUDE.md + a legacy hook entry.
mkdir -p "$S/repo/.claude"
cat > "$S/repo/CLAUDE.md" <<EOF
# Brain: smoke

vault: $S/vault/projects/smoke

## Context protocol
old text
---
# My notes
EOF
cat > "$S/repo/.claude/settings.json" <<'JSON'
{
  "hooks": {
    "SessionStart": [
      {"hooks": [{"type": "command", "command": "bash $CLAUDE_PLUGIN_ROOT/hooks/brain-session-start.sh"}]}
    ]
  }
}
JSON
git -C "$S/repo" init -q -b main
git -C "$S/repo" config user.email t@t
git -C "$S/repo" config user.name t
echo -e "def a():\n    return 1" > "$S/repo/a.py"
git -C "$S/repo" add . && git -C "$S/repo" commit -q -m init

# brain.config + env
echo "{\"vault\": \"$S/vault\"}" > "$S/brain.config"
mkdir -p "$S/data"
```

## 2. Run each check from `$S/repo`

Each check is a separate `claude -p` call:

```bash
cd "$S/repo"
env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT BRAIN_CONFIG="$S/brain.config" CLAUDE_PLUGIN_DATA="$S/data" \
  claude -p --model haiku --plugin-dir /Users/mtenekeci/Documents/Projects/claude-brain \
  --allowedTools "Bash,Edit,Read" --output-format text "<prompt>"
```

`--plugin-dir` is sufficient to load `hooks/hooks.json` from this repo — no
fallback registration in `.claude/settings.json` was needed the last time
this was run (see below). If a future run shows no "Brain:" block, fall back
to writing the nine `hook <Event>` commands into `$S/repo/.claude/settings.json`
directly and note that in "Last run".

### Check 1 — Injection + migration

Prompt: `Reply with the exact first line of any block in your context that starts with "Brain:" and then the text of the "## State" section you were given.`

Expect: reply quotes `Brain: vault context for "smoke"` and `Alpha works.`.
Afterwards: `$S/repo/CLAUDE.md` is the slim block + `---\n# My notes` (legacy
text gone); `.claude/settings.json` no longer contains `brain-session-start.sh`;
`$S/data/brain.log` is absent or empty.

### Check 2 — No architecture injection

Same run as Check 1 — reply must NOT contain `All DB calls go through`.

### Check 3 — Commit tracking + Stop gate

Prompt: `Do exactly this and nothing else: 1) Bash: echo x >> a.py && git add a.py && git commit -q -m "feat: x". 2) Reply DONE.`

Expect: the Stop hook blocks once, so the final reply is NOT a bare "DONE" —
Claude is forced into a second turn where it updates the vault. Verify via
files: `$S/vault/projects/smoke/context.md` frontmatter gains `branch: main`;
`log.md` gains a new `## ` entry describing the commit.

### Check 4 — Idle SessionEnd

Count `## ` entries in `log.md` before. Prompt: `Reply with exactly: hello`.
Expect: entry count unchanged afterwards (no auto-close for an idle session).

### Check 5 — Migration idempotent

Re-run the Check 1 prompt. Expect: reply/stdout does NOT contain
`Brain: migrated` a second time, and `CLAUDE.md` is byte-for-byte unchanged
from after Check 1.

## Last run

- **Date:** 2026-09-07
- **Mode:** `--plugin-dir` (no settings.json fallback needed — hooks loaded and fired correctly).
- **Check 1 (Injection + migration): PASS.** Reply: `Brain: vault context for "smoke" follows. It is authoritative for state, decisions, history, and hard rules.` + `## State\nAlpha works.`. `CLAUDE.md` reduced to the slim block + `---\n# My notes`. `.claude/settings.json` became `{}` (legacy `SessionStart` hook stripped). `$S/data/brain.log` did not exist.
- **Check 2 (No architecture injection): PASS.** `grep -c "All DB calls go through"` on the captured stdout = 0.
- **Check 3 (Commit + Stop gate): PASS.** Final reply was `Vault updated. The commit "feat: x" has been logged in the smoke project context.` (not a bare DONE), confirming the Stop hook forced a second turn. `context.md` frontmatter gained `branch: main`. `log.md` gained a `## 2026-09-07 · Session 2` entry describing the commit. Note: the raw "Brain: this turn landed ..." block-reason text itself is not visible in `--output-format text` output (only the final assistant turn is printed by `-p` mode) — the gate's *effect* (non-DONE reply + vault edits) is the observable evidence here, not the literal hook string.
- **Check 4 (Idle SessionEnd): PASS.** `## ` entry count in `log.md` was 2 before and 2 after a plain "hello" reply.
- **Check 5 (Migration idempotent): PASS.** No `Brain: migrated` in the re-run's stdout; `CLAUDE.md` diffed byte-identical to its post-Check-1 state.
- **Bugs found:** none. All 61 unit tests remained green after deleting the bash hooks (`python3 -m unittest discover -s tests`).
- **Deviation from the original plan:** this run used a fully isolated scratch vault/repo/config instead of this repository's own files, so as not to mutate the maintainer's live `CLAUDE.md` / `.claude/settings.json` / real vault. Re-run against this repo itself before a release if you want the original in-repo variant.
