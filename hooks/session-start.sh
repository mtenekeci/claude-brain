#!/bin/bash
# Brain SessionStart hook — injects vault content (not just paths) directly into
# Claude's context before the first user prompt. Emits:
#   - Full context.md
#   - Last log entry (from final ## heading to EOF)
# This guarantees the answer to "what's next / what's the current state" is
# already in context before Claude responds — no Read step Claude can skip.
# Architecture.md is named as a Tier 2 path for on-demand loading only.

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

echo "Brain: vault context for this project is injected below. Treat it as authoritative — when its content answers a question (current state, what's next, recent decisions), use it directly instead of asking the user or re-reading source files."
echo
echo "═══════════════════════════════════════════════════════════════"
echo "VAULT FILE: $CONTEXT"
echo "═══════════════════════════════════════════════════════════════"
cat "$CONTEXT"

if [ -f "$LOG" ]; then
    LAST_ENTRY=$(awk '
        /^## / { start = NR; buf = $0; next }
        start { buf = buf "\n" $0 }
        END { if (start) print buf }
    ' "$LOG")
    if [ -n "$LAST_ENTRY" ]; then
        echo
        echo "═══════════════════════════════════════════════════════════════"
        echo "VAULT FILE: $LOG (last entry only)"
        echo "═══════════════════════════════════════════════════════════════"
        echo "$LAST_ENTRY"
    fi
fi

if [ -f "$ARCHITECTURE" ]; then
    echo
    echo "═══════════════════════════════════════════════════════════════"
    echo "Tier 2 (load before any architectural decision, not upfront):"
    echo "  $ARCHITECTURE"
    echo "═══════════════════════════════════════════════════════════════"
fi
