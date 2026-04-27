#!/bin/bash
OUTPUT=$(bash "$(dirname "$0")/precompact.sh")
EXPECTED="BRAIN SYNC REQUIRED: Before compacting, write session summary to log.md and update context.md. This is mandatory."

if [ "$OUTPUT" = "$EXPECTED" ]; then
  echo "PASS: precompact hook outputs correct message"
  exit 0
else
  echo "FAIL"
  echo "  Expected: $EXPECTED"
  echo "  Got:      $OUTPUT"
  exit 1
fi
