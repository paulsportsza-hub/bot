#!/usr/bin/env bash
# db-bare-connect-check.sh — reject staged bare sqlite3.connect() calls
# outside the canonical connection helpers.
#
# The bot has TWO sanctioned helpers:
#   - bot/db_connection.py    (get_connection)
#   - scrapers/db_connect.py  (connect_odds_db, connect_odds_db_readonly, connect_db)
#
# Any other module calling sqlite3.connect() bypasses WAL + busy_timeout +
# row_factory and creates 'database is locked' on hot paths under load —
# observed live FIX-DBLOCK-CARD-GEN-DIGEST-STATS-01 (2026-05-07).
#
# Allowlist:
#   - db_connection.py / db_connect.py (helpers themselves)
#   - test_*.py / tests/ (tests construct controlled scratch DBs)
#   - URI mode=ro paths followed by busy_timeout pragma (read-only fast path)
#
# Bypass: BARE_CONNECT_BYPASS=1 (audit-trailed, reviewer-approved).

set -euo pipefail

if [ "${BARE_CONNECT_BYPASS:-0}" = "1" ]; then
    echo "[db-bare-connect-check] BYPASSED (BARE_CONNECT_BYPASS=1)" >&2
    exit 0
fi

STAGED_PY=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null \
    | grep -E '\.py$' \
    | grep -vE '(^|/)(db_connection|db_connect)\.py$' \
    | grep -vE '(^|/)tests?/' \
    | grep -vE '(^|/)test_[^/]+\.py$' \
    || true)

if [ -z "$STAGED_PY" ]; then
    exit 0
fi

VIOLATIONS=""
for f in $STAGED_PY; do
    [ -f "$f" ] || continue
    HITS=$(grep -nE 'sqlite3\.connect\(|_sqlite3\.connect\(' "$f" 2>/dev/null || true)
    if [ -z "$HITS" ]; then continue; fi
    while IFS= read -r line; do
        # Allow URI read-only mode (mode=ro) — these pair with explicit
        # busy_timeout + query_only and are safe.
        if echo "$line" | grep -q 'mode=ro'; then continue; fi
        VIOLATIONS+="$f:$line"$'\n'
    done <<< "$HITS"
done

if [ -n "$VIOLATIONS" ]; then
    echo "" >&2
    echo "ERROR: bare sqlite3.connect() detected in staged files." >&2
    echo "       Use one of the canonical helpers instead:" >&2
    echo "         - bot/db_connection.py: get_connection()" >&2
    echo "         - scrapers/db_connect.py: connect_odds_db(), connect_odds_db_readonly(), connect_db()" >&2
    echo "" >&2
    echo "       Why: bare connect() opens without WAL + busy_timeout pragmas," >&2
    echo "       causing 'database is locked' on hot paths under writer contention." >&2
    echo "       Tracked incident: FIX-DBLOCK-CARD-GEN-DIGEST-STATS-01 (2026-05-07)." >&2
    echo "" >&2
    echo "Violations:" >&2
    echo "$VIOLATIONS" | sed 's/^/  - /' >&2
    echo "" >&2
    echo "Bypass (audit-trailed): BARE_CONNECT_BYPASS=1 git commit ..." >&2
    echo "" >&2
    exit 1
fi
exit 0
