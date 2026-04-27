"""Regression guard: every edge_results row older than 1 hour has a brl row.

FIX-CORE7-CROSS-SPORT-01: log_edge_recommendation() was overwriting edge_id on
every UPDATE, breaking the FK link to any existing bet_recommendations_log row.
Then _blw_fire_tips' in-memory dedup skipped the re-write, leaving orphans.

If this test fails:
  - edge_results rows are accumulating without brl rows
  - CLV / closing-line calibration data is being permanently lost
  - The write-site fix (preserve edge_id on UPDATE) has been reverted
"""

import os
import sys
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
_SCRAPERS = os.path.join(_ROOT, "scrapers")
for _p in [_SCRAPERS, _ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

DB_PATH = os.path.join(_SCRAPERS, "odds.db")


def _get_conn():
    import sqlite3
    from scrapers.db_connect import connect_odds_db
    conn = connect_odds_db(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def test_no_orphan_edges_older_than_1h():
    """No edge_results row older than 1 hour may lack a bet_recommendations_log row."""
    if not os.path.exists(DB_PATH):
        pytest.skip("odds.db not present in test environment")

    conn = _get_conn()
    try:
        orphans = conn.execute("""
            SELECT er.edge_id, er.match_key, er.sport, er.recommended_at
            FROM edge_results er
            LEFT JOIN bet_recommendations_log brl ON brl.edge_id = er.edge_id
            WHERE er.recommended_at < datetime('now', '-1 hour')
              AND er.result IS NULL
              AND brl.id IS NULL
            ORDER BY er.recommended_at DESC
            LIMIT 20
        """).fetchall()
    finally:
        conn.close()

    orphan_details = [
        f"{r['edge_id']} | {r['sport']} | {r['recommended_at']}"
        for r in orphans
    ]

    assert len(orphans) == 0, (
        f"Found {len(orphans)} edge_results row(s) older than 1h with no brl row. "
        "Root cause: log_edge_recommendation() UPDATE must NOT overwrite edge_id "
        "(breaks FK link). Fix: remove 'SET edge_id = ?' from the UPDATE statement.\n\n"
        "Orphans:\n" + "\n".join(orphan_details)
    )


def test_edge_id_stable_across_updates():
    """Verify log_edge_recommendation does not overwrite edge_id on repeat calls."""
    if not os.path.exists(DB_PATH):
        pytest.skip("odds.db not present in test environment")

    import sqlite3
    from scrapers.db_connect import connect_odds_db
    from scrapers.edge.settlement import log_edge_recommendation

    # Use an isolated in-memory-style DB to avoid touching live data
    tmp_db = DB_PATH + ".test_stable_edge_id.tmp"
    conn = None
    try:
        conn = connect_odds_db(tmp_db)
        conn.row_factory = sqlite3.Row

        # Ensure tables exist (settlement + odds_snapshots for ISBets guard)
        from scrapers.edge.settlement import _ensure_table
        _ensure_table(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS odds_snapshots (
                id INTEGER PRIMARY KEY, match_id TEXT, bookmaker TEXT,
                scraped_at DATETIME DEFAULT (datetime('now'))
            )
        """)
        conn.commit()

        fake_edge = {
            "match_key": "test_home_vs_test_away_2099-01-01",
            "tier": "silver",
            "edge_pct": 5.0,
            "best_odds": 2.10,
            "best_bookmaker": "testbook",
            "composite_score": 60.0,
            "outcome": "home",
            "market_type": "1x2",
            "sport": "soccer",
            "league": "epl",
            "confirming_signals": 3,
        }

        # First write — creates the row
        log_edge_recommendation(fake_edge, conn)
        conn.commit()

        row1 = conn.execute(
            "SELECT edge_id FROM edge_results WHERE match_key = ? AND result IS NULL",
            (fake_edge["match_key"],)
        ).fetchone()
        assert row1, "First log_edge_recommendation call must create a row"
        edge_id_first = row1["edge_id"]

        # Second write (simulated refresh) — must preserve edge_id
        log_edge_recommendation(fake_edge, conn)
        conn.commit()

        row2 = conn.execute(
            "SELECT edge_id FROM edge_results WHERE match_key = ? AND result IS NULL",
            (fake_edge["match_key"],)
        ).fetchone()
        assert row2, "Row must still exist after second call"
        edge_id_second = row2["edge_id"]

        assert edge_id_first == edge_id_second, (
            f"edge_id changed on UPDATE: '{edge_id_first}' → '{edge_id_second}'. "
            "log_edge_recommendation must preserve edge_id on UPDATE to keep brl FK stable."
        )
    finally:
        if conn is not None:
            conn.close()
        if os.path.exists(tmp_db):
            os.remove(tmp_db)
        for ext in ["-wal", "-shm"]:
            p = tmp_db + ext
            if os.path.exists(p):
                os.remove(p)
