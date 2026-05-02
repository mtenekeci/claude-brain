#!/bin/bash
set -euo pipefail

PLUGIN_JSON=".claude-plugin/plugin.json"

current=$(python3 -c "import json; print(json.load(open('$PLUGIN_JSON'))['version'])")
echo "Current version: $current"

IFS='.' read -r major minor patch <<< "$current"
default_next="$major.$minor.$((patch + 1))"

read -rp "New version [$default_next]: " next
next="${next:-$default_next}"

# Validate semver format
if ! [[ "$next" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Invalid version: $next" >&2
  exit 1
fi

# Bump version in plugin.json
python3 - <<PY
import json
with open("$PLUGIN_JSON") as f:
    d = json.load(f)
d["version"] = "$next"
with open("$PLUGIN_JSON", "w") as f:
    json.dump(d, f, indent=2)
    f.write("\n")
PY

git add "$PLUGIN_JSON"
git commit -m "release: v$next"
git tag "v$next"

echo ""
echo "Tagged v$next. To publish:"
echo "  git push && git push --tags"
echo ""
echo "Users update with: /plugin update brain"
