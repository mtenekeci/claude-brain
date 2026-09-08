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
# async_regen MUST be false here — otherwise SessionStart / graph loads below spawn a real
# detached `map --regen` process against the scratch repo.
echo "{\"vault\": \"$S/vault\", \"async_regen\": false}" > "$S/brain.config"
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

## Checks 6–9 — retrieval + briefing (separate sandbox)

Checks 6–9 use a *second* scratch sandbox (a fresh `mktemp -d`, call it `$S`)
built directly from `tests.helpers` so the graph has real content to hit,
rather than reusing the Check 1–5 sandbox (which by then has migrated away
its legacy state):

```bash
S=$(mktemp -d)
python3 - "$S" <<'EOF'
import sys, os
sys.path.insert(0, "/Users/mtenekeci/Documents/Projects/claude-brain")
from tests.helpers import make_vault, make_project, make_source_tree
S = sys.argv[1]
vault = make_vault(S, slug="smoke")
repo = make_project(S, slug="smoke", vault=vault, legacy=False)
make_source_tree(repo)
EOF

# Add a `## Modules` row so retrieval / graph top have a module node to hit.
python3 - "$S" <<'EOF'
import sys, os
sys.path.insert(0, "/Users/mtenekeci/Documents/Projects/claude-brain")
S = sys.argv[1]
pdir = os.path.join(S, "vault", "projects", "smoke")
from brain import codemap
codemap.ensure(os.path.join(S, "repo"), pdir)
path = os.path.join(pdir, "codemap.md")
text = open(path, encoding="utf-8").read()
text = text.replace(
    "## Modules\n| module | path | responsibility | links |\n|---|---|---|---|\n",
    "## Modules\n| module | path | responsibility | links |\n|---|---|---|---|\n"
    "| Auth flow | src/auth/ | Session cookies | uses:: [[concepts/nextauth|NextAuth]] |\n")
open(path, "w", encoding="utf-8").write(text)
EOF

echo "{\"vault\": \"$S/vault\", \"async_regen\": false}" > "$S/brain.config"
mkdir -p "$S/data"
cd "$S/repo"
```

Each check below is its own `claude -p` call with the same env/flags as
Checks 1–5 (`--allowedTools "Bash,Edit,Read,Grep"`, plus `Agent,Task` for
Check 8).

### Check 6 — Per-prompt graph hits

Prompt: `I need to work on the auth flow module. Reply with the exact text of any block in your context that starts with the words Brain: graph hits, verbatim.`

Expect: reply quotes a `Brain: graph hits for "..."` block containing
`module auth-flow  src/auth/  — Auth flow`. Front-load the module name in the
prompt — `retrieve.tokens` caps at 12 terms, so a wordy prompt can push the
term of interest past the cap and the hit silently falls back to generic
project/decision/question nodes instead (observed once while drafting this
check).

Dedupe note: dedupe of repeat hits is scoped to `state.injected` on the
*session*, not the CLI invocation — each separate `claude -p` gets a fresh
session id, so a second `claude -p` run with an identical prompt is expected
to repeat the block rather than suppress it. That's by design, not a bug;
this check only asserts the block appears (once) in a single run.

### Check 7 — Grep pre-tool context

Prompt: `Run a Grep for the symbol SessionStore in this repo. Before or after doing so, your tool context may include a line starting with the words Brain: graph already knows — quote that exact line verbatim if present, otherwise say NONE.`

Expect: reply quotes `Brain: graph already knows —` followed by a
`symbol src/auth/session.ts#SessionStore ... — SessionStore` line.

### Check 8 — Subagent briefing

Prompt: `Dispatch an Explore subagent (or Task tool general-purpose agent if Explore is unavailable) with this exact instruction: 'Reply with only the first line of your context that starts with the words Brain briefing:, verbatim, and nothing else.' Then relay that subagent's exact reply back to me, prefixed with SUBAGENT SAID:.`
(add `Agent,Task` to `--allowedTools` for this one run)

Expect: reply contains `SUBAGENT SAID: Brain briefing: this project is "smoke". Vault: .../projects/smoke/ (context.md, architecture.md, codemap.md).`

### Check 9 — `graph top` CLI

From `$S/repo`:

```bash
env BRAIN_CONFIG="$S/brain.config" CLAUDE_PLUGIN_DATA="$S/data" \
  python3 /Users/mtenekeci/Documents/Projects/claude-brain/brain/__main__.py graph top
```

Expect: first line is `project smoke  projects/smoke/context.md  — smoke  (N)`.

### Check 10 — vault-notes reminder (PostToolUse on `Agent`)

> Plan 3: `SubagentStop` is gone — the "Last run" note below proved its output goes to the
> finished subagent, not the parent. The reminder now rides the parent-visible channels:
> `PostToolUse` on the foreground `Agent` tool call (this check) and, for a background agent,
> the `<task-notification>` prompt (`UserPromptSubmit`). Re-run the prompt below unchanged;
> the expected line is now `Brain: subagent reported vault notes — fold them into
> .../architecture.md / codemap.md ## Modules now ...` (no agent type in it), and it must
> reach the PARENT. To see whether the hook fired, log from `on_post_tool_use`'s `Agent`
> branch instead of the deleted `on_subagent_stop`.


Same sandbox and flags as Checks 6-9, plus `Agent,Task` in `--allowedTools`.

Prompt: `Step 1: use the Task tool with subagent_type general-purpose and this exact prompt: 'Do no work. Reply with exactly two lines. Line 1: SUBAGENT OK. Line 2: Vault notes: none.' Step 2: after it returns, report whether YOU (the top-level assistant) received, at any point after the subagent finished, any message or context line beginning with the word Brain: that tells you to fold vault notes into architecture.md. If yes, reply 'GOT IT: ' followed by that line verbatim. If no, reply exactly 'NO BRAIN LINE'. Do not dispatch a second subagent.`

Expect (as designed): the parent quotes `Brain: subagent '<type>' reported vault
notes — fold them into .../architecture.md ...`.

Observed instead: see "Last run" below — the text is delivered to the *subagent*,
not the parent. Use `--model sonnet` (haiku is too unreliable at reporting what it
did or did not receive), and note that `-p` mode prints only the final assistant
turn, so a negative answer alone is not proof the hook never fired. To see whether
it fired at all, temporarily add a `config.log_error(...)` line at the top of
`on_subagent_stop` and read `$CLAUDE_PLUGIN_DATA/brain.log` — and note that Claude
Code sets `CLAUDE_PLUGIN_DATA` itself (to `~/.claude/plugins/data/brain-inline`),
overriding the `$S/data` value the commands above export, so look there.

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

### Checks 6–9 (Task 12, separate sandbox)

- **Date:** 2026-09-08
- **Mode:** `--plugin-dir`, second scratch sandbox built via `tests.helpers` as described above; `brain.config` included `"async_regen": false`.
- **Check 6 (Per-prompt graph hits): PASS.** First attempt used a longer, quote-heavy prompt and the reply's `Brain: graph hits` block surfaced only generic `project`/`decision`/`question` nodes — no `auth-flow` hit. Root cause (confirmed with a direct `retrieve.tokens`/`retrieve.select` call): `retrieve.tokens` caps at 12 terms and the wordy prompt pushed "auth"/"flow"/"module" past the cap before they were ever extracted, so `select` fell back to the top-scoring generic nodes. This is retrieval behaving correctly given its token budget, not a bug — re-ran with a shorter, front-loaded prompt (`I need to work on the auth flow module. ...`) and got: `Brain: graph hits for "smoke, Auth flow, Use Postgres (2026-01-02)" —` followed by `module auth-flow  src/auth/  — Auth flow` with its `Session cookies` responsibility and file list. Recorded the front-loading caveat directly in the Check 6 instructions above. Cross-run dedupe: not directly observable via `-p` (each invocation gets a fresh session id, so `state.injected` dedupe never engages across separate `claude -p` calls) — this is dedupe-by-design, not something this harness can exercise; noted in the check text rather than asserted as PASS/FAIL.
- **Check 7 (Grep pre-tool context): PASS.** Reply: `**Brain: graph already knows —**` followed by `symbol src/auth/session.ts#SessionStore  src/auth/session.ts  — SessionStore`.
- **Check 8 (Subagent briefing): PASS.** Reply: `SUBAGENT SAID: Brain briefing: this project is "smoke". Vault: <tmp>/vault/projects/smoke/ (context.md, architecture.md, codemap.md).` — first line of the briefing, quoted verbatim by the dispatched subagent.
- **Check 9 (`graph top` CLI): PASS.** First line of output: `project smoke  projects/smoke/context.md  — smoke  (4)`, ahead of `module auth-flow`, the decision, the question, and the architecture section node.
- **Bugs found:** none in `brain/` — the Check 6 surprise was a prompt-authoring issue (token-budget interaction with prompt wording), not a defect; no code or test change was warranted.
- **Unit tests:** full suite green both plain and with `CLAUDE_PROJECT_DIR=$PWD` set (154 tests, including the 3 new `tests/test_budgets.py` cases).

### Check 10 (final fix wave, SubagentStop verification)

- **Date:** 2026-09-08
- **Mode:** `--plugin-dir`, third scratch sandbox built via `tests.helpers` exactly as Checks 6-9 describe; `brain.config` had `"async_regen": false`.
- **Check 10 (SubagentStop reminder): FAIL as designed — the reminder does not reach the parent.** Four runs (haiku ×3, sonnet ×1) all ended in `NO BRAIN LINE`. Instrumenting `on_subagent_stop` with a `config.log_error` of the payload proved the hook *does* fire and *does* emit: the payload carries `last_assistant_message` (`'SUBAGENT OK.\nVault notes: none.'`), so the `"Vault notes:"` guard passed and the JSON was returned. The give-away is the *next* two `SubagentStop` payloads in the same run: `'I have no vault notes to fold in — my prior report explicitly said "Vault notes: none." Nothing to update in architecture.md or codemap.md.'` and `'I\'ll note again: I did no research and reported no vault notes ("none") …'`. That is the **subagent** answering our reminder. So Claude Code feeds `SubagentStop` output back into the finished subagent's own loop (the way `Stop` output does for the main agent), not into the parent turn. This holds for `hookSpecificOutput.additionalContext` and for a top-level `systemMessage` alike — both were present on the last two runs and neither surfaced to the parent.
- **Change made:** `on_subagent_stop` now returns the text on **both** channels (`hookSpecificOutput.additionalContext` and a top-level `systemMessage`), per the fix-wave instruction. It did not change the observed outcome; it is kept because `systemMessage` is the documented parent-facing channel and costs nothing if a later Claude Code version honours it.
- **Not a loop:** the reminder costs the subagent one or two extra turns and then stops — its follow-up replies do not contain the literal `Vault notes:`, so the guard in `on_subagent_stop` returns EMPTY for them. Bounded, but the reminder is currently addressed to the wrong agent, and a subagent cannot act on it (it is told not to write to the vault by `briefing.text`). **Open issue for Plan 3:** either drop `SubagentStop` and rely on the parent's own `## Vault notes:` convention (already in the briefing), or re-word the text so it reads sensibly to the subagent that actually receives it.
- **Environment note recorded above:** Claude Code overrides `CLAUDE_PLUGIN_DATA` with `~/.claude/plugins/data/brain-inline`; the `$S/data` export in the sandbox recipe has no effect on where hooks write state or `brain.log`.
- **Unit tests:** 167 green, plain and with `CLAUDE_PROJECT_DIR=$PWD`.
