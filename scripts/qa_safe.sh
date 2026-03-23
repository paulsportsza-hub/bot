#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# qa_safe.sh — Bounded, serialised QA test runner
#
# Prevents QA from starving the live bot, scrapers, or pregen.
#
# Guardrails:
#   1. Exclusive flock — only ONE qa_safe run at a time
#   2. Hard wall-clock timeout (default 300s / 5 min)
#   3. nice +15 / ionice -c3 — lowest CPU/IO priority
#   4. Per-test timeout via pytest-timeout (30s default in pytest.ini)
#   5. Fail-fast (-x) by default
#
# Usage:
#   bash scripts/qa_safe.sh                      # full suite, fail-fast
#   bash scripts/qa_safe.sh contracts             # layer 1 only
#   bash scripts/qa_safe.sh edge_accuracy         # layer 2 only
#   bash scripts/qa_safe.sh accuracy              # layer 3 only
#   bash scripts/qa_safe.sh snapshots             # layer 4 only
#   bash scripts/qa_safe.sh e2e                   # layer 5 only
#   bash scripts/qa_safe.sh gate                  # wave completion gate (L1-L4)
#   bash scripts/qa_safe.sh tests/test_config.py  # specific file
#   bash scripts/qa_safe.sh -- -k "test_foo"      # pass extra pytest args after --
#
# Environment:
#   QA_TIMEOUT=600  — override wall-clock timeout (seconds)
#   QA_VERBOSE=1    — use -v instead of -q
#   QA_NO_FAILFAST=1 — disable -x (run all tests even on failure)
# ─────────────────────────────────────────────────────────────
set -euo pipefail

LOCK_FILE="/tmp/mzansiedge_qa.lock"
QA_TIMEOUT="${QA_TIMEOUT:-300}"
BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# ── Colour helpers ──────────────────────────────────────────
red()   { printf '\033[0;31m%s\033[0m\n' "$*"; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
cyan()  { printf '\033[0;36m%s\033[0m\n' "$*"; }

# ── Exclusive lock (non-blocking) ───────────────────────────
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    red "BLOCKED: Another QA run is already in progress."
    red "Lock file: $LOCK_FILE"
    red "Waiting process: $(cat "$LOCK_FILE" 2>/dev/null || echo unknown)"
    exit 1
fi
echo "$$" >&9

cleanup() {
    flock -u 9 2>/dev/null
    exec 9>&-
}
trap cleanup EXIT

# ── Activate venv ───────────────────────────────────────────
cd "$BOT_DIR"
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi

# ── Parse target ────────────────────────────────────────────
TARGET=""
EXTRA_ARGS=""

# Check for -- separator for extra pytest args
BEFORE_DASHDASH=()
AFTER_DASHDASH=()
FOUND_DASHDASH=false
for arg in "$@"; do
    if [ "$arg" = "--" ]; then
        FOUND_DASHDASH=true
        continue
    fi
    if $FOUND_DASHDASH; then
        AFTER_DASHDASH+=("$arg")
    else
        BEFORE_DASHDASH+=("$arg")
    fi
done

if [ ${#BEFORE_DASHDASH[@]} -gt 0 ]; then
    case "${BEFORE_DASHDASH[0]}" in
        contracts)      TARGET="tests/contracts/" ;;
        edge_accuracy)  TARGET="tests/edge_accuracy/" ;;
        accuracy)       TARGET="tests/accuracy/" ;;
        snapshots)      TARGET="tests/snapshots/" ;;
        e2e)            TARGET="tests/e2e/" ;;
        gate)           TARGET="tests/contracts/ tests/edge_accuracy/ tests/accuracy/ tests/snapshots/" ;;
        *)              TARGET="${BEFORE_DASHDASH[0]}" ;;
    esac
fi

# ── Build pytest command ────────────────────────────────────
PYTEST_CMD=("python" "-m" "pytest")

if [ -n "$TARGET" ]; then
    # shellcheck disable=SC2206
    PYTEST_CMD+=($TARGET)
fi

# Verbosity
if [ "${QA_VERBOSE:-0}" = "1" ]; then
    PYTEST_CMD+=("-v" "--tb=short")
else
    PYTEST_CMD+=("-q" "--tb=short")
fi

# Fail-fast
if [ "${QA_NO_FAILFAST:-0}" != "1" ]; then
    PYTEST_CMD+=("-x")
fi

# Extra args from after --
if [ ${#AFTER_DASHDASH[@]} -gt 0 ]; then
    PYTEST_CMD+=("${AFTER_DASHDASH[@]}")
fi

# ── Run with guardrails ────────────────────────────────────
cyan "═══════════════════════════════════════════════"
cyan " MzansiEdge Safe QA Runner"
cyan " $(date '+%Y-%m-%d %H:%M:%S %Z')"
cyan " Timeout: ${QA_TIMEOUT}s | Priority: nice +15 | Lock: $$"
cyan " Target: ${TARGET:-full suite}"
cyan "═══════════════════════════════════════════════"
echo ""

# nice +15 = low CPU priority, ionice -c3 = idle IO class
# timeout kills the entire process group after QA_TIMEOUT seconds
EXIT_CODE=0
timeout --kill-after=30 "$QA_TIMEOUT" \
    nice -n 15 ionice -c 3 \
    "${PYTEST_CMD[@]}" || EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    green "═══════════════════════════════════════════════"
    green " QA PASSED"
    green "═══════════════════════════════════════════════"
elif [ $EXIT_CODE -eq 124 ]; then
    red "═══════════════════════════════════════════════"
    red " QA KILLED — wall-clock timeout (${QA_TIMEOUT}s)"
    red "═══════════════════════════════════════════════"
else
    red "═══════════════════════════════════════════════"
    red " QA FAILED (exit code: $EXIT_CODE)"
    red "═══════════════════════════════════════════════"
fi

exit $EXIT_CODE
