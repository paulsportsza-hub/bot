#!/usr/bin/env python3
"""BUILD-VERDICT-QUALITY-GATE-01: Backfill verdict quality scan.

One-shot script.  Scans the entire narrative_cache for rows whose verdict
would fail the new min_verdict_quality() gate.

Actions taken:
  - Marks failing rows with quality_status = 'invalidated'  (no deletes)
  - For Gold/Diamond failing rows: writes to regen_queue so pregen picks them up
  - Logs a JSON summary of counts

Usage:
    python scripts/backfill_verdict_quality_scan.py
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BOT_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _BOT_DIR)
sys.path.insert(0, os.path.dirname(_BOT_DIR))

from config import SCRAPERS_ROOT
from narrative_spec import min_verdict_quality, _extract_verdict_text

_ODDS_DB = os.path.join(str(SCRAPERS_ROOT.parent), "scrapers", "odds.db")

log = logging.getLogger("backfill_verdict_quality_scan")
if not log.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def _get_db_path() -> str:
    if os.path.exists(_ODDS_DB):
        return _ODDS_DB
    candidates = [
        os.path.join(_BOT_DIR, "data", "odds.db"),
        os.path.join(os.path.dirname(_BOT_DIR), "scrapers", "odds.db"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return _ODDS_DB


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Add quality_status column if missing; create regen_queue if absent."""
    cols = {
        row[1] for row in conn.execute("PRAGMA table_info(narrative_cache)").fetchall()
    }
    if "quality_status" not in cols:
        conn.execute(
            "ALTER TABLE narrative_cache ADD COLUMN quality_status TEXT"
        )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS regen_queue (
            match_key TEXT PRIMARY KEY,
            edge_tier TEXT NOT NULL,
            invalidated_reason TEXT NOT NULL,
            queued_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL DEFAULT 'pending'
        )
    """)
    conn.commit()


def run_backfill(db_path: str | None = None) -> dict:
    """Scan narrative_cache and mark low-quality verdicts.

    Returns summary dict with:
        scanned, rejected, gold_rejected, bronze_rejected
    """
    path = db_path or _get_db_path()
    if not os.path.exists(path):
        log.error("backfill: DB not found at %s", path)
        return {"scanned": 0, "rejected": 0, "gold_rejected": 0, "bronze_rejected": 0}

    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    summary = {"scanned": 0, "rejected": 0, "gold_rejected": 0, "bronze_rejected": 0}

    try:
        # Ensure schema is up-to-date
        try:
            _ensure_columns(conn)
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                log.info("backfill: narrative_cache table missing — nothing to scan")
                return summary
            raise

        # Fetch all rows: match_id, narrative_html, verdict_html, edge_tier
        rows = conn.execute(
            "SELECT match_id, narrative_html, verdict_html, edge_tier "
            "FROM narrative_cache "
            "WHERE quality_status IS NULL OR quality_status != 'invalidated'"
        ).fetchall()

        log.info("backfill: scanning %d rows", len(rows))
        summary["scanned"] = len(rows)

        invalidated_keys: list[str] = []
        gold_keys: list[tuple[str, str]] = []   # (match_key, edge_tier)

        for row in rows:
            match_key = row["match_id"]
            edge_tier = (row["edge_tier"] or "bronze").lower()

            # Try verdict_html first; fall back to extracting from narrative_html
            verdict_text = (row["verdict_html"] or "").strip()
            if not verdict_text and row["narrative_html"]:
                verdict_text = _extract_verdict_text(row["narrative_html"])

            if verdict_text and not min_verdict_quality(verdict_text):
                invalidated_keys.append(match_key)
                if edge_tier in ("gold", "diamond"):
                    gold_keys.append((match_key, edge_tier))
                else:
                    summary["bronze_rejected"] += 1

        summary["rejected"] = len(invalidated_keys)
        summary["gold_rejected"] = len(gold_keys)
        summary["bronze_rejected"] = summary["rejected"] - summary["gold_rejected"]

        log.info(
            "backfill: %d rows fail quality gate (%d Gold/Diamond, %d other)",
            summary["rejected"], summary["gold_rejected"], summary["bronze_rejected"],
        )

        # Mark rows as invalidated (no delete — preserve for audit)
        if invalidated_keys:
            placeholders = ",".join("?" * len(invalidated_keys))
            conn.execute(
                f"UPDATE narrative_cache SET quality_status = 'invalidated' "
                f"WHERE match_id IN ({placeholders})",
                invalidated_keys,
            )
            log.info("backfill: marked %d rows as invalidated", len(invalidated_keys))

        # Gold/Diamond rows → regen_queue
        if gold_keys:
            for mk, tier in gold_keys:
                conn.execute(
                    "INSERT OR REPLACE INTO regen_queue "
                    "(match_key, edge_tier, invalidated_reason) VALUES (?, ?, ?)",
                    (mk, tier, "verdict_quality_gate_fail"),
                )
            log.info("backfill: queued %d Gold/Diamond rows for regen", len(gold_keys))

        conn.commit()

    except Exception as exc:
        log.exception("backfill: unexpected error: %s", exc)
    finally:
        conn.close()

    return summary


if __name__ == "__main__":
    result = run_backfill()
    print(json.dumps(result, indent=2))
    log.info("backfill complete: %s", result)
