#!/usr/bin/env python3
"""MONITOR-P0-FIX-01: Fix narrative_integrity_log.recorded_at schema.

Changes:
  1. Add fixture_id TEXT column (if not present).
  2. Backfill recorded_at from ts where recorded_at = '2000-01-01T00:00:00'
     and ts IS NOT NULL (covers rows written by the old cron monitor).
  3. For rows with recorded_at = '2000-01-01T00:00:00' and no ts, set
     recorded_at = datetime('now') as a safe fallback.

Why: _write_signal() previously omitted recorded_at, so it defaulted to
'2000-01-01T00:00:00'. This broke _debounced() — last alert time always
appeared as 2000-01-01, so every cron run fired alerts instead of debouncing.
"""
from __future__ import annotations

import os
import sys
import sqlite3

# Resolve odds.db path — run from repo root or bot dir
_HERE = os.path.dirname(os.path.abspath(__file__))
_BOT_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BOT_DIR)
sys.path.insert(0, os.path.dirname(_BOT_DIR))

try:
    from config import SCRAPERS_ROOT
    _ODDS_DB = str(SCRAPERS_ROOT / "odds.db")
except ImportError:
    _ODDS_DB = os.path.join(os.path.dirname(_BOT_DIR), "scrapers", "odds.db")


def run_migration(db_path: str | None = None) -> None:
    path = db_path or _ODDS_DB
    if not os.path.exists(path):
        print(f"[SKIP] {path} not found — nothing to migrate")
        return

    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")

    # Verify table exists
    tbl = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='narrative_integrity_log'"
    ).fetchone()
    if not tbl:
        print("[SKIP] narrative_integrity_log table does not exist yet")
        conn.close()
        return

    cols = {row[1] for row in conn.execute("PRAGMA table_info(narrative_integrity_log)").fetchall()}
    print(f"[INFO] Existing columns: {sorted(cols)}")

    with conn:
        # 1. Add fixture_id column if not present
        if "fixture_id" not in cols:
            conn.execute("ALTER TABLE narrative_integrity_log ADD COLUMN fixture_id TEXT")
            print("[ADD]  fixture_id TEXT column added")
        else:
            print("[SKIP] fixture_id column already present")

        # 2. Add details column if not present (safety — old schema has it)
        if "details" not in cols:
            conn.execute("ALTER TABLE narrative_integrity_log ADD COLUMN details TEXT")
            print("[ADD]  details TEXT column added")
        else:
            print("[SKIP] details column already present")

        # 3. Backfill recorded_at from ts (old-script rows)
        if "ts" in cols:
            result = conn.execute(
                "UPDATE narrative_integrity_log "
                "SET recorded_at = ts "
                "WHERE recorded_at = '2000-01-01T00:00:00' AND ts IS NOT NULL AND ts != ''"
            )
            print(f"[BACKFILL] {result.rowcount} rows: recorded_at <- ts")

        # 4. Set remaining stale defaults to now
        result2 = conn.execute(
            "UPDATE narrative_integrity_log "
            "SET recorded_at = datetime('now') "
            "WHERE recorded_at = '2000-01-01T00:00:00'"
        )
        if result2.rowcount:
            print(f"[BACKFILL] {result2.rowcount} rows: recorded_at <- now (no ts available)")

        # 5. Ensure index exists on (signal, recorded_at)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_nil_signal_time "
            "ON narrative_integrity_log(signal, recorded_at)"
        )
        print("[INDEX] idx_nil_signal_time ensured")

    conn.close()
    print("[DONE] Migration 0001 complete")


if __name__ == "__main__":
    run_migration()
