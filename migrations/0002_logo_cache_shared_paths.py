#!/usr/bin/env python3
"""FIX-LOGO-CACHE-RELATIVE-PATHS-01: Rewrite logo_cache file_path to shared volume.

Rewrites file_path values that start with /home/paulsportsza/bot/card_assets/
to /home/paulsportsza/bot-data-shared/card_assets/.

Idempotent: rows already pointing to bot-data-shared are left unchanged.
Rollback: re-run with OLD_PREFIX / NEW_PREFIX swapped.

Usage:
    python3 migrations/0002_logo_cache_shared_paths.py [db_path]

If db_path is omitted, defaults to bot/data/logo_cache.db.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BOT_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BOT_DIR)

from db_connection import get_connection  # noqa: E402

_OLD_PREFIX = "/home/paulsportsza/bot/card_assets/"
_NEW_PREFIX = "/home/paulsportsza/bot-data-shared/card_assets/"


def run_migration(db_path: str | None = None) -> int:
    """Rewrite logo_cache rows. Returns the count of rows updated."""
    path = db_path or os.path.join(_BOT_DIR, "data", "logo_cache.db")
    if not os.path.exists(path):
        print(f"[SKIP] {path} not found — nothing to migrate")
        return 0

    conn = get_connection(db_path=path)

    tbl = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='logo_cache'"
    ).fetchone()
    if not tbl:
        print("[SKIP] logo_cache table does not exist")
        conn.close()
        return 0

    # Use SUBSTR to replace only the prefix — avoids doubling if run twice,
    # because the LIKE guard only matches the old prefix.
    with conn:
        result = conn.execute(
            "UPDATE logo_cache "
            "SET file_path = ? || SUBSTR(file_path, ?) "
            "WHERE file_path LIKE ?",
            (_NEW_PREFIX, len(_OLD_PREFIX) + 1, _OLD_PREFIX + "%"),
        )
        updated = result.rowcount

    conn.close()
    print(f"[UPDATE] {updated} row(s) rewritten: {_OLD_PREFIX!r} → {_NEW_PREFIX!r}")

    # Post-run verification: warn on ok-status rows whose file does not exist on disk.
    conn2 = get_connection(db_path=path)
    missing_rows = conn2.execute(
        "SELECT team_key, file_path FROM logo_cache WHERE status = 'ok' AND file_path IS NOT NULL"
    ).fetchall()
    conn2.close()
    missing_files = [r[0] for r in missing_rows if not os.path.exists(r[1])]
    if missing_files:
        print(f"[WARN]   {len(missing_files)} ok row(s) have missing files on disk: {missing_files}")
        print(f"[WARN]   Copy logo files to {_NEW_PREFIX!r} before this migration is considered complete.")
    else:
        print(f"[OK]     All {len(missing_rows)} ok-status files verified on disk.")

    print(f"[DONE]   Migration 0002 complete on {path}")
    return updated


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else None
    run_migration(db)
