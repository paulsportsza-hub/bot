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
if [[ "${CI:-}" == "true" ]]; then
  # CI mode: skip contract tests that require the scrapers/ directory
  # (scrapers/ lives at /home/paulsportsza/scrapers/ — not part of this repo)
  # Skipped: test_canary_build, test_edge_contracts, test_founding_payment_contracts,
  #          test_sentry_lock_fix, test_shadow_verifier, test_sport_terminology,
  #          test_imports, test_db_connection, test_source_scanning
  echo "CI mode: skipping 9 scrapers-dependent contract tests"
  pytest tests/contracts/ -q --tb=short \
    --ignore=tests/contracts/test_canary_build.py \
    --ignore=tests/contracts/test_edge_contracts.py \
    --ignore=tests/contracts/test_founding_payment_contracts.py \
    --ignore=tests/contracts/test_sentry_lock_fix.py \
    --ignore=tests/contracts/test_shadow_verifier.py \
    --ignore=tests/contracts/test_sport_terminology.py \
    --ignore=tests/contracts/test_imports.py \
    --ignore=tests/contracts/test_db_connection.py \
    --ignore=tests/contracts/test_source_scanning.py
else
  pytest tests/contracts/ -q --tb=short
fi

echo ""
echo "=== STEP 3: EDGE ACCURACY TESTS ==="
if [[ "${CI:-}" == "true" ]]; then
  # CI mode: skip edge accuracy tests — all require scrapers.edge.* (server-only)
  echo "CI mode: skipping edge accuracy tests (require scrapers/ directory)"
else
  pytest tests/edge_accuracy/ -q --tb=short
fi

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
