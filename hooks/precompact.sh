#!/bin/bash
# Brain PreCompact hook — writes a checkpoint entry to log.md via bash
# (guaranteed before compact), then tells Claude to fill it in with real content.

set -euo pipefail

VAULT=$(python3 - <<'PY'
import json, os
cfg = os.path.expanduser("~/.claude/brain.config")
if os.path.exists(cfg):
    print(json.load(open(cfg))["vault"])
PY
2>/dev/null) || true

SLUG=$(awk -F'/' '/^vault:/{print $NF}' CLAUDE.md 2>/dev/null | tr -d '[:space:]') || true

if [ -z "$VAULT" ] || [ -z "$SLUG" ]; then
  echo "BRAIN SYNC REQUIRED: Write session summary to log.md and update context.md before compacting."
  exit 0
fi

LOG="$VAULT/projects/$SLUG/log.md"
if [ ! -f "$LOG" ]; then
  echo "BRAIN SYNC REQUIRED: Write session summary to log.md and update context.md before compacting."
  exit 0
fi

# If last entry is already a checkpoint or auto-close, just ask Claude to update it
if tail -10 "$LOG" | grep -q "(pre-compact\|auto-close)"; then
  echo "BRAIN SYNC: A checkpoint entry already exists in log.md. UPDATE IT NOW — replace all NEEDS_UPDATE placeholders with real session details, then update context.md."
  exit 0
fi

N=$(grep -c "^## " "$LOG" 2>/dev/null || echo "0")
DATE=$(date +%Y-%m-%d)

printf "\n## %s · Session %d (pre-compact)\nCompleted: NEEDS_UPDATE\nChanged: NEEDS_UPDATE\nDecided: NEEDS_UPDATE\nNext: NEEDS_UPDATE\n" \
  "$DATE" "$((N+1))" >> "$LOG"

echo "BRAIN SYNC: Checkpoint written to $LOG as Session $((N+1)). FILL IT IN NOW — replace every NEEDS_UPDATE with real session details. Then update context.md State and Active Work sections. Do this before the compact proceeds."
