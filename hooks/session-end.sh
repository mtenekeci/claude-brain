#!/bin/bash
set -euo pipefail

VAULT=$(python3 - <<'PY'
import json, os
cfg = os.path.expanduser("~/.claude/brain.config")
if os.path.exists(cfg):
    print(json.load(open(cfg))["vault"])
PY
2>/dev/null) || true
[ -z "$VAULT" ] && exit 0

SLUG=$(awk -F'/' '/^vault:/{print $NF}' CLAUDE.md 2>/dev/null | tr -d '[:space:]') || true
[ -z "$SLUG" ] && exit 0

LOG="$VAULT/projects/$SLUG/log.md"
[ -f "$LOG" ] || exit 0

# Skip if already has an auto-close entry for today
tail -10 "$LOG" | grep -q "(auto-close)" && exit 0

TODAY=$(date +%Y-%m-%d)

# Build Completed line from today's commits — real signal, not a placeholder
COMMITS=$(git log --since="$TODAY 00:00" --oneline 2>/dev/null | head -5 || true)
if [ -n "$COMMITS" ]; then
    # Indent each commit line for readability in the log entry
    COMPLETED=$(printf "%s" "$COMMITS" | sed 's/^/  /')
    COMPLETED="Auto-recorded — commits today:
$COMPLETED"
else
    COMPLETED="Session ended without commits — run /brain sync to record details"
fi

# Build Changed list from committed + unstaged files
COMMITTED=$(git log --since="$TODAY 00:00" --name-only --format="" 2>/dev/null \
  | grep -v "^$" | sort -u | head -8) || true
MODIFIED=$(git status --short 2>/dev/null | awk '{print $2}' | head -5) || true
CHANGED=$(printf "%s\n%s" "$COMMITTED" "$MODIFIED" \
  | grep -v "^$" | sort -u | tr '\n' ' ' | sed 's/ $//' | head -c 200) || true
[ -z "$CHANGED" ] && CHANGED="—"

N=$(grep -c "^## " "$LOG" 2>/dev/null || echo "0")

printf "\n## %s · Session %d (auto-close)\nCompleted: %s\nChanged: %s\nDecided: none\nNext: —\n" \
  "$TODAY" "$((N+1))" "$COMPLETED" "$CHANGED" >> "$LOG"
