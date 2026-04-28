#!/usr/bin/env bash
# OPS-CANONICAL-LANE-COMMIT-DISCIPLINE-01 — pre-commit canonical-lane discipline check.
#
# Rejects commits that co-stage files under static/qa-gallery/canonical/ alongside
# files outside that path. Per CLAUDE.md "Canonical QA Gallery — Hand-Curated, Do
# Not Touch" lock: canonical writes are atomic-commit-only.
#
# Usage:
#   canonical_lane_check.sh                       # reads `git diff --cached --name-only` (hook mode)
#   canonical_lane_check.sh path1 path2 ...       # arg-list mode (test mode)
#   echo "path1\npath2" | canonical_lane_check.sh -    # stdin mode
#
# Exit codes:
#   0 — clean (no mixed staging)
#   1 — mixed staging detected, commit must abort
#
# Emergency override: ALLOW_CANONICAL_MIX=1 bypasses with a warning. Use only
# for audited recovery commits and document the reason in the commit message.

set -euo pipefail

CANONICAL_PREFIX="static/qa-gallery/canonical/"

if [ "$#" -eq 0 ]; then
    STAGED=$(git diff --cached --name-only --diff-filter=ACMRD 2>/dev/null || true)
elif [ "$1" = "-" ]; then
    STAGED=$(cat)
else
    STAGED=$(printf '%s\n' "$@")
fi

# Strip empty lines.
STAGED=$(printf '%s\n' "$STAGED" | grep -v '^$' || true)

if [ -z "$STAGED" ]; then
    exit 0
fi

CANONICAL_HITS=$(printf '%s\n' "$STAGED" | grep -E "^${CANONICAL_PREFIX}" || true)
OTHER_HITS=$(printf '%s\n' "$STAGED" | grep -vE "^${CANONICAL_PREFIX}" || true)

if [ -n "$CANONICAL_HITS" ] && [ -n "$OTHER_HITS" ]; then
    if [ "${ALLOW_CANONICAL_MIX:-0}" = "1" ]; then
        echo "WARNING: ALLOW_CANONICAL_MIX=1 — mixed staging permitted (audited override)" >&2
        echo "  Canonical files in commit:" >&2
        printf '%s\n' "$CANONICAL_HITS" | sed 's/^/    /' >&2
        echo "  Non-canonical files in commit:" >&2
        printf '%s\n' "$OTHER_HITS" | sed 's/^/    /' >&2
        exit 0
    fi
    {
        echo ""
        echo "ERROR: Canonical lane discipline violation — mixed staging."
        echo ""
        echo "  Per CLAUDE.md (LOCKED 28 Apr 2026, OPS-CANONICAL-LANE-COMMIT-DISCIPLINE-01):"
        echo "  Canonical writes (static/qa-gallery/canonical/) must be atomic-commit-only."
        echo "  A single commit must contain EITHER canonical/ files OR non-canonical/ files —"
        echo "  never both. Cross-lane staging caused 2 incidents in 2 days; the hook closes"
        echo "  the race surface."
        echo ""
        echo "  Canonical files staged:"
        printf '%s\n' "$CANONICAL_HITS" | sed 's/^/    /'
        echo ""
        echo "  Non-canonical files staged:"
        printf '%s\n' "$OTHER_HITS" | sed 's/^/    /'
        echo ""
        echo "  Resolution:"
        echo "    git restore --staged static/qa-gallery/canonical/   # unstage all canonical"
        echo "    git restore --staged <path>                          # unstage a single file"
        echo "    ALLOW_CANONICAL_MIX=1 git commit ...                 # emergency override (audited)"
        echo ""
        echo "  Brief: OPS-CANONICAL-LANE-COMMIT-DISCIPLINE-01"
        echo ""
    } >&2
    exit 1
fi

exit 0
