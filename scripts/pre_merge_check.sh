#!/usr/bin/env bash
# Pre-Merge Gate — Runs Testing Schema Layers 1, 2, 3.
# Merge is blocked if ANY layer fails. No exceptions.
#
# Usage:
#   bash scripts/pre_merge_check.sh
#   # Exit 0 = all pass, Exit 1 = blocked
#
# W46-INFRA — 6 March 2026

set -euo pipefail

cd "$(dirname "$0")/.."

# Activate venv if available
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi

FAILED=0

echo "═══════════════════════════════════════════════"
echo " MzansiEdge Pre-Merge Gate"
echo " $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "═══════════════════════════════════════════════"
echo ""

# ── Layer 1: Contract & Integration Tests ──
echo "▶ Layer 1: Contract & Integration Tests"
echo "─────────────────────────────────────────"
python -m pytest tests/contracts/ -v --tb=short 2>&1 || FAILED=1
echo ""

# ── Layer 2: Edge Accuracy Guards ──
echo "▶ Layer 2: Edge Accuracy Guards"
echo "─────────────────────────────────────────"
python -m pytest tests/edge_accuracy/ -v --tb=short 2>&1 || FAILED=1
echo ""

# ── Layer 3: Historical Accuracy (if exists) ──
if [ -d tests/accuracy/ ] && [ "$(find tests/accuracy/ -name 'test_*.py' | head -1)" ]; then
    echo "▶ Layer 3: Historical Accuracy"
    echo "─────────────────────────────────────────"
    python -m pytest tests/accuracy/ -v --tb=short 2>&1 || FAILED=1
    echo ""
else
    echo "▶ Layer 3: Historical Accuracy — SKIPPED (no test files yet)"
    echo ""
fi

echo "═══════════════════════════════════════════════"
if [ "$FAILED" -ne 0 ]; then
    echo " ❌ PRE-MERGE GATE: BLOCKED"
    echo " Fix failing tests before merging."
    echo "═══════════════════════════════════════════════"
    exit 1
else
    echo " ✅ PRE-MERGE GATE: PASSED"
    echo "═══════════════════════════════════════════════"
    exit 0
fi
