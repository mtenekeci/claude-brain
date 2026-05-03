#!/bin/bash
# Brain PostToolUse hook — counts source file reads per session and reminds
# Claude to update vault Architecture after every 3 source files read.
# Counter resets daily per project.

set -euo pipefail

# Parse tool info from stdin
INPUT=$(cat)

TOOL_NAME=$(python3 -c "
import json, sys
try:
    d = json.loads(sys.argv[1])
    print(d.get('tool_name', ''))
except:
    pass
" "$INPUT" 2>/dev/null) || true

# Only care about Read tool
[ "$TOOL_NAME" = "Read" ] || exit 0

# Get file path
FILE_PATH=$(python3 -c "
import json, sys
try:
    d = json.loads(sys.argv[1])
    print(d.get('tool_input', {}).get('file_path', ''))
except:
    pass
" "$INPUT" 2>/dev/null) || true
[ -z "$FILE_PATH" ] && exit 0

# Only count source files
EXT="${FILE_PATH##*.}"
case "$EXT" in
  ts|tsx|js|jsx|py|go|rs|rb|java|kt|swift|vue|svelte|c|cpp|cs|php|scala) ;;
  *) exit 0 ;;
esac

# Skip vault files
VAULT=$(python3 -c "
import json, os
cfg = os.path.expanduser('~/.claude/brain.config')
if os.path.exists(cfg):
    print(json.load(open(cfg))['vault'])
" 2>/dev/null) || true
[ -n "$VAULT" ] && [[ "$FILE_PATH" == "$VAULT"* ]] && exit 0

# Per-project daily counter (resets each day, stable across hook invocations)
PROJECT_HASH=$(printf '%s' "$PWD" | md5 -q 2>/dev/null || printf '%s' "$PWD" | md5sum | cut -c1-8)
COUNTER_FILE="/tmp/brain-reads-${PROJECT_HASH}-$(date +%Y%m%d)"
COUNT=0
[ -f "$COUNTER_FILE" ] && COUNT=$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)
COUNT=$((COUNT + 1))
echo "$COUNT" > "$COUNTER_FILE"

# Remind at every 3rd source file read (3, 6, 9) — cap at 9 to avoid noise
if [ $((COUNT % 3)) -eq 0 ] && [ "$COUNT" -le 9 ]; then
  SLUG=$(awk -F'/' '/^vault:/{print $NF}' CLAUDE.md 2>/dev/null | tr -d '[:space:]') || true
  CONTEXT_PATH=""
  [ -n "$VAULT" ] && [ -n "$SLUG" ] && CONTEXT_PATH=" ($VAULT/projects/$SLUG/context.md)"
  ARCH_PATH=""
  [ -n "$VAULT" ] && [ -n "$SLUG" ] && ARCH_PATH=" ($VAULT/projects/$SLUG/architecture.md)"
  echo "Brain: $COUNT source files read this session. Before continuing, update architecture.md${ARCH_PATH} with what you've learned — so future sessions don't re-read these files."
fi
