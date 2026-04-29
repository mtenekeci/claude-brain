#!/bin/bash
# Brain PreCompact hook — writes a git-enriched checkpoint entry, then tells
# Claude to fill in Completed and Decided with session knowledge.
# Degrades gracefully if Claude doesn't act — git context is still useful.

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
  echo "BRAIN SYNC: Update log.md and context.md before compacting."
  exit 0
fi

LOG="$VAULT/projects/$SLUG/log.md"
if [ ! -f "$LOG" ]; then
  echo "BRAIN SYNC: Update log.md and context.md before compacting."
  exit 0
fi

# If last entry is already a checkpoint or auto-close, just ask Claude to enrich it
if tail -10 "$LOG" | grep -q "(pre-compact\|auto-close)"; then
  echo "BRAIN SYNC: Checkpoint already in log.md — update Completed and Decided fields with real session details, then update context.md."
  exit 0
fi

# Collect changed files: committed today + currently modified
TODAY=$(date +%Y-%m-%d)
COMMITTED=$(git log --since="$TODAY 00:00" --name-only --format="" 2>/dev/null \
  | grep -v "^$" | sort -u | head -8) || true
MODIFIED=$(git status --short 2>/dev/null | awk '{print $2}' | head -5) || true
CHANGED=$(printf "%s\n%s" "$COMMITTED" "$MODIFIED" \
  | grep -v "^$" | sort -u | tr '\n' ' ' | sed 's/ $//' | head -c 200) || true
[ -z "$CHANGED" ] && CHANGED="—"

N=$(grep -c "^## " "$LOG" 2>/dev/null || echo "0")
DATE=$TODAY

printf "\n## %s · Session %d (pre-compact)\nCompleted: —\nChanged: %s\nDecided: none\nNext: —\n" \
  "$DATE" "$((N+1))" "$CHANGED" >> "$LOG"

echo "BRAIN SYNC: Checkpoint written to log.md (Session $((N+1))) with git context. NOW update: (1) Completed — what was accomplished, (2) Decided — any decisions made, (3) context.md State and Active Work. Do this before the compact proceeds."
