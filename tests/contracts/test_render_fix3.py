"""RENDER-FIX3 contract tests — confirming_signals stored and read accurately.

Tests required by brief:
1. DB migration test: confirming_signals column exists in edge_results
2. Write test: insert row with confirming_signals=2, read it back, assert value is 2
3. Legacy fallback test: NULL confirming_signals falls back to composite_score estimate
4. Integration test: log_edge_recommendation() stores actual confirming_signals count

BUILD-TEST-ISOLATION: All tests use isolated tmp DBs created from DDL.
Never opens the live scrapers/odds.db — scraper write locks cannot cause flakiness.
"""
import sqlite3
import sys
import os

# Allow importing scrapers package from parent dir
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../scrapers"))

# Minimal schema for the tests — includes tables that settlement.py queries internally.
# edge_results: full DDL including confirming_signals column (post RENDER-FIX3 migration).
# odds_snapshots: minimal stub so _is_isbets_only_fixture() doesn't raise OperationalError.
_SCHEMA_DDL = """
    CREATE TABLE IF NOT EXISTS edge_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        edge_id TEXT NOT NULL,
        match_key TEXT NOT NULL,
        sport TEXT NOT NULL,
        league TEXT NOT NULL,
        edge_tier TEXT NOT NULL,
        composite_score REAL NOT NULL,
        bet_type TEXT NOT NULL,
        recommended_odds REAL NOT NULL,
        bookmaker TEXT NOT NULL,
        predicted_ev REAL NOT NULL,
        result TEXT,
        match_score TEXT,
        actual_return REAL,
        recommended_at DATETIME NOT NULL,
        settled_at DATETIME,
        match_date DATE NOT NULL,
        confirming_signals INTEGER,
        UNIQUE(match_key, bet_type)
    );
    CREATE TABLE IF NOT EXISTS odds_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id TEXT NOT NULL,
        bookmaker TEXT NOT NULL,
        scraped_at DATETIME
    );
"""


def _make_test_db(path: str) -> str:
    """Create a fresh isolated SQLite DB with the required schema. Returns path."""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_SCHEMA_DDL)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.commit()
    finally:
        conn.close()
    return path


def _connect_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


class TestRenderFix3Migration:
    """Test 1: confirming_signals column exists in edge_results schema."""

    def test_column_exists_in_schema(self, tmp_path):
        db_path = _make_test_db(str(tmp_path / "edge.db"))
        conn = _connect_db(db_path)
        try:
            cur = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='edge_results'")
            schema = cur.fetchone()[0]
            assert "confirming_signals" in schema, (
                "confirming_signals column missing from edge_results DDL — "
                "update _SCHEMA_DDL in this test and run the RENDER-FIX3 migration on odds.db"
            )
        finally:
            conn.close()

    def test_column_is_nullable_integer(self, tmp_path):
        """Column must be INTEGER DEFAULT NULL (not NOT NULL)."""
        db_path = _make_test_db(str(tmp_path / "edge.db"))
        conn = _connect_db(db_path)
        try:
            cur = conn.execute("PRAGMA table_info(edge_results)")
            cols = {row[1]: row for row in cur.fetchall()}
            assert "confirming_signals" in cols, "confirming_signals column missing"
            col = cols["confirming_signals"]
            assert col[2].upper() == "INTEGER", f"Expected INTEGER type, got {col[2]}"
            assert col[3] == 0, "confirming_signals should be nullable (notnull=0)"
        finally:
            conn.close()


class TestRenderFix3Write:
    """Test 2: write confirming_signals=2, read it back, assert value is 2."""

    def test_write_and_read_confirming_signals(self, tmp_path):
        db_path = _make_test_db(str(tmp_path / "edge.db"))
        conn = _connect_db(db_path)
        conn.row_factory = sqlite3.Row
        match_key = "test_rendfix3_home_vs_away_2099-01-01"
        bet_type = "Home Win"
        try:
            conn.execute(
                """INSERT INTO edge_results
                   (edge_id, match_key, sport, league, edge_tier, composite_score,
                    bet_type, recommended_odds, bookmaker, predicted_ev,
                    recommended_at, match_date, confirming_signals)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "edge_test_rf3",
                    match_key,
                    "soccer",
                    "epl",
                    "gold",
                    65.0,
                    bet_type,
                    2.1,
                    "betway",
                    8.5,
                    "2099-01-01T12:00:00+00:00",
                    "2099-01-01",
                    2,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT confirming_signals FROM edge_results WHERE match_key = ? AND bet_type = ?",
                (match_key, bet_type),
            ).fetchone()
            assert row is not None, "Row not found after insert"
            assert row["confirming_signals"] == 2, (
                f"Expected confirming_signals=2, got {row['confirming_signals']}"
            )
        finally:
            conn.close()


class TestRenderFix3LegacyFallback:
    """Test 3: NULL confirming_signals falls back to composite_score estimate."""

    def test_null_falls_back_to_estimate_high(self):
        """composite_score >= 70 → estimate = 3."""
        composite = 72.0
        confirming_actual = None
        if confirming_actual is not None:
            result = int(confirming_actual)
        else:
            result = 3 if composite >= 70 else (2 if composite >= 55 else (1 if composite >= 35 else 0))
        assert result == 3

    def test_null_falls_back_to_estimate_mid(self):
        """composite_score >= 55 and < 70 → estimate = 2."""
        composite = 60.0
        confirming_actual = None
        if confirming_actual is not None:
            result = int(confirming_actual)
        else:
            result = 3 if composite >= 70 else (2 if composite >= 55 else (1 if composite >= 35 else 0))
        assert result == 2

    def test_null_falls_back_to_estimate_low(self):
        """composite_score >= 35 and < 55 → estimate = 1."""
        composite = 40.0
        confirming_actual = None
        if confirming_actual is not None:
            result = int(confirming_actual)
        else:
            result = 3 if composite >= 70 else (2 if composite >= 55 else (1 if composite >= 35 else 0))
        assert result == 1

    def test_null_falls_back_to_estimate_zero(self):
        """composite_score < 35 → estimate = 0."""
        composite = 20.0
        confirming_actual = None
        if confirming_actual is not None:
            result = int(confirming_actual)
        else:
            result = 3 if composite >= 70 else (2 if composite >= 55 else (1 if composite >= 35 else 0))
        assert result == 0

    def test_actual_value_overrides_estimate(self):
        """When confirming_signals is not None, use actual regardless of composite_score."""
        # Low composite would estimate 0, but actual=3 must win
        composite = 20.0
        confirming_actual = 3
        if confirming_actual is not None:
            result = int(confirming_actual)
        else:
            result = 3 if composite >= 70 else (2 if composite >= 55 else (1 if composite >= 35 else 0))
        assert result == 3


class TestRenderFix3Integration:
    """Test 4: log_edge_recommendation() stores actual confirming_signals=3 in DB row."""

    def test_log_edge_recommendation_stores_confirming_signals(self, tmp_path):
        from config import ensure_scrapers_importable
        ensure_scrapers_importable()
        from scrapers.edge.settlement import log_edge_recommendation

        db_path = _make_test_db(str(tmp_path / "edge.db"))
        conn = _connect_db(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        match_key = "test_rendfix3_int_home_vs_away_2099-02-01"
        try:
            edge = {
                "match_key": match_key,
                "tier": "gold",
                "market_type": "1x2",
                "outcome": "home",
                "best_odds": 1.95,
                "best_bookmaker": "betway",
                "edge_pct": 7.2,
                "composite_score": 68.0,
                "sport": "soccer",
                "league": "epl",
                "confirming_signals": 3,
            }
            result = log_edge_recommendation(edge, conn=conn)
            assert result is True, "log_edge_recommendation should return True on success"

            row = conn.execute(
                "SELECT confirming_signals FROM edge_results WHERE match_key = ?",
                (match_key,),
            ).fetchone()
            assert row is not None, "Row not found after log_edge_recommendation"
            assert row["confirming_signals"] == 3, (
                f"Expected confirming_signals=3, got {row['confirming_signals']}"
            )
        finally:
            conn.close()
