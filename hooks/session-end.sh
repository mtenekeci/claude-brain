#!/bin/bash
# Brain SessionEnd hook — writes a session marker enriched with git context
# when the session ends without a manual /brain sync.
# The next /brain sync overwrites this entry with real content.

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

tail -10 "$LOG" | grep -q "(auto-close)" && exit 0

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

printf "\n## %s · Session %d (auto-close)\nCompleted: Session ended without sync — run /brain sync to record details\nChanged: %s\nDecided: none\nNext: —\n" \
  "$DATE" "$((N+1))" "$CHANGED" >> "$LOG"
