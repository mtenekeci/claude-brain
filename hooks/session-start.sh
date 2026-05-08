#!/bin/bash
# Brain SessionStart hook — injects vault context into Claude's session before
# the first user prompt. Loads context.md (full) + last log entry on every
# session. Architecture.md is named as a Tier 2 path for on-demand loading
# only — not loaded unconditionally (can be large, rarely needed at session start).

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

if [ -f "$ARCHITECTURE" ]; then
  echo "Brain: read these files now before responding to any message:
1. $CONTEXT (full)
2. $LOG — find the last ## heading and read to end of file only

Tier 2 (load before any architectural decision or significant design choice, not upfront):
- $ARCHITECTURE (full)"
else
  echo "Brain: read these files now before responding to any message:
1. $CONTEXT (full)
2. $LOG — find the last ## heading and read to end of file only"
fi
