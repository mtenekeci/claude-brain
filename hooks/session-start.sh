#!/bin/bash
# Brain SessionStart hook — injects vault file paths into Claude's context
# before the first user prompt. Claude reads these files before responding.

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

CONTEXT="$VAULT/projects/$SLUG/context.md"
ARCHITECTURE="$VAULT/projects/$SLUG/architecture.md"
LOG="$VAULT/projects/$SLUG/log.md"

[ -f "$CONTEXT" ] || exit 0

# Check if architecture.md exists — not all projects have it yet
if [ -f "$ARCHITECTURE" ]; then
  echo "Brain: read these files now before responding to any message:
1. $CONTEXT (full)
2. $ARCHITECTURE (full)
3. $LOG — find the last ## heading and read to end of file only"
else
  echo "Brain: read these files now before responding to any message:
1. $CONTEXT (full)
2. $LOG — find the last ## heading and read to end of file only"
fi
