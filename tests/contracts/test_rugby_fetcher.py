"""Contract test: RugbyFetcher.fetch_context() queries rugby_fixtures → data_available=True.

BUILD-ENRICH-02: Wire RugbyFetcher to rugby_fixtures table.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from unittest.mock import patch

# Ensure both bot/ and the parent dir (for scrapers package) are on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from fetchers.rugby_fetcher import RugbyFetcher, _query_rugby_fixture


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_db(tmp_path) -> str:
    """Create a minimal rugby_fixtures SQLite DB with one upcoming fixture."""
    db_path = str(tmp_path / "odds.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE rugby_fixtures (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            api_id          INTEGER NOT NULL,
            league_name     TEXT,
            league_api_id   INTEGER,
            season          INTEGER,
            match_date      TEXT NOT NULL,
            status          TEXT,
            home_team       TEXT NOT NULL,
            home_team_api_id INTEGER,
            away_team       TEXT NOT NULL,
            away_team_api_id INTEGER,
            home_score      INTEGER,
            away_score      INTEGER,
            scraped_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(api_id)
        )
    """)
    conn.execute(
        """INSERT INTO rugby_fixtures
           (api_id, league_name, league_api_id, season, match_date, status,
            home_team, home_team_api_id, away_team, away_team_api_id)
           VALUES (?, ?, ?, ?, date('now', '+1 day'), 'Not Started',
                   ?, ?, ?, ?)""",
        (99001, "Super Rugby", 71, 2026, "Chiefs", 101, "Waratahs", 102),
    )
    conn.commit()
    conn.close()
    return db_path


def _run(coro):
    return asyncio.run(coro)


# ── Unit: _query_rugby_fixture ─────────────────────────────────────────────────

class TestQueryRugbyFixture:
    def test_returns_row_when_match_exists(self, tmp_path):
        db = _make_db(tmp_path)
        row = _query_rugby_fixture("Chiefs", "Waratahs", scrapers_db=db)
        assert row is not None
        assert row["home_team"] == "Chiefs"
        assert row["away_team"] == "Waratahs"
        assert row["league_name"] == "Super Rugby"

    def test_case_insensitive_match(self, tmp_path):
        db = _make_db(tmp_path)
        row = _query_rugby_fixture("chiefs", "WARATAHS", scrapers_db=db)
        assert row is not None

    def test_returns_none_when_no_match(self, tmp_path):
        db = _make_db(tmp_path)
        row = _query_rugby_fixture("Bulls", "Stormers", scrapers_db=db)
        assert row is None

    def test_returns_none_on_db_error(self):
        row = _query_rugby_fixture("Chiefs", "Waratahs", scrapers_db="/nonexistent/path.db")
        assert row is None


# ── Integration: RugbyFetcher.fetch_context() ─────────────────────────────────

class TestRugbyFetcherDBFirst:
    def test_data_available_true_with_fixture(self, tmp_path):
        """AC: data_available=True when rugby_fixtures has a matching row."""
        db = _make_db(tmp_path)
        fetcher = RugbyFetcher()

        with patch(
            "fetchers.rugby_fetcher._query_rugby_fixture",
            return_value={
                "home_team": "Chiefs",
                "away_team": "Waratahs",
                "league_name": "Super Rugby",
                "match_date": "2026-04-05",
                "status": "Not Started",
            },
        ):
            result = _run(
                fetcher.fetch_context("Chiefs", "Waratahs", "super_rugby", db_path=db)
            )

        assert result.context["data_available"] is True

    def test_home_name_maps_from_fixture(self, tmp_path):
        """AC: home_team['name'] comes from rugby_fixtures.home_team."""
        db = _make_db(tmp_path)
        fetcher = RugbyFetcher()

        with patch(
            "fetchers.rugby_fetcher._query_rugby_fixture",
            return_value={
                "home_team": "Chiefs",
                "away_team": "Waratahs",
                "league_name": "Super Rugby",
                "match_date": "2026-04-05",
                "status": "Not Started",
            },
        ):
            result = _run(
                fetcher.fetch_context("Chiefs", "Waratahs", "super_rugby", db_path=db)
            )

        assert result.context["home_team"]["name"] == "Chiefs"
        assert result.context["away_team"]["name"] == "Waratahs"

    def test_competition_maps_from_league_name(self, tmp_path):
        """AC: competition field comes from rugby_fixtures.league_name."""
        db = _make_db(tmp_path)
        fetcher = RugbyFetcher()

        with patch(
            "fetchers.rugby_fetcher._query_rugby_fixture",
            return_value={
                "home_team": "Leinster",
                "away_team": "Ulster",
                "league_name": "United Rugby Championship",
                "match_date": "2026-04-06",
                "status": "Not Started",
            },
        ):
            result = _run(
                fetcher.fetch_context("Leinster", "Ulster", "urc", db_path=db)
            )

        assert result.context["competition"] == "United Rugby Championship"

    def test_data_available_false_when_no_fixture(self, tmp_path):
        """AC: no regression — data_available=False when no fixture in DB and API unavailable."""
        db_path = str(tmp_path / "empty.db")
        fetcher = RugbyFetcher()

        # Patch out API key so the no-fixture path returns _empty_fallback immediately
        with patch("fetchers.rugby_fetcher._query_rugby_fixture", return_value=None), \
             patch("fetchers.rugby_fetcher._get_api_key", return_value=""):
            result = _run(
                fetcher.fetch_context("Bulls", "Stormers", "urc", db_path=db_path)
            )

        assert result.context["data_available"] is False

    def test_data_source_set_to_rugby_fixtures(self, tmp_path):
        """data_source field identifies the DB table when fixture found."""
        db = _make_db(tmp_path)
        fetcher = RugbyFetcher()

        with patch(
            "fetchers.rugby_fetcher._query_rugby_fixture",
            return_value={
                "home_team": "Reds",
                "away_team": "Western Force",
                "league_name": "Super Rugby",
                "match_date": "2026-04-07",
                "status": "Not Started",
            },
        ):
            result = _run(
                fetcher.fetch_context("Reds", "Western Force", "super_rugby", db_path=db)
            )

        assert result.context["data_source"] == "rugby_fixtures"

    def test_unknown_league_still_returns_data_available(self, tmp_path):
        """Fixture found overrides unknown league guard — data_available=True."""
        db = _make_db(tmp_path)
        fetcher = RugbyFetcher()

        with patch(
            "fetchers.rugby_fetcher._query_rugby_fixture",
            return_value={
                "home_team": "Chiefs",
                "away_team": "Waratahs",
                "league_name": "Super Rugby",
                "match_date": "2026-04-05",
                "status": "Not Started",
            },
        ):
            # "unknown_league" is not in LEAGUE_CONFIG — previously caused early False return
            result = _run(
                fetcher.fetch_context("Chiefs", "Waratahs", "unknown_league", db_path=db)
            )

        assert result.context["data_available"] is True
