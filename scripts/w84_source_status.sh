#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# w84_source_status.sh — Quick W84/W82 source verification snapshot
#
# Usage:
#   bash scripts/w84_source_status.sh
#   bash scripts/w84_source_status.sh --hours 12 --min-recent 5
#   bash scripts/w84_source_status.sh --enforce
# ─────────────────────────────────────────────────────────────
set -euo pipefail

DB_PATH="${ODDS_DB_PATH:-${MZANSI_DB_PATH:-/home/paulsportsza/scrapers/odds.db}}"
LOG_PATH="${BOT_LOG_PATH:-/tmp/bot_latest.log}"
HOURS=12
MIN_RECENT=5
ENFORCE=0

while [ $# -gt 0 ]; do
    case "$1" in
        --db)
            DB_PATH="$2"
            shift 2
            ;;
        --log)
            LOG_PATH="$2"
            shift 2
            ;;
        --hours)
            HOURS="$2"
            shift 2
            ;;
        --min-recent)
            MIN_RECENT="$2"
            shift 2
            ;;
        --enforce)
            ENFORCE=1
            shift
            ;;
        -h|--help)
            echo "Usage: bash scripts/w84_source_status.sh [--db PATH] [--log PATH] [--hours N] [--min-recent N] [--enforce]"
            exit 0
            ;;
        *)
            echo "Unknown arg: $1" >&2
            exit 2
            ;;
    esac
done

python3 - "$DB_PATH" "$LOG_PATH" "$HOURS" "$MIN_RECENT" "$ENFORCE" <<'PY'
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

db_path = Path(sys.argv[1])
log_path = Path(sys.argv[2])
hours = int(sys.argv[3])
min_recent = int(sys.argv[4])
enforce = int(sys.argv[5])

print("══════════════════════════════════════════")
print(" W84 Source Status")
print("══════════════════════════════════════════")
print(f"DB:  {db_path}")
print(f"Log: {log_path}")

if not db_path.exists():
    print("FAIL: DB file missing")
    raise SystemExit(1 if enforce else 0)

conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

def scalar(sql: str, params: tuple = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    if not row:
        return 0
    value = row[0]
    return int(value or 0)

total_cache = scalar("SELECT COUNT(*) FROM narrative_cache")
recent_total = scalar(
    "SELECT COUNT(*) FROM narrative_cache WHERE created_at >= datetime('now', ?)",
    (f"-{hours} hours",),
)
recent_w84 = scalar(
    "SELECT COUNT(*) FROM narrative_cache WHERE narrative_source = 'w84' AND created_at >= datetime('now', ?)",
    (f"-{hours} hours",),
)
recent_w82 = scalar(
    "SELECT COUNT(*) FROM narrative_cache WHERE narrative_source = 'w82' AND created_at >= datetime('now', ?)",
    (f"-{hours} hours",),
)
shadow_recent = scalar(
    "SELECT COUNT(*) FROM shadow_narratives WHERE created_at >= datetime('now', ?)",
    (f"-{hours} hours",),
)
shadow_pass = scalar(
    "SELECT COUNT(*) FROM shadow_narratives WHERE verification_passed = 1 AND created_at >= datetime('now', ?)",
    (f"-{hours} hours",),
)

latest_rows = conn.execute(
    "SELECT created_at, narrative_source, model, match_id "
    "FROM narrative_cache ORDER BY created_at DESC LIMIT 5"
).fetchall()
conn.close()

verify_fail = 0
w84_error = 0
if log_path.exists():
    tail = log_path.read_text(errors="replace").splitlines()[-2000:]
    verify_fail = sum("W84 VERIFY FAIL" in line for line in tail)
    w84_error = sum("W84 ERROR" in line for line in tail)

print(f"Cache rows total: {total_cache}")
print(f"Recent window: last {hours}h")
print(f"Recent source counts: w84={recent_w84} | w82={recent_w82} | total={recent_total}")
if shadow_recent:
    rate = (shadow_pass / shadow_recent) * 100.0
    print(f"Recent shadow verify: pass={shadow_pass}/{shadow_recent} ({rate:.0f}%)")
else:
    print("Recent shadow verify: no recent shadow rows")
print(f"Recent log markers: W84 VERIFY FAIL={verify_fail} | W84 ERROR={w84_error}")

print("Latest cache rows:")
if latest_rows:
    for row in latest_rows:
        print(
            f"  {row['created_at']} | {row['narrative_source']} | "
            f"{row['model']} | {row['match_id']}"
        )
else:
    print("  (none)")

unsafe = False
if recent_total >= min_recent and recent_w84 == 0:
    print(f"FAIL: recent cache volume >= {min_recent}, but W84 served count is zero")
    unsafe = True
elif recent_total == 0:
    print("WARN: no recent cache rows in the inspection window")
else:
    print("OK: W84 source presence detected in recent cache window")

if verify_fail or w84_error:
    print("WARN: recent W84 verify/error markers present in bot log")

if enforce and unsafe:
    raise SystemExit(1)
PY
