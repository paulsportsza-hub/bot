#!/usr/bin/env bash
# daily_test_suite.sh — Daily test runner with pre-flight guards.
# Fails loudly if test directory is missing or suspiciously empty.
# Usage: bash scripts/daily_test_suite.sh [extra pytest args]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_DIR="$BOT_DIR/tests"

# ── Pre-flight: test directory must exist ─────────────────────────────────
if [[ ! -d "$TEST_DIR" ]]; then
    echo "FATAL: Test directory $TEST_DIR does not exist" >&2
    exit 1
fi

# ── Pre-flight: minimum test file count ───────────────────────────────────
TEST_COUNT=$(find "$TEST_DIR" -name 'test_*.py' | wc -l)
if [[ "$TEST_COUNT" -lt 10 ]]; then
    echo "FATAL: Only $TEST_COUNT test files found in $TEST_DIR (expected 30+). Possible misconfiguration." >&2
    exit 1
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%S)] Running daily test suite ($TEST_COUNT test files found)"

# ── Run tests via safe wrapper ────────────────────────────────────────────
cd "$BOT_DIR"
bash scripts/qa_safe.sh gate "$@"

EXIT_CODE=$?
if [[ "$EXIT_CODE" -eq 0 ]]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%S)] Daily test suite PASSED"
else
    echo "[$(date -u +%Y-%m-%dT%H:%M:%S)] Daily test suite FAILED (exit $EXIT_CODE)" >&2
fi
exit "$EXIT_CODE"
