#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

import bot
from scrapers.db_connect import connect_odds_db as _connect_odds_db  # W81-DBLOCK


def _connect() -> sqlite3.Connection:
    bot._ensure_shadow_narratives_table()
    conn = _connect_odds_db(str(bot._NARRATIVE_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _show(match_key: str) -> int:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM shadow_narratives WHERE match_key = ? ORDER BY created_at DESC, id DESC LIMIT 1",
            (match_key,),
        ).fetchone()
        if not row:
            print(f"No shadow narrative found for {match_key}")
            return 1

        report = json.loads(row["verification_report"])
        print(f"Shadow Narrative #{row['id']} | {row['match_key']}")
        print(f"Created: {row['created_at']} | Model: {row['model']} | Richness: {row['richness_score']}")
        print(f"Verification passed: {bool(row['verification_passed'])}")
        print(f"Duration ms: {row['duration_ms']} | Tokens: {row['token_count']}")
        print("")
        print("== W82 BASELINE ==")
        print(row["w82_baseline"])
        print("")
        print("== W82 POLISHED ==")
        print(row["w82_polished"] or "(none)")
        print("")
        print("== SHADOW VERIFIED DRAFT ==")
        print(row["verified_draft"] or "(rejected)")
        print("")
        print("== SHADOW RAW DRAFT ==")
        print(row["raw_draft"])
        print("")
        print("== VERIFICATION REPORT ==")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    finally:
        conn.close()


def _stats() -> int:
    conn = _connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM shadow_narratives").fetchone()[0]
        passed = conn.execute(
            "SELECT COUNT(*) FROM shadow_narratives WHERE verification_passed = 1"
        ).fetchone()[0]
        latest = conn.execute(
            "SELECT created_at FROM shadow_narratives ORDER BY created_at DESC, id DESC LIMIT 1"
        ).fetchone()
        richness = conn.execute(
            "SELECT richness_score, COUNT(*) AS total FROM shadow_narratives GROUP BY richness_score ORDER BY richness_score"
        ).fetchall()
        scoring = conn.execute(
            "SELECT AVG(scored_quality), AVG(scored_accuracy), AVG(scored_value), COUNT(*) "
            "FROM shadow_narratives WHERE scored_quality IS NOT NULL OR scored_accuracy IS NOT NULL OR scored_value IS NOT NULL"
        ).fetchone()

        print(f"Total shadow rows: {total}")
        print(f"Hard-pass rows: {passed}")
        print(f"Hard-pass rate: {(passed / total * 100):.1f}%" if total else "Hard-pass rate: n/a")
        print(f"Latest row: {latest[0] if latest else 'n/a'}")
        print("")
        print("Richness distribution:")
        for row in richness:
            print(f"- {row['richness_score']}: {row['total']}")
        print("")
        print("Human scores:")
        print(f"- Rows scored: {scoring[3] or 0}")
        print(f"- Avg quality: {round(scoring[0], 2) if scoring[0] is not None else 'n/a'}")
        print(f"- Avg accuracy: {round(scoring[1], 2) if scoring[1] is not None else 'n/a'}")
        print(f"- Avg value: {round(scoring[2], 2) if scoring[2] is not None else 'n/a'}")
        return 0
    finally:
        conn.close()


def _score(row_id: int, quality: float | None, accuracy: float | None, value: float | None, notes: str) -> int:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE shadow_narratives SET scored_quality = ?, scored_accuracy = ?, scored_value = ?, scorer_notes = ? WHERE id = ?",
            (quality, accuracy, value, notes, row_id),
        )
        conn.commit()
        print(f"Scored shadow narrative #{row_id}")
        return 0
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect and score W84 shadow narratives")
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show", help="Show the latest shadow row for a match key")
    show.add_argument("--match-key", required=True)

    sub.add_parser("stats", help="Show aggregate shadow narrative stats")

    score = sub.add_parser("score", help="Apply human scores to a shadow row")
    score.add_argument("--id", type=int, required=True)
    score.add_argument("--quality", type=float)
    score.add_argument("--accuracy", type=float)
    score.add_argument("--value", type=float)
    score.add_argument("--notes", default="")

    args = parser.parse_args()
    if args.command == "show":
        return _show(args.match_key)
    if args.command == "stats":
        return _stats()
    if args.command == "score":
        return _score(args.id, args.quality, args.accuracy, args.value, args.notes)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
