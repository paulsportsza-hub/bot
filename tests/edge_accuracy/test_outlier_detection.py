"""Layer 2.4 — Outlier detection guards.

MAD-based outlier detection catches divergent bookmaker odds.
Outliers should be excluded from EV calculation.
"""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ODDS_DB_PATH, ensure_scrapers_importable
ensure_scrapers_importable()

from scrapers.odds_integrity import (
    detect_outlier_odds,
    MAX_SINGLE_BOOKMAKER_DEVIATION,
)

DB_PATH = str(ODDS_DB_PATH)


def _get_sample_match_ids(limit=5):
    """Get sample match_ids from odds_latest for testing."""
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT DISTINCT match_id FROM odds_latest WHERE market_type='1x2' LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []


class TestOutlierDetection:
    """detect_outlier_odds() correctly identifies statistical outliers."""

    def test_returns_list(self):
        """detect_outlier_odds must return a list."""
        match_ids = _get_sample_match_ids(1)
        if not match_ids:
            pytest.skip("No matches in odds_latest")

        result = detect_outlier_odds(match_ids[0])
        assert isinstance(result, list), (
            f"detect_outlier_odds should return list, got {type(result)}"
        )

    def test_outlier_dict_shape(self):
        """Each outlier dict must have required keys."""
        match_ids = _get_sample_match_ids(10)
        if not match_ids:
            pytest.skip("No matches in odds_latest")

        required_keys = {"bookmaker", "selection", "odds", "consensus_median", "deviation_pct"}

        for mid in match_ids:
            outliers = detect_outlier_odds(mid)
            for o in outliers:
                missing = required_keys - set(o.keys())
                assert not missing, (
                    f"Outlier for {mid} missing keys: {missing}"
                )

    def test_deviation_threshold_configured(self):
        """MAX_SINGLE_BOOKMAKER_DEVIATION must be > 0 and < 1."""
        assert 0 < MAX_SINGLE_BOOKMAKER_DEVIATION < 1.0, (
            f"MAX_SINGLE_BOOKMAKER_DEVIATION={MAX_SINGLE_BOOKMAKER_DEVIATION} "
            f"should be between 0 and 1"
        )

    def test_synthetic_outlier_detected(self):
        """A bookmaker with 50% higher odds than peers should be flagged."""
        # Create a temporary in-memory DB with synthetic data
        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE odds_latest (
                match_id TEXT, bookmaker TEXT, market_type TEXT,
                home_odds REAL, draw_odds REAL, away_odds REAL
            )
        """)
        # Normal bookmakers: home=2.0, draw=3.5, away=3.5
        conn.execute("INSERT INTO odds_latest VALUES (?, ?, ?, ?, ?, ?)",
                      ("test_match", "bk1", "1x2", 2.00, 3.50, 3.50))
        conn.execute("INSERT INTO odds_latest VALUES (?, ?, ?, ?, ?, ?)",
                      ("test_match", "bk2", "1x2", 2.05, 3.40, 3.45))
        conn.execute("INSERT INTO odds_latest VALUES (?, ?, ?, ?, ?, ?)",
                      ("test_match", "bk3", "1x2", 1.95, 3.60, 3.55))
        # Outlier: home=3.50 (75% above median ~2.0)
        conn.execute("INSERT INTO odds_latest VALUES (?, ?, ?, ?, ?, ?)",
                      ("test_match", "outlier_bk", "1x2", 3.50, 3.50, 3.50))
        conn.commit()

        # Write to temp file since detect_outlier_odds reads from file
        import tempfile
        tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmpfile.close()

        tmp_conn = sqlite3.connect(tmpfile.name)
        tmp_conn.execute("""
            CREATE TABLE odds_latest (
                match_id TEXT, bookmaker TEXT, market_type TEXT,
                home_odds REAL, draw_odds REAL, away_odds REAL
            )
        """)
        for row in conn.execute("SELECT * FROM odds_latest"):
            tmp_conn.execute("INSERT INTO odds_latest VALUES (?, ?, ?, ?, ?, ?)", row)
        tmp_conn.commit()
        tmp_conn.close()
        conn.close()

        try:
            outliers = detect_outlier_odds("test_match", db_path=tmpfile.name)
            outlier_bks = [o["bookmaker"] for o in outliers]
            assert "outlier_bk" in outlier_bks, (
                f"outlier_bk with 75% deviation not detected. "
                f"Outliers found: {outliers}"
            )
        finally:
            os.unlink(tmpfile.name)

    def test_no_outlier_when_odds_close(self):
        """When all bookmakers have similar odds, no outliers should be flagged."""
        import tempfile

        tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmpfile.close()

        conn = sqlite3.connect(tmpfile.name)
        conn.execute("""
            CREATE TABLE odds_latest (
                match_id TEXT, bookmaker TEXT, market_type TEXT,
                home_odds REAL, draw_odds REAL, away_odds REAL
            )
        """)
        # All bookmakers within 5% of each other
        conn.execute("INSERT INTO odds_latest VALUES (?, ?, ?, ?, ?, ?)",
                      ("test_close", "bk1", "1x2", 2.00, 3.50, 3.50))
        conn.execute("INSERT INTO odds_latest VALUES (?, ?, ?, ?, ?, ?)",
                      ("test_close", "bk2", "1x2", 2.05, 3.45, 3.45))
        conn.execute("INSERT INTO odds_latest VALUES (?, ?, ?, ?, ?, ?)",
                      ("test_close", "bk3", "1x2", 1.98, 3.55, 3.52))
        conn.commit()
        conn.close()

        try:
            outliers = detect_outlier_odds("test_close", db_path=tmpfile.name)
            assert len(outliers) == 0, (
                f"Expected no outliers with close odds, got {len(outliers)}: {outliers}"
            )
        finally:
            os.unlink(tmpfile.name)
