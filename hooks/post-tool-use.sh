#!/bin/bash
# Brain PostToolUse hook
# - Counts source file reads, reminds to update architecture.md every 3 reads
# - Detects git commits, reminds to update context.md State + Active Work immediately
# - Detects Agent tool completion, reminds to sync brain after superpowers tasks

set -euo pipefail

INPUT=$(cat)

TOOL_NAME=$(python3 -c "
import json, sys
try:
    d = json.loads(sys.argv[1])
    print(d.get('tool_name', ''))
except:
    pass
" "$INPUT" 2>/dev/null) || true

[ -z "$TOOL_NAME" ] && exit 0

# ── Shared helpers ────────────────────────────────────────────────────────────

VAULT=$(python3 -c "
import json, os
cfg = os.path.expanduser('~/.claude/brain.config')
if os.path.exists(cfg):
    print(json.load(open(cfg))['vault'])
" 2>/dev/null) || true

SLUG=$(awk -F'/' '/^vault:/{print $NF}' CLAUDE.md 2>/dev/null | tr -d '[:space:]') || true

# ── Bash tool — detect git commit ────────────────────────────────────────────

if [ "$TOOL_NAME" = "Bash" ]; then
    CMD=$(python3 -c "
import json, sys
try:
    d = json.loads(sys.argv[1])
    print(d.get('tool_input', {}).get('command', ''))
except:
    pass
" "$INPUT" 2>/dev/null) || true

    if echo "$CMD" | grep -qE "git push"; then
        CONTEXT_PATH=""
        [ -n "$VAULT" ] && [ -n "$SLUG" ] && CONTEXT_PATH=" ($VAULT/projects/$SLUG/context.md)"
        CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "?")
        echo "Brain: git push just ran on branch '${CURRENT_BRANCH}'. Verify NOW: (1) does this branch match the expected sub-branch in ## Active Work in context.md${CONTEXT_PATH}? If not, the push went to the wrong target — tell the user immediately. (2) Does the push respect ## Hard Rules? For all future pushes this session, run 'git branch --show-current' BEFORE pushing and reconcile against Active Work."
        exit 0
    fi

    echo "$CMD" | grep -qE "git commit" || exit 0

    CONTEXT_PATH=""
    [ -n "$VAULT" ] && [ -n "$SLUG" ] && CONTEXT_PATH=" ($VAULT/projects/$SLUG/context.md)"
    echo "Brain: VAULT WRITE REQUIRED — git commit just landed. Your next action MUST be an Edit to context.md${CONTEXT_PATH} updating ## State and ## Active Work to reflect this commit. Do this BEFORE any further code work, BEFORE responding to the user, and do NOT batch it with later commits. Skipping this leaves the brain stale for the rest of the session."
    exit 0
fi

# ── Agent tool — detect superpowers task completion ───────────────────────────

if [ "$TOOL_NAME" = "Agent" ]; then
    ARCH_PATH=""
    CONTEXT_PATH=""
    CONCEPTS_PATH=""
    [ -n "$VAULT" ] && [ -n "$SLUG" ] && ARCH_PATH=" ($VAULT/projects/$SLUG/architecture.md)"
    [ -n "$VAULT" ] && [ -n "$SLUG" ] && CONTEXT_PATH=" ($VAULT/projects/$SLUG/context.md)"
    [ -n "$VAULT" ] && CONCEPTS_PATH=" ($VAULT/concepts/)"
    echo "Brain: subagent task completed. Check now: (1) if new patterns or conventions were discovered → add to architecture.md${ARCH_PATH} — and for each one, does it name a specific external library, named subsystem, infra component, or cross-project decision? If yes, create/update its note in concepts/${CONCEPTS_PATH} and link it, don't leave it as prose only; (2) if this completes a full feature → update context.md${CONTEXT_PATH} State + Active Work."
    exit 0
fi

# ── Skill tool — detect superpowers skill invocation ─────────────────────────

if [ "$TOOL_NAME" = "Skill" ]; then
    SKILL_NAME=$(python3 -c "
import json, sys
try:
    d = json.loads(sys.argv[1])
    print(d.get('tool_input', {}).get('skill', ''))
except:
    pass
" "$INPUT" 2>/dev/null) || true

    CONTEXT_PATH=""
    ARCH_PATH=""
    [ -n "$VAULT" ] && [ -n "$SLUG" ] && CONTEXT_PATH="$VAULT/projects/$SLUG/context.md"
    [ -n "$VAULT" ] && [ -n "$SLUG" ] && ARCH_PATH="$VAULT/projects/$SLUG/architecture.md"

    case "$SKILL_NAME" in
        *brainstorm*)
            MSG="Brain: brainstorming loaded. BEFORE asking any questions, read context.md + last log entry as Step 1 'Explore project context'"
            [ -n "$CONTEXT_PATH" ] && MSG="$MSG ($CONTEXT_PATH)"
            MSG="${MSG}. Load architecture.md before proposing approaches (Tier 2 — this is an architectural decision). When design is approved, write decisions to ## Decisions immediately."
            echo "$MSG"
            ;;
        *subagent-driven*)
            MSG="Brain: subagent-driven-development loaded. Before dispatching the first implementer, read context.md + architecture.md"
            [ -n "$CONTEXT_PATH" ] && MSG="$MSG ($CONTEXT_PATH, $ARCH_PATH)"
            MSG="${MSG}. Each implementer starts cold — no SessionStart hook fires for it. Brief it: name the vault path, tell it to read context.md/architecture.md, inline any Hard Rules or Architecture facts specific to its task, and have it report new patterns/decisions back to you in its final message (it should not write to the vault itself). After ALL tasks complete, run a full vault sync (State + Active Work + log entry) before finishing-a-development-branch. PostToolUse reminders after each Agent call are non-negotiable — act on them."
            echo "$MSG"
            ;;
        *)
            MSG="Brain: skill '$SKILL_NAME' loaded"
            [ -n "$CONTEXT_PATH" ] && MSG="${MSG}. If this session produces decisions, patterns, or completed work → update context.md ($CONTEXT_PATH) before the session ends."
            [ -z "$CONTEXT_PATH" ] && MSG="${MSG}. If this session produces decisions, patterns, or completed work → update context.md before the session ends."
            echo "$MSG"
            ;;
    esac
    exit 0
fi

# ── Read tool — count source file reads, remind to update architecture.md ─────

[ "$TOOL_NAME" = "Read" ] || exit 0

FILE_PATH=$(python3 -c "
import json, sys
try:
    d = json.loads(sys.argv[1])
    print(d.get('tool_input', {}).get('file_path', ''))
except:
    pass
" "$INPUT" 2>/dev/null) || true
[ -z "$FILE_PATH" ] && exit 0

EXT="${FILE_PATH##*.}"
case "$EXT" in
  ts|tsx|js|jsx|py|go|rs|rb|java|kt|swift|vue|svelte|c|cpp|cs|php|scala) ;;
  *) exit 0 ;;
esac

# Skip vault files
[ -n "$VAULT" ] && [[ "$FILE_PATH" == "$VAULT"* ]] && exit 0

# Per-project session counter (keyed by PID of shell session to reset per session)
SESSION_ID="${PPID:-$$}"
PROJECT_HASH=$(printf '%s' "$PWD" | md5 -q 2>/dev/null || printf '%s' "$PWD" | md5sum | cut -c1-8)
COUNTER_FILE="/tmp/brain-reads-${PROJECT_HASH}-${SESSION_ID}"
COUNT=0
[ -f "$COUNTER_FILE" ] && COUNT=$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)
COUNT=$((COUNT + 1))
echo "$COUNT" > "$COUNTER_FILE"

if [ $((COUNT % 3)) -eq 0 ] && [ "$COUNT" -le 9 ]; then
    ARCH_PATH=""
    CONCEPTS_PATH=""
    [ -n "$VAULT" ] && [ -n "$SLUG" ] && ARCH_PATH=" ($VAULT/projects/$SLUG/architecture.md)"
    [ -n "$VAULT" ] && CONCEPTS_PATH=" ($VAULT/concepts/)"
    echo "Brain: $COUNT source files read this session. Before continuing, update architecture.md${ARCH_PATH} with what you've learned. Concept check (do this now, not later): does any bullet you're about to write name a specific external library, a named subsystem, an infra component, or a decision with reach beyond this project? If yes, create or update its note in concepts/${CONCEPTS_PATH} and link it from the bullet — do not leave it as architecture.md prose only."
fi
