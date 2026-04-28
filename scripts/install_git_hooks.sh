#!/usr/bin/env bash
# OPS-CANONICAL-LANE-COMMIT-DISCIPLINE-01 — one-time setup helper for tracked git hooks.
#
# Sets `git config core.hooksPath .githooks` so the in-repo `.githooks/` directory
# becomes the active hooks path for this clone. Run once after a fresh clone.
#
# Idempotent: safe to re-run.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

if [ ! -d .githooks ]; then
    echo "ERROR: .githooks/ directory not found at $REPO_ROOT" >&2
    echo "Run this script from the bot repository root." >&2
    exit 1
fi

CURRENT=$(git config --get core.hooksPath || echo "")
if [ "$CURRENT" = ".githooks" ]; then
    echo "core.hooksPath is already set to .githooks — no change."
else
    git config core.hooksPath .githooks
    echo "Set core.hooksPath = .githooks (was: ${CURRENT:-default})"
fi

# Ensure all tracked hooks are executable.
for hook in .githooks/*; do
    if [ -f "$hook" ] && [ ! -x "$hook" ]; then
        chmod +x "$hook"
        echo "Made executable: $hook"
    fi
done

echo ""
echo "Tracked hooks active for this clone. Test with:"
echo "  bash scripts/canonical_lane_check.sh README.md static/qa-gallery/canonical/foo.png"
echo "  (should exit 1 with mixed-staging error)"
