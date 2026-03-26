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
pytest tests/contracts/ -q --tb=short

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
