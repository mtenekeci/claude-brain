#!/bin/bash
# Brain SessionEnd hook — writes a minimal session marker when the session
# ends without a manual /brain sync. The next /brain sync overwrites this
# entry with real content.

set -euo pipefail

# Read vault path from brain.config
VAULT=$(python3 - <<'PY'
import json, os
cfg = os.path.expanduser("~/.claude/brain.config")
if os.path.exists(cfg):
    print(json.load(open(cfg))["vault"])
PY
2>/dev/null) || true
[ -z "$VAULT" ] && exit 0

# Read slug from CLAUDE.md in current working directory
SLUG=$(awk -F'/' '/^vault:/{print $NF}' CLAUDE.md 2>/dev/null | tr -d '[:space:]') || true
[ -z "$SLUG" ] && exit 0

LOG="$VAULT/projects/$SLUG/log.md"
[ -f "$LOG" ] || exit 0

# Skip if last entry is already an auto-close (prevent duplicates)
tail -10 "$LOG" | grep -q "(auto-close)" && exit 0

N=$(grep -c "^## " "$LOG" 2>/dev/null || echo "0")
DATE=$(date +%Y-%m-%d)

printf "\n## %s · Session %d (auto-close)\nCompleted: Session ended without sync — run /brain sync to record details\nChanged: —\nDecided: none\nNext: —\n" \
  "$DATE" "$((N+1))" >> "$LOG"
