#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Activate venv if available
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi

echo "========================================"
echo "  PRE-MERGE GATE — $(date -Is)"
echo "========================================"

echo ""
echo "=== STEP 1: ENV GUARD (full) ==="
./scripts/env_guard.sh --full

echo ""
echo "=== STEP 2: CONTRACT TESTS ==="
# Collect tracked + staged test files only — keeps untracked WIP from parallel
# agent sessions out of the gate. INV-PRE-MERGE-GATE-INTEGRITY-01 (G2).
TRACKED_CONTRACTS=$(git ls-files tests/contracts/ -- 'tests/contracts/test_*.py' 2>/dev/null)
STAGED_CONTRACTS=$(git diff --cached --name-only --diff-filter=A 2>/dev/null \
                   | grep -E '^tests/contracts/test_.*\.py$' || true)
SCOPED=$(printf '%s\n%s\n' "$TRACKED_CONTRACTS" "$STAGED_CONTRACTS" | sort -u | grep -v '^$' || true)

if [ -z "$SCOPED" ]; then
  echo "No tracked or staged contract tests — skipping Step 2."
else
  pytest $SCOPED -q --tb=short -rs
fi

echo ""
echo "=== STEP 3: EDGE ACCURACY TESTS ==="
pytest tests/edge_accuracy/ -q --tb=short

echo ""
# === STEP 4: ACCURACY TESTS ===
# SKIPPED: tests/accuracy/ is empty (only __init__.py). Re-enable when accuracy tests are added.
# pytest tests/accuracy/ -q --tb=short

echo ""
echo "=== STEP 5: SNAPSHOT TESTS ==="
pytest tests/snapshots/ -q --tb=short

echo ""
echo "=== STEP 6: E2E JOURNEYS ==="
pytest tests/e2e/ -q --tb=short

echo ""
echo "========================================"
echo "  PRE-MERGE GATE PASSED"
echo "========================================"
