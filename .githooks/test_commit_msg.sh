#!/bin/bash
# Regression tests for .githooks/commit-msg — run manually with:
#   bash .githooks/test_commit_msg.sh

HOOK="$(dirname "$0")/commit-msg"
PASS=0
FAIL=0

check() {
  desc="$1"
  message="$2"
  expect="$3"  # "block" or "allow"

  tmpfile=$(mktemp)
  printf '%s\n' "$message" > "$tmpfile"
  sh "$HOOK" "$tmpfile" >/dev/null 2>&1
  result=$?
  rm -f "$tmpfile"

  if [ "$expect" = "block" ] && [ "$result" -ne 0 ]; then
    echo "PASS: $desc (blocked)"
    PASS=$((PASS + 1))
  elif [ "$expect" = "allow" ] && [ "$result" -eq 0 ]; then
    echo "PASS: $desc (allowed)"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $desc (expected $expect, hook exit code was $result)"
    FAIL=$((FAIL + 1))
  fi
}

# Known bot trailer forms that must be blocked
check "Claude Code trailer" "fix: thing

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>" block

check "ChatGPT trailer" "fix: thing

Co-Authored-By: ChatGPT <noreply@openai.com>" block

check "Copilot with copilot@github.com" "fix: thing

Co-Authored-By: Copilot <copilot@github.com>" block

check "Copilot with numeric noreply address" "fix: thing

Co-Authored-By: Copilot <223556219+Copilot@users.noreply.github.com>" block

check "GitHub Copilot display name" "fix: thing

Co-Authored-By: GitHub Copilot <noreply@github.com>" block

# Legitimate human co-authors must be allowed, including at AI company domains
check "human co-author, generic domain" "fix: thing

Co-Authored-By: Jane Human <jane@example.com>" allow

check "human co-author at anthropic.com" "fix: thing

Co-Authored-By: Jane Human <jane@anthropic.com>" allow

check "human co-author at openai.com" "fix: thing

Co-Authored-By: Jane Human <jane@openai.com>" allow

check "no trailer at all" "fix: thing

Just a normal commit message." allow

echo ""
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
