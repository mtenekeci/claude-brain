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

    echo "$CMD" | grep -qE "git commit" || exit 0

    CONTEXT_PATH=""
    [ -n "$VAULT" ] && [ -n "$SLUG" ] && CONTEXT_PATH=" ($VAULT/projects/$SLUG/context.md)"
    echo "Brain: git commit detected. Before your next response, update context.md ## State and ## Active Work${CONTEXT_PATH} to reflect what just changed. Do not wait for /brain sync."
    exit 0
fi

# ── Agent tool — detect superpowers task completion ───────────────────────────

if [ "$TOOL_NAME" = "Agent" ]; then
    ARCH_PATH=""
    CONTEXT_PATH=""
    [ -n "$VAULT" ] && [ -n "$SLUG" ] && ARCH_PATH=" ($VAULT/projects/$SLUG/architecture.md)"
    [ -n "$VAULT" ] && [ -n "$SLUG" ] && CONTEXT_PATH=" ($VAULT/projects/$SLUG/context.md)"
    echo "Brain: subagent task completed. Check now: (1) if new patterns or conventions were discovered → add to architecture.md${ARCH_PATH}; (2) if this completes a full feature → update context.md${CONTEXT_PATH} State + Active Work."
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
    [ -n "$VAULT" ] && [ -n "$SLUG" ] && ARCH_PATH=" ($VAULT/projects/$SLUG/architecture.md)"
    echo "Brain: $COUNT source files read this session. Before continuing, update architecture.md${ARCH_PATH} with what you've learned — so future sessions don't re-read these files."
fi
