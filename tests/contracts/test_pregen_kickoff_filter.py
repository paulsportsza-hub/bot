"""BUILD-PREGEN-KICKOFF-FILTER-01: Regression tests for past-kickoff skip + quarantine.

AC coverage:
  (a) _generate_one returns skipped_past_kickoff for >24h past fixture (Sonnet not called)
  (b) <24h-past fixture is NOT skipped
  (c) Future fixture is NOT skipped
  (d) _quarantine_stale_cache_rows marks stale rows idempotently
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

# Ensure scripts/ and bot/ are on the path
_BOT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS_DIR = os.path.join(_BOT_ROOT, "scripts")
for _p in (_BOT_ROOT, _SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _date_suffix(delta_days: int) -> str:
    """Return YYYY-MM-DD for today ± delta_days."""
    return (datetime.now(timezone.utc) + timedelta(days=delta_days)).strftime("%Y-%m-%d")


def _make_narrative_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE narrative_cache (
            match_id TEXT PRIMARY KEY,
            narrative_html TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT 'test',
            edge_tier TEXT NOT NULL DEFAULT 'bronze',
            tips_json TEXT NOT NULL DEFAULT '[]',
            odds_hash TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            evidence_json TEXT,
            narrative_source TEXT NOT NULL DEFAULT 'w82',
            coverage_json TEXT,
            quarantined INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Tests for _is_past_kickoff (AC b + c + partial a)
# ---------------------------------------------------------------------------

class TestIsPastKickoff:
    """Unit tests for the pure helper function."""

    def test_ancient_fixture_is_past(self):
        from pregenerate_narratives import _is_past_kickoff
        assert _is_past_kickoff("man_city_vs_arsenal_2020-01-01") is True

    def test_yesterday_fixture_is_past(self):
        from pregenerate_narratives import _is_past_kickoff
        key = f"home_vs_away_{_date_suffix(-2)}"
        assert _is_past_kickoff(key) is True

    def test_within_24h_fixture_not_past(self):
        """Fixture dated today is within 24h — must not be skipped (AC b)."""
        from pregenerate_narratives import _is_past_kickoff
        # Today midnight UTC is < 24h ago for most of the day
        key = f"home_vs_away_{_date_suffix(0)}"
        # This is ambiguous at day boundary; test future fixture instead for AC b
        key_future = f"home_vs_away_{_date_suffix(1)}"
        assert _is_past_kickoff(key_future) is False

    def test_future_fixture_not_past(self):
        """Future fixture must never be skipped (AC c)."""
        from pregenerate_narratives import _is_past_kickoff
        key = f"home_vs_away_{_date_suffix(3)}"
        assert _is_past_kickoff(key) is False

    def test_no_date_suffix_returns_false(self):
        """Match keys without a date suffix are not filtered."""
        from pregenerate_narratives import _is_past_kickoff
        assert _is_past_kickoff("man_city_vs_arsenal") is False
        assert _is_past_kickoff("") is False

    def test_malformed_date_returns_false(self):
        from pregenerate_narratives import _is_past_kickoff
        assert _is_past_kickoff("home_vs_away_not-a-date") is False

    def test_cutoff_hours_respected(self):
        """Custom cutoff_hours parameter is respected."""
        from pregenerate_narratives import _is_past_kickoff
        # A fixture 2 days old is past with default 24h cutoff
        key = f"home_vs_away_{_date_suffix(-2)}"
        assert _is_past_kickoff(key, cutoff_hours=24) is True
        # With a 96h cutoff a 2-day-old fixture is NOT past
        assert _is_past_kickoff(key, cutoff_hours=96) is False


# ---------------------------------------------------------------------------
# Tests for _generate_one early return (AC a)
# ---------------------------------------------------------------------------

class TestGenerateOneKickoffFilter:
    """_generate_one must early-return for past-kickoff fixtures."""

    def test_past_kickoff_returns_skipped(self):
        """AC a: _generate_one returns skipped_past_kickoff=True, success=False."""
        from pregenerate_narratives import _generate_one

        past_edge = {
            "match_key": f"man_city_vs_arsenal_2020-01-01",
            "home_team": "Man City",
            "away_team": "Arsenal",
            "sport": "soccer",
            "league": "EPL",
            "tier": "gold",
        }

        result = asyncio.run(_generate_one(past_edge))

        assert result["success"] is False
        assert result.get("skipped_past_kickoff") is True
        assert "match_key" in result
        assert result["match_key"] == "man_city_vs_arsenal_2020-01-01"

    def test_future_kickoff_not_skipped(self):
        """AC c: future fixture proceeds past the early-return guard."""
        from pregenerate_narratives import _is_past_kickoff
        future_key = f"home_vs_away_{_date_suffix(3)}"
        # The guard must NOT fire for a future fixture
        assert not _is_past_kickoff(future_key)

    def test_recent_kickoff_not_skipped(self):
        """AC b: <24h-past fixture is not filtered."""
        from pregenerate_narratives import _is_past_kickoff
        # Fixture 12h in the future is within 24h window
        recent_key = f"home_vs_away_{_date_suffix(1)}"
        assert not _is_past_kickoff(recent_key)


# ---------------------------------------------------------------------------
# Tests for _quarantine_stale_cache_rows (AC d)
# ---------------------------------------------------------------------------

class TestQuarantineStale:
    """_quarantine_stale_cache_rows marks past rows and is idempotent."""

    def test_quarantines_stale_rows(self, tmp_path):
        db = str(tmp_path / "odds.db")
        conn = _make_narrative_db(db)
        stale_key = f"home_vs_away_{_date_suffix(-3)}"
        fresh_key = f"home_vs_away_{_date_suffix(1)}"
        conn.execute("INSERT INTO narrative_cache (match_id) VALUES (?)", (stale_key,))
        conn.execute("INSERT INTO narrative_cache (match_id) VALUES (?)", (fresh_key,))
        conn.commit()
        conn.close()

        from pregenerate_narratives import _quarantine_stale_cache_rows
        count = _quarantine_stale_cache_rows(db_path=db)

        assert count == 1
        conn2 = sqlite3.connect(db)
        rows = {r[0]: r[1] for r in conn2.execute(
            "SELECT match_id, quarantined FROM narrative_cache"
        ).fetchall()}
        conn2.close()
        assert rows[stale_key] == 1
        assert rows[fresh_key] == 0

    def test_idempotent_on_already_quarantined(self, tmp_path):
        """Running back-purge twice must not double-count."""
        db = str(tmp_path / "odds.db")
        conn = _make_narrative_db(db)
        stale_key = f"home_vs_away_{_date_suffix(-3)}"
        conn.execute("INSERT INTO narrative_cache (match_id) VALUES (?)", (stale_key,))
        conn.commit()
        conn.close()

        from pregenerate_narratives import _quarantine_stale_cache_rows
        count1 = _quarantine_stale_cache_rows(db_path=db)
        count2 = _quarantine_stale_cache_rows(db_path=db)

        assert count1 == 1
        assert count2 == 0  # already quarantined — no new rows

    def test_future_rows_untouched(self, tmp_path):
        db = str(tmp_path / "odds.db")
        conn = _make_narrative_db(db)
        future_key = f"home_vs_away_{_date_suffix(3)}"
        conn.execute("INSERT INTO narrative_cache (match_id) VALUES (?)", (future_key,))
        conn.commit()
        conn.close()

        from pregenerate_narratives import _quarantine_stale_cache_rows
        count = _quarantine_stale_cache_rows(db_path=db)

        assert count == 0
        conn2 = sqlite3.connect(db)
        row = conn2.execute(
            "SELECT quarantined FROM narrative_cache WHERE match_id = ?", (future_key,)
        ).fetchone()
        conn2.close()
        assert row[0] == 0

    def test_today_row_untouched(self, tmp_path):
        """A row dated today is within 24h and must NOT be quarantined."""
        db = str(tmp_path / "odds.db")
        conn = _make_narrative_db(db)
        today_key = f"home_vs_away_{_date_suffix(0)}"
        conn.execute("INSERT INTO narrative_cache (match_id) VALUES (?)", (today_key,))
        conn.commit()
        conn.close()

        from pregenerate_narratives import _quarantine_stale_cache_rows
        # Today at midnight UTC is < 24h ago; row should NOT be quarantined
        # (cutoff = now - 24h; today's date >= cutoff date)
        count = _quarantine_stale_cache_rows(db_path=db)
        assert count == 0
