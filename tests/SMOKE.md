# Live smoke test (manual, isolated)

This procedure exercises the real `claude` binary against the Python hooks in
`brain/` + `hooks/hooks.json`, entirely inside a scratch sandbox. It never
touches this repo's own `CLAUDE.md`, `.claude/settings.json`, or the real
vault — run it before cutting a release or merging a hooks change.

`$REPO` below is this checkout. Set it once, from anywhere inside the repo:

```bash
REPO=$(git rev-parse --show-toplevel)
```

Never substitute a home-directory path for `$REPO` in this file — a worktree
or a second clone must be able to run this unchanged.

## 1. Build the sandbox

```bash
S=$(mktemp -d)

# Scratch vault, same shape tests/helpers.make_vault produces.
python3 - "$REPO" "$S" <<'EOF'
import sys
sys.path.insert(0, sys.argv[1])
from tests.helpers import make_vault
make_vault(sys.argv[2], slug="smoke")
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
printf 'def a():\n    return 1\n' > "$S/repo/a.py"
git -C "$S/repo" add . && git -C "$S/repo" commit -q -m init

# brain.config + env
# async_regen MUST be false in every sandbox config here — otherwise SessionStart and the
# graph loads below spawn a real detached `map --regen` process against the scratch repo.
echo "{\"vault\": \"$S/vault\", \"async_regen\": false}" > "$S/brain.config"
mkdir -p "$S/data"
```

## 2. Run each check from `$S/repo`

Each check is a separate `claude -p` call:

```bash
cd "$S/repo"
env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT BRAIN_CONFIG="$S/brain.config" CLAUDE_PLUGIN_DATA="$S/data" \
  claude -p --model haiku --plugin-dir "$REPO" \
  --allowedTools "Bash,Edit,Read" --output-format text "<prompt>"
```

`--plugin-dir` is sufficient to load `hooks/hooks.json` from this repo — no
fallback registration in `.claude/settings.json` was needed the last time
this was run (see below). If a future run shows no "Brain:" block, fall back
to writing the eight `hook <Event>` commands into `$S/repo/.claude/settings.json`
directly and note that in "Last run".

Claude Code sets `CLAUDE_PLUGIN_DATA` itself (to `~/.claude/plugins/data/brain-inline`),
overriding the `$S/data` value exported above — so session state and `brain.log`
land there, not in the sandbox. Look there when a check needs them.

### Check 1 — Injection + migration

Prompt: `Reply with the exact first line of any block in your context that starts with "Brain:" and then the text of the "## State" section you were given.`

Expect: reply quotes `Brain: vault context for "smoke"` and `Alpha works.`.
Afterwards: `$S/repo/CLAUDE.md` is the slim block + `---\n# My notes` (legacy
text gone); `.claude/settings.json` no longer contains `brain-session-start.sh`;
`brain.log` is absent or empty.

### Check 2 — No architecture injection

Same run as Check 1 — reply must NOT contain `All DB calls go through`.

### Check 3 — Commit tracking + Stop gate

Prompt: `This is a hook test and I explicitly authorize this one commit on main; do not ask. Do exactly this and nothing else: 1) Bash: echo x >> a.py && git add a.py && git commit -q -m "feat: x". 2) Reply DONE.`

The authorization clause is load-bearing: the fixture `context.md` carries the
Hard Rule "Never commit directly to `main`", and a model that reads its context
correctly will otherwise refuse and ask — which is the injection working, but
leaves this check unexercised.

Expect, verified from the files (not the reply):

- `$S/vault/projects/smoke/context.md` frontmatter gains `branch: main`;
- `## State` / `## Active Work` in that file were rewritten to mention the commit.

Either route counts as a pass, and which one you get is model-dependent:

1. Claude acts on the `Brain: commit landed` reminder inside the same turn and
   replies `DONE` — nothing left for the gate to block. This is the expected
   route now that `PostToolUse` delivers through `additionalContext`.
2. Claude ignores the reminder, the `Stop` gate blocks once, and it is forced
   into a second turn — the final reply is then not a bare `DONE`.

`log.md` may end up with a `(auto-close)` entry rather than a hand-written one:
`SessionEnd` writes it when the session updated `context.md` but never appended
a log entry. That is correct behaviour, not a miss.

### Check 4 — Idle SessionEnd

Count `## ` entries in `log.md` before. Prompt: `Reply with exactly: hello`.
Expect: entry count unchanged afterwards (no auto-close for an idle session).

### Check 5 — Migration idempotent

Re-run the Check 1 prompt. Expect: reply/stdout does NOT contain
`Brain: migrated` a second time, and `CLAUDE.md` is byte-for-byte unchanged
from after Check 1.

## Checks 6–10 — retrieval, briefing, graph, agent notes (separate sandbox)

Checks 6–10 use a *second* scratch sandbox (a fresh `mktemp -d`, call it `$S`)
built directly from `tests.helpers` so the graph has real content to hit,
rather than reusing the Check 1–5 sandbox (which by then has migrated away
its legacy state):

```bash
S=$(mktemp -d)
python3 - "$REPO" "$S" <<'EOF'
import sys, os
sys.path.insert(0, sys.argv[1])
from tests.helpers import make_vault, make_project, make_source_tree
S = sys.argv[2]
vault = make_vault(S, slug="smoke")
repo = make_project(S, slug="smoke", vault=vault, legacy=False)
make_source_tree(repo)
EOF

# Add a `## Modules` row so retrieval / graph top have a module node to hit.
python3 - "$REPO" "$S" <<'EOF'
import sys, os
sys.path.insert(0, sys.argv[1])
S = sys.argv[2]
pdir = os.path.join(S, "vault", "projects", "smoke")
from brain import codemap
codemap.ensure(os.path.join(S, "repo"), pdir)
path = os.path.join(pdir, "codemap.md")
with open(path, encoding="utf-8") as f:
    text = f.read()
head = "## Modules\n| module | path | responsibility | links |\n|---|---|---|---|\n"
text = text.replace(head, head + "| Auth flow | src/auth/ | Session cookies | uses:: [[concepts/nextauth|NextAuth]] |\n")
with open(path, "w", encoding="utf-8") as f:
    f.write(text)
EOF

echo "{\"vault\": \"$S/vault\", \"async_regen\": false}" > "$S/brain.config"
mkdir -p "$S/data"
cd "$S/repo"
```

Each check below is its own `claude -p` call with the same env/flags as
Checks 1–5 (`--allowedTools "Bash,Edit,Read,Grep"`, plus `Agent,Task` for
Checks 8 and 10).

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
  python3 "$REPO/brain/__main__.py" graph top
```

Expect: first line is `project smoke  projects/smoke/context.md  — smoke  (N)`.

### Check 10 — vault-notes reminder via `PostToolUse`

`SubagentStop` is gone: a previous run of this check (recorded under "Last
run") proved its output is fed back into the *finished subagent's* own loop,
not the parent turn, so a reminder sent there lands where nobody can act on
it. v2 delivers the reminder on the two channels that do reach the parent:

- `PostToolUse` on the foreground subagent tool call — this check;
- the `<task-notification>` prompt a *background* agent's completion submits,
  handled in `UserPromptSubmit`.

The handler branches on `hooks.AGENT_TOOLS` (`Agent` and `Task`) and
`hooks/hooks.json` matches both, because different Claude Code builds put
different names in `tool_name`. **Record which one this build actually sends**
(see the payload probe below) in "Last run".

Same sandbox and flags as Checks 6–9, plus `Agent,Task` in `--allowedTools`,
and `--model sonnet` (haiku is too unreliable at reporting what it did or did
not receive).

Prompt: `Step 1: use the Task tool with subagent_type general-purpose and this exact prompt: 'Do no work. Reply with exactly two lines. Line 1: SUBAGENT OK. Line 2: Vault notes: none.' Step 2: after it returns, report whether YOU (the top-level assistant) received, at any point after the subagent finished, any message or context line beginning with the word Brain: that tells you to fold vault notes into architecture.md. If yes, reply 'GOT IT: ' followed by that line verbatim. If no, reply exactly 'NO BRAIN LINE'. Do not dispatch a second subagent.`

Expect: the parent replies `GOT IT: Brain: subagent reported vault notes —
fold them into .../architecture.md / codemap.md ## Modules now ...` (no agent
type in the text). `-p` mode prints only the final assistant turn, so a
negative answer alone is not proof the hook never fired — confirm with the
payload probe.

**Payload probe (also records the live tool name).** Temporarily add, at the
top of `on_post_tool_use` in `brain/hooks.py`:

```python
config.log_error("PostToolUse tool_name=%r" % ctx.payload.get("tool_name"))
```

then re-run and read `~/.claude/plugins/data/brain-inline/brain.log` (not
`$S/data` — see the note in section 2). Remove the line afterwards.

The same probe answers a non-interactive variant of this check: feed a payload
straight to the hook and confirm the reminder text comes back, which needs no
`claude` session at all —

```bash
cd "$S/repo"
for tool in Agent Task; do
  printf '{"session_id":"probe","cwd":"%s","hook_event_name":"PostToolUse","tool_name":"%s","tool_input":{"prompt":"x"},"tool_response":{"content":"Done.\\n\\nVault notes:\\n- x"}}' "$PWD" "$tool" \
  | env BRAIN_CONFIG="$S/brain.config" CLAUDE_PLUGIN_DATA="$S/data" \
      python3 "$REPO/brain/__main__.py" hook PostToolUse
  echo
done
```

Expect one `Brain: subagent reported vault notes — ...` line per tool name.
This proves the handler; only the live run proves Claude Code delivers it to
the parent.

## Last run — v2.0.0 release (checks 1–10)

- **Date:** 2026-09-08
- **Build:** `claude` 2.1.263. **Mode:** `--plugin-dir "$REPO"`, no `settings.json` fallback needed.
- **Sandboxes:** three `mktemp -d` sandboxes as described above; every `brain.config` had `"async_regen": false`. The real vault, `~/.claude/brain.config` and this repo's own files were never touched.
- **Check 1 (Injection + migration): PASS.** Reply quoted `Brain: vault context for "smoke" follows.` and `## State / Alpha works.`. `CLAUDE.md` reduced to the slim block + `---\n# My notes`, `CLAUDE.md.brain-bak` written, `.claude/settings.json` became `{}`, no new `brain.log` entries.
- **Check 2 (No architecture injection): PASS.** `grep -c "All DB calls go through"` on the captured reply = 0.
- **Check 3 (Commit + vault write): PASS, via route 1.** Reply was a bare `DONE`, and that is now the *correct* outcome: the probe below shows `PostToolUse(Bash)` → `note_commit 'feat: x'`, then `PostToolUse(Read)` and two `PostToolUse(Edit)` on `context.md` → `note_vault_write`, and only then `Stop k=0 m=0` — i.e. Claude acted on the `Brain: commit landed` reminder within the turn, so the gate had nothing left to block. `context.md` gained `branch: main` and rewritten `## State` ("Test commit (feat: x) on main completed.") / `## Active Work`. `log.md` got a `(auto-close)` entry from SessionEnd. A first attempt with the original prompt was refused by the model on the fixture's `main` Hard Rule — hence the authorization clause now in the check.
- **Check 4 (Idle SessionEnd): PASS.** `## ` count in `log.md` unchanged across a plain `hello` reply (run twice, in two sandboxes).
- **Check 5 (Migration idempotent): PASS.** No `Brain: migrated` in the re-run; `CLAUDE.md` diffed byte-identical to its post-Check-1 state; no second `.brain-bak`.
- **Check 6 (Per-prompt graph hits): PASS.** `Brain: graph hits for "smoke, Auth flow, Use Postgres (2026-01-02)" —` with `module auth-flow  src/auth/  — Auth flow`, its `Session cookies` responsibility and its file list.
- **Check 7 (Grep pre-tool context): PASS.** `Brain: graph already knows — symbol src/auth/session.ts#SessionStore  src/auth/session.ts  — SessionStore`.
- **Check 8 (Subagent briefing): PASS.** `SUBAGENT SAID: Brain briefing: this project is "smoke". Vault: <tmp>/vault/projects/smoke/ (context.md, architecture.md, codemap.md).`
- **Check 9 (`graph top` CLI): PASS.** First line `project smoke  projects/smoke/context.md  — smoke  (4)`, then `module auth-flow (3)`, the decision, the question and the architecture section.
- **Check 10 (vault-notes reminder): PASS after a fix — see below.** Non-interactive probe: the handler returns the reminder for `tool_name` `Agent` *and* `Task`. Live: the parent replied `GOT IT: Brain: subagent reported vault notes — fold them into .../architecture.md / codemap.md ## Modules now (a concept note only if you'd link it from more than one place).`
- **Live tool name (carried question):** this build sends **`tool_name='Agent'`** for a `Task`-tool subagent dispatch. The `Task` alias in `hooks.AGENT_TOOLS` and in the `hooks.json` matcher is kept as forward/backward cover; only `Agent` was observed.

### Bug found and fixed by this run

**`PostToolUse` stdout never reaches the model** — the same class of miss that cost us
`SubagentStop`. Measured three ways in Claude Code 2.1.263:

1. Check 10 first attempt: the handler fired (`tool_name='Agent'`, `tool_response` carried
   `Vault notes: none.`) and returned the reminder on stdout — the parent still answered
   `NO BRAIN LINE`.
2. Isolated probe with `gate: off`, so the `Stop` gate could not be the explanation: after a
   real `git commit`, asked whether a line starting `Brain: commit landed` had appeared.
   Answer: `NO`.
3. Same probe with the handler's text moved to
   `hookSpecificOutput.additionalContext`: `YES: Brain: commit landed — update ## State and
   ## Active Work in .../context.md before continuing.`

Fix: `hooks.dispatch` routes every `PostToolUse` result through `_deliverable`, which wraps
stdout in `hookSpecificOutput.additionalContext` (keeping `stdout` on the `HookResult` so
handlers and tests still read one field). Only `PostToolUse` is listed — `SessionStart` and
`UserPromptSubmit` do inject stdout and were left alone. Covered by
`tests/test_hooks_post.py::PostToolUseDeliveryTests`. Re-running check 10 after the fix
passed, and check 3 changed route as described above, which is how the fix made itself visible.

`PreCompact` stdout is very likely transcript-only for the same reason, but this harness
cannot trigger a real compaction, and speculatively wrapping it would lose the text if that
event does not honour `additionalContext`. Left as-is; its checkpoint entry is written
directly to `log.md` regardless, so the record survives even when the enrichment prompt does
not land. **Open item for the next live run.**

- **Unit tests at the time of this run:** 258 green, plain, with `CLAUDE_PROJECT_DIR=$PWD`, and under `-W error::ResourceWarning`.

## Earlier runs

### Plan 1 (checks 1–5)

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

### Check 10, first attempt (SubagentStop, since removed)

- **Date:** 2026-09-08
- **Check 10 (SubagentStop reminder): FAIL as designed — the reminder does not reach the parent.** Four runs (haiku ×3, sonnet ×1) all ended in `NO BRAIN LINE`. Instrumenting `on_subagent_stop` with a `config.log_error` of the payload proved the hook *does* fire and *does* emit: the payload carries `last_assistant_message` (`'SUBAGENT OK.\nVault notes: none.'`), so the `"Vault notes:"` guard passed and the JSON was returned. The give-away is the *next* two `SubagentStop` payloads in the same run: `'I have no vault notes to fold in — my prior report explicitly said "Vault notes: none." Nothing to update in architecture.md or codemap.md.'` and `'I\'ll note again: I did no research and reported no vault notes ("none") …'`. That is the **subagent** answering our reminder. So Claude Code feeds `SubagentStop` output back into the finished subagent's own loop (the way `Stop` output does for the main agent), not into the parent turn. This held for `hookSpecificOutput.additionalContext` and for a top-level `systemMessage` alike.
- **Resolution (Plan 3):** `SubagentStop` was dropped entirely; the reminder moved to `PostToolUse` on the subagent tool call and to the `<task-notification>` prompt. Check 10 above was rewritten for that.
- **Environment note recorded above:** Claude Code overrides `CLAUDE_PLUGIN_DATA` with `~/.claude/plugins/data/brain-inline`; the `$S/data` export in the sandbox recipe has no effect on where hooks write state or `brain.log`.
