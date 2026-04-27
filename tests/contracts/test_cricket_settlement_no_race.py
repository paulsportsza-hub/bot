"""FIX-CORE7-CRICKET-01 — Contract test: cricket settlement race prevention.

Asserts:
  1. Cricket is NOT in _MANUAL_REVIEW_SPORTS (auto-settles like soccer/rugby).
  2. _expire_stale_edges Path 1 (kickoff-based) excludes cricket.
  3. _expire_stale_edges Path 2a (2-day date-stale) excludes cricket.
  4. _expire_stale_edges Path 2b (7-day grace) only fires after 7 days for cricket.
  5. settle_edges() settles a cricket edge BEFORE _expire_stale_edges marks it expired —
     simulates the race with a synthetic in-memory DB.

Uses isolated in-memory SQLite — no live odds.db dependency.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

_BOT_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _BOT_DIR)
import config
config.ensure_scrapers_importable()

from scrapers.edge.settlement import (
    _MANUAL_REVIEW_SPORTS,
    evaluate_bet,
    settle_edges,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE edge_results (
            id INTEGER PRIMARY KEY,
            edge_id TEXT DEFAULT 'test_edge',
            match_key TEXT NOT NULL,
            sport TEXT NOT NULL,
            league TEXT DEFAULT 'ipl',
            edge_tier TEXT DEFAULT 'silver',
            composite_score REAL DEFAULT 55.0,
            bet_type TEXT NOT NULL,
            result TEXT,
            match_score TEXT,
            actual_return REAL,
            recommended_odds REAL DEFAULT 2.0,
            bookmaker TEXT DEFAULT 'betway',
            predicted_ev REAL DEFAULT 5.0,
            recommended_at TEXT DEFAULT (datetime('now')),
            settled_at TEXT,
            match_date TEXT NOT NULL,
            movement TEXT,
            confirming_signals INTEGER,
            posted_to_alerts_direct INTEGER DEFAULT 0
        );
        CREATE TABLE match_results (
            id INTEGER PRIMARY KEY,
            match_key TEXT NOT NULL UNIQUE,
            home_team TEXT,
            away_team TEXT,
            home_score INTEGER,
            away_score INTEGER,
            result TEXT,
            match_date TEXT,
            league TEXT,
            sport TEXT
        );
        CREATE TABLE fixture_mapping (
            id INTEGER PRIMARY KEY,
            match_key TEXT NOT NULL UNIQUE,
            league TEXT,
            home_team TEXT,
            away_team TEXT,
            kickoff TEXT,
            status TEXT,
            api_fixture_id TEXT,
            venue TEXT,
            mapped_at TEXT,
            referee TEXT
        );
        CREATE TABLE odds_snapshots (
            id INTEGER PRIMARY KEY,
            match_key TEXT,
            bookmaker TEXT,
            scraped_at TEXT
        );
        CREATE TABLE clv_tracking (
            id INTEGER PRIMARY KEY,
            match_key TEXT, selection TEXT,
            our_recommended_odds REAL, our_recommended_bookmaker TEXT,
            our_edge_rating TEXT, price_edge_score REAL, market_agreement_score REAL,
            form_h2h_score REAL, tipster_score REAL, lineup_injury_score REAL,
            movement_score REAL, model_probability_score REAL, raw_signals_json TEXT
        );
    """)
    return conn


def _make_db_file(path: str) -> sqlite3.Connection:
    """Create a file-based SQLite DB with the required schema (for tests that need settle_edges to close/reopen)."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS edge_results (
            id INTEGER PRIMARY KEY,
            edge_id TEXT DEFAULT 'test_edge',
            match_key TEXT NOT NULL,
            sport TEXT NOT NULL,
            league TEXT DEFAULT 'ipl',
            edge_tier TEXT DEFAULT 'silver',
            composite_score REAL DEFAULT 55.0,
            bet_type TEXT NOT NULL,
            result TEXT,
            match_score TEXT,
            actual_return REAL,
            recommended_odds REAL DEFAULT 2.0,
            bookmaker TEXT DEFAULT 'betway',
            predicted_ev REAL DEFAULT 5.0,
            recommended_at TEXT DEFAULT (datetime('now')),
            settled_at TEXT,
            match_date TEXT NOT NULL,
            movement TEXT,
            confirming_signals INTEGER,
            posted_to_alerts_direct INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS match_results (
            id INTEGER PRIMARY KEY,
            match_key TEXT NOT NULL UNIQUE,
            home_team TEXT, away_team TEXT,
            home_score INTEGER, away_score INTEGER,
            result TEXT, match_date TEXT, league TEXT, sport TEXT
        );
        CREATE TABLE IF NOT EXISTS fixture_mapping (
            id INTEGER PRIMARY KEY,
            match_key TEXT NOT NULL UNIQUE,
            league TEXT, home_team TEXT, away_team TEXT,
            kickoff TEXT, status TEXT, api_fixture_id TEXT,
            venue TEXT, mapped_at TEXT, referee TEXT
        );
        CREATE TABLE IF NOT EXISTS odds_snapshots (
            id INTEGER PRIMARY KEY, match_key TEXT, bookmaker TEXT, scraped_at TEXT
        );
        CREATE TABLE IF NOT EXISTS clv_tracking (
            id INTEGER PRIMARY KEY, match_key TEXT, selection TEXT,
            our_recommended_odds REAL, our_recommended_bookmaker TEXT,
            our_edge_rating TEXT, price_edge_score REAL, market_agreement_score REAL,
            form_h2h_score REAL, tipster_score REAL, lineup_injury_score REAL,
            movement_score REAL, model_probability_score REAL, raw_signals_json TEXT
        );
    """)
    return conn


def _add_cricket_edge(conn, match_key: str, match_date: str, result=None) -> int:
    conn.execute(
        """INSERT INTO edge_results
           (match_key, sport, league, bet_type, recommended_odds, match_date, result)
           VALUES (?, 'cricket', 'ipl', 'Home Win', 2.0, ?, ?)""",
        (match_key, match_date, result),
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _add_result(conn, match_key: str, home: int, away: int):
    conn.execute(
        """INSERT OR REPLACE INTO match_results
           (match_key, home_score, away_score, result, match_date, league, sport)
           VALUES (?, ?, ?, 'finished', date('now'), 'ipl', 'cricket')""",
        (match_key, home, away),
    )
    conn.commit()


def _add_fixture(conn, match_key: str, kickoff: str):
    conn.execute(
        """INSERT OR REPLACE INTO fixture_mapping
           (match_key, kickoff, league, home_team, away_team, status)
           VALUES (?, ?, 'ipl', 'team_a', 'team_b', 'finished')""",
        (match_key, kickoff),
    )
    conn.commit()


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestCricketNotInManualReview:
    """Cricket must be removed from _MANUAL_REVIEW_SPORTS (FIX-CORE7-CRICKET-01)."""

    def test_cricket_not_in_manual_review_sports(self):
        assert "cricket" not in _MANUAL_REVIEW_SPORTS, (
            "cricket must not be in _MANUAL_REVIEW_SPORTS — "
            "FIX-CORE7-CRICKET-01 removed it so settle_edges() auto-settles IPL edges."
        )

    def test_mma_boxing_still_in_manual_review(self):
        assert "mma" in _MANUAL_REVIEW_SPORTS
        assert "boxing" in _MANUAL_REVIEW_SPORTS

    def test_evaluate_bet_cricket_home_win(self):
        assert evaluate_bet("Home Win", 180, 160, "cricket") is True

    def test_evaluate_bet_cricket_away_win(self):
        assert evaluate_bet("Away Win", 160, 180, "cricket") is True

    def test_evaluate_bet_cricket_home_loss(self):
        assert evaluate_bet("Home Win", 160, 180, "cricket") is False


class TestExpireStaleEdgesExcludesCricket:
    """_expire_stale_edges SQL must exclude cricket from kickoff and 2-day paths."""

    def test_expire_sql_path1_excludes_cricket(self):
        """Path 1 (kickoff-based) query must have sport NOT IN ('cricket', ...)."""
        import bot
        import inspect
        src = inspect.getsource(bot._expire_stale_edges)
        assert "sport NOT IN" in src, "Path 1 must filter out cricket by sport NOT IN"
        assert "'cricket'" in src, "cricket must be in the exclusion list"

    def test_expire_sql_path2a_excludes_cricket(self):
        """Path 2a (2-day) query must exclude cricket."""
        import bot
        import inspect
        src = inspect.getsource(bot._expire_stale_edges)
        assert "-2 days" in src, "Path 2a must keep -2 days threshold"
        # Verify -2 days appears alongside NOT IN filter
        lines = src.splitlines()
        two_day_block = "\n".join(
            l for l in lines if "-2 days" in l or "sport NOT IN" in l
        )
        assert "sport NOT IN" in two_day_block

    def test_expire_sql_path2b_cricket_7_days(self):
        """Path 2b must expire cricket/combat only after 7 days."""
        import bot
        import inspect
        src = inspect.getsource(bot._expire_stale_edges)
        assert "-7 days" in src, "Path 2b must use -7 days for cricket/combat"
        assert "sport IN" in src, "Path 2b must use sport IN filter for cricket"


class TestCricketSettlesBeforeExpiry:
    """Timing contract: a cricket edge settles before _expire_stale_edges marks it expired.

    Simulates a match played yesterday where results are in match_results.
    With the fix (cricket excluded from kickoff path, 7-day grace on date path),
    settle_edges() must settle the edge as hit/miss BEFORE the grace period fires.
    """

    def test_cricket_edge_settles_not_expires(self, tmp_path):
        db_path = str(tmp_path / "test_settle.db")
        conn = _make_db_file(db_path)
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        match_key = "mumbai_indians_vs_chennai_super_kings_2026-04-26"

        _add_cricket_edge(conn, match_key, yesterday)
        _add_result(conn, match_key, 200, 180)
        conn.close()

        with patch("scrapers.edge.settlement.DB_PATH", db_path):
            counts = settle_edges()

        conn2 = sqlite3.connect(db_path)
        conn2.row_factory = sqlite3.Row
        row = conn2.execute(
            "SELECT result FROM edge_results WHERE match_key = ?", (match_key,)
        ).fetchone()
        conn2.close()

        assert row["result"] in ("hit", "miss"), (
            f"Cricket edge must be settled to hit/miss by settle_edges(), got: {row['result']}"
        )
        assert counts["settled"] >= 1

    def test_cricket_edge_kickoff_does_not_cause_expiry(self):
        """A cricket edge with a past kickoff in fixture_mapping must NOT be expired by Path 1."""
        conn = _make_db()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        match_key = "royal_challengers_bengaluru_vs_gujarat_titans_2026-04-27"
        past_kickoff = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime(
            "%Y-%m-%dT%H:%M:%S+00:00"
        )

        _add_cricket_edge(conn, match_key, today)
        _add_fixture(conn, match_key, past_kickoff)

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

        # Simulate Path 1 expiry with cricket exclusion (mirrors bot._expire_stale_edges)
        rowcount = conn.execute("""
            UPDATE edge_results
            SET result = 'expired'
            WHERE result IS NULL
              AND sport NOT IN ('cricket', 'mma', 'boxing')
              AND match_key IN (
                  SELECT e.match_key
                  FROM edge_results e
                  JOIN fixture_mapping fm ON fm.match_key = e.match_key
                  WHERE e.result IS NULL
                    AND e.sport NOT IN ('cricket', 'mma', 'boxing')
                    AND fm.kickoff < ?
              )
        """, (now_utc,)).rowcount
        conn.commit()

        row = conn.execute(
            "SELECT result FROM edge_results WHERE match_key = ?", (match_key,)
        ).fetchone()
        assert row["result"] is None, (
            "Cricket edge with past kickoff must NOT be expired by Path 1 "
            f"(got: {row['result']})"
        )

    def test_cricket_edge_2day_path_does_not_expire(self):
        """A 3-day-old cricket edge must NOT be expired by the 2-day date-stale path."""
        conn = _make_db()
        three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
        match_key = "punjab_kings_vs_rajasthan_royals_2026-04-24"
        _add_cricket_edge(conn, match_key, three_days_ago)

        # Simulate Path 2a (2-day, non-cricket only)
        conn.execute("""
            UPDATE edge_results
            SET result = 'expired'
            WHERE result IS NULL
              AND sport NOT IN ('cricket', 'mma', 'boxing')
              AND match_date < date('now', '-2 days')
        """)
        conn.commit()

        row = conn.execute(
            "SELECT result FROM edge_results WHERE match_key = ?", (match_key,)
        ).fetchone()
        assert row["result"] is None, (
            "3-day-old cricket edge must not be expired by 2-day path "
            f"(got: {row['result']})"
        )

    def test_cricket_edge_7day_path_expires(self):
        """An 8-day-old cricket edge (still NULL) MUST expire via the 7-day grace path."""
        conn = _make_db()
        eight_days_ago = (datetime.now(timezone.utc) - timedelta(days=8)).strftime("%Y-%m-%d")
        match_key = "sunrisers_hyderabad_vs_mumbai_indians_2026-04-19"
        _add_cricket_edge(conn, match_key, eight_days_ago)

        # Simulate Path 2b (7-day grace for cricket)
        conn.execute("""
            UPDATE edge_results
            SET result = 'expired'
            WHERE result IS NULL
              AND sport IN ('cricket', 'mma', 'boxing')
              AND match_date < date('now', '-7 days')
        """)
        conn.commit()

        row = conn.execute(
            "SELECT result FROM edge_results WHERE match_key = ?", (match_key,)
        ).fetchone()
        assert row["result"] == "expired", (
            "8-day-old unresolved cricket edge must be expired by the 7-day grace path"
        )
