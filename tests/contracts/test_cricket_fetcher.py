"""Contract tests for CricketFetcher DB integration (BUILD-ENRICH-03).

Guards:
  1. _fetch_fixture_from_db returns data_available=True with IPL fixture data
  2. _fetch_fixture_from_db resolves team names via sportmonks_teams JOIN
  3. _fetch_fixture_from_db falls back to league-level when specific match not found
  4. _fetch_fixture_from_db returns None when no fixture exists
  5. fetch_context() returns data_available=True when DB has fixture (no API token needed)
  6. competition and format fields populated from DB fixture
"""

import asyncio
import os
import sqlite3
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── Helpers ───────────────────────────────────────────────────────────────────


def _create_sportmonks_db(db_path: str) -> None:
    """Create sportmonks_fixtures + sportmonks_teams + sportmonks_venues with sample IPL data."""
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE sportmonks_fixtures (
            id INTEGER PRIMARY KEY,
            api_id INTEGER,
            league_name TEXT,
            league_id INTEGER,
            season_id INTEGER,
            match_date TEXT,
            match_type TEXT,
            status TEXT,
            home_team TEXT,
            home_team_id INTEGER,
            away_team TEXT,
            away_team_id INTEGER,
            venue_id INTEGER,
            winner_team_id INTEGER,
            note TEXT,
            scraped_at TEXT
        );
        CREATE TABLE sportmonks_teams (
            team_id INTEGER PRIMARY KEY,
            name TEXT,
            code TEXT,
            updated_at TEXT
        );
        CREATE TABLE sportmonks_venues (
            venue_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            city TEXT,
            country_id INTEGER,
            updated_at TEXT
        );
        INSERT INTO sportmonks_teams VALUES (6,  'Mumbai Indians',    'MI',   '2026-04-04');
        INSERT INTO sportmonks_teams VALUES (2,  'Chennai Super Kings','CSK', '2026-04-04');
        INSERT INTO sportmonks_teams VALUES (10, 'Sunrisers Hyderabad','SRH', '2026-04-04');
        INSERT INTO sportmonks_fixtures VALUES (
            1, 69999, 'IPL', 1, 1795,
            datetime('now', '+2 days'), 'T20', 'NS',
            'Mumbai Indians', 6, 'Chennai Super Kings', 2,
            46, NULL, NULL, '2026-04-04'
        );
        """
    )
    conn.commit()
    conn.close()


def _create_empty_sportmonks_db(db_path: str) -> None:
    """Create schema with no fixture rows."""
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE sportmonks_fixtures (
            id INTEGER PRIMARY KEY,
            api_id INTEGER,
            league_name TEXT,
            league_id INTEGER,
            season_id INTEGER,
            match_date TEXT,
            match_type TEXT,
            status TEXT,
            home_team TEXT,
            home_team_id INTEGER,
            away_team TEXT,
            away_team_id INTEGER,
            venue_id INTEGER,
            winner_team_id INTEGER,
            note TEXT,
            scraped_at TEXT
        );
        CREATE TABLE sportmonks_teams (
            team_id INTEGER PRIMARY KEY,
            name TEXT,
            code TEXT,
            updated_at TEXT
        );
        CREATE TABLE sportmonks_venues (
            venue_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            city TEXT,
            country_id INTEGER,
            updated_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()


# ── _fetch_fixture_from_db ─────────────────────────────────────────────────────


class TestFetchFixtureFromDB:
    """Contract: _fetch_fixture_from_db returns correct data from sportmonks DB."""

    def test_returns_data_available_true_with_ipl_fixture(self):
        """Primary contract: data_available=True when fixture exists."""
        from fetchers.cricket_fetcher import _fetch_fixture_from_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _create_sportmonks_db(db_path)
            result = _fetch_fixture_from_db(
                "Mumbai Indians", "Chennai Super Kings", "ipl",
                scrapers_db=db_path,
            )
            assert result is not None
            assert result["data_available"] is True
        finally:
            os.unlink(db_path)

    def test_home_name_resolved_from_teams_table(self):
        """home_name comes from sportmonks_teams JOIN when available."""
        from fetchers.cricket_fetcher import _fetch_fixture_from_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _create_sportmonks_db(db_path)
            result = _fetch_fixture_from_db(
                "Mumbai Indians", "Chennai Super Kings", "ipl",
                scrapers_db=db_path,
            )
            assert result is not None
            assert result["home_name"] == "Mumbai Indians"
            assert result["away_name"] == "Chennai Super Kings"
        finally:
            os.unlink(db_path)

    def test_competition_field_from_league_name(self):
        """competition field populated from league_name column."""
        from fetchers.cricket_fetcher import _fetch_fixture_from_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _create_sportmonks_db(db_path)
            result = _fetch_fixture_from_db(
                "Mumbai Indians", "Chennai Super Kings", "ipl",
                scrapers_db=db_path,
            )
            assert result is not None
            assert result["competition"] == "IPL"
        finally:
            os.unlink(db_path)

    def test_format_field_from_match_type(self):
        """format field populated from match_type column (T20)."""
        from fetchers.cricket_fetcher import _fetch_fixture_from_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _create_sportmonks_db(db_path)
            result = _fetch_fixture_from_db(
                "Mumbai Indians", "Chennai Super Kings", "ipl",
                scrapers_db=db_path,
            )
            assert result is not None
            assert result["format"] == "T20"
        finally:
            os.unlink(db_path)

    def test_league_fallback_when_specific_match_not_found(self):
        """Falls back to any league fixture when specific team match fails."""
        from fetchers.cricket_fetcher import _fetch_fixture_from_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _create_sportmonks_db(db_path)
            # Unknown teams but valid league — should find the IPL fixture
            result = _fetch_fixture_from_db(
                "Unknown Team A", "Unknown Team B", "ipl",
                scrapers_db=db_path,
            )
            assert result is not None
            assert result["data_available"] is True
            assert result["competition"] == "IPL"
        finally:
            os.unlink(db_path)

    def test_returns_none_when_no_fixture_exists(self):
        """Returns None when DB has no matching fixture."""
        from fetchers.cricket_fetcher import _fetch_fixture_from_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _create_empty_sportmonks_db(db_path)
            result = _fetch_fixture_from_db(
                "Mumbai Indians", "Chennai Super Kings", "ipl",
                scrapers_db=db_path,
            )
            assert result is None
        finally:
            os.unlink(db_path)

    def test_returns_none_for_unknown_league_with_no_fixtures(self):
        """Returns None for unknown league key with no fixture rows."""
        from fetchers.cricket_fetcher import _fetch_fixture_from_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _create_empty_sportmonks_db(db_path)
            result = _fetch_fixture_from_db(
                "Team A", "Team B", "sa20",
                scrapers_db=db_path,
            )
            assert result is None
        finally:
            os.unlink(db_path)

    def test_fallback_team_name_when_no_teams_row(self):
        """Falls back to fixture table team name when teams JOIN yields NULL."""
        from fetchers.cricket_fetcher import _fetch_fixture_from_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            # Fixture has team not in sportmonks_teams
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE sportmonks_fixtures (
                    id INTEGER PRIMARY KEY, api_id INTEGER, league_name TEXT,
                    league_id INTEGER, season_id INTEGER, match_date TEXT,
                    match_type TEXT, status TEXT, home_team TEXT,
                    home_team_id INTEGER, away_team TEXT, away_team_id INTEGER,
                    venue_id INTEGER, winner_team_id INTEGER, note TEXT, scraped_at TEXT
                );
                CREATE TABLE sportmonks_teams (
                    team_id INTEGER PRIMARY KEY, name TEXT, code TEXT, updated_at TEXT
                );
                CREATE TABLE sportmonks_venues (
                    venue_id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                    city TEXT, country_id INTEGER, updated_at TEXT
                );
                INSERT INTO sportmonks_fixtures VALUES (
                    1, 88888, 'IPL', 1, 1795,
                    datetime('now', '+1 day'), 'T20', 'NS',
                    'Kolkata Knight Riders', 99, 'Punjab Kings', 98,
                    50, NULL, NULL, '2026-04-04'
                );
                """
            )
            conn.commit()
            conn.close()
            result = _fetch_fixture_from_db(
                "Kolkata Knight Riders", "Punjab Kings", "ipl",
                scrapers_db=db_path,
            )
            assert result is not None
            assert result["home_name"] == "Kolkata Knight Riders"
            assert result["away_name"] == "Punjab Kings"
        finally:
            os.unlink(db_path)


# ── fetch_context integration ─────────────────────────────────────────────────


class TestCricketFetcherContextDB:
    """Contract: fetch_context() returns data_available=True from DB fixture."""

    def test_fetch_context_data_available_true_no_token(self):
        """fetch_context returns data_available=True from DB even without API token."""
        from fetchers.cricket_fetcher import CricketFetcher

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _create_sportmonks_db(db_path)

            import unittest.mock as mock

            fetcher = CricketFetcher()
            with mock.patch(
                "fetchers.cricket_fetcher._fetch_fixture_from_db",
                return_value={
                    "data_available": True,
                    "home_name": "Mumbai Indians",
                    "away_name": "Chennai Super Kings",
                    "competition": "IPL",
                    "format": "T20",
                    "match_date": "2026-04-06 14:00:00",
                },
            ), mock.patch("fetchers.cricket_fetcher._get_api_token", return_value=""):
                result = asyncio.get_event_loop().run_until_complete(
                    fetcher.fetch_context(
                        "Mumbai Indians", "Chennai Super Kings", "ipl",
                    )
                )
            assert result.context["data_available"] is True
        finally:
            os.unlink(db_path)

    def test_fetch_context_competition_from_db(self):
        """competition field reflects DB league_name, not hardcoded config."""
        from fetchers.cricket_fetcher import CricketFetcher

        import unittest.mock as mock

        fetcher = CricketFetcher()
        with mock.patch(
            "fetchers.cricket_fetcher._fetch_fixture_from_db",
            return_value={
                "data_available": True,
                "home_name": "Sunrisers Hyderabad",
                "away_name": "Royal Challengers Bengaluru",
                "competition": "IPL",
                "format": "T20",
                "match_date": "2026-04-07 10:00:00",
            },
        ), mock.patch("fetchers.cricket_fetcher._get_api_token", return_value=""):
            result = asyncio.get_event_loop().run_until_complete(
                fetcher.fetch_context(
                    "Sunrisers Hyderabad", "Royal Challengers Bengaluru", "ipl",
                )
            )
        assert result.context["competition"] == "IPL"
        assert result.context["format"] == "T20"

    def test_fetch_context_empty_when_no_token_no_db(self):
        """fetch_context returns data_available=False when no token AND no DB fixture."""
        from fetchers.cricket_fetcher import CricketFetcher

        import unittest.mock as mock

        fetcher = CricketFetcher()
        with mock.patch(
            "fetchers.cricket_fetcher._fetch_fixture_from_db",
            return_value=None,
        ), mock.patch("fetchers.cricket_fetcher._get_api_token", return_value=""):
            result = asyncio.get_event_loop().run_until_complete(
                fetcher.fetch_context("Team A", "Team B", "ipl")
            )
        assert result.context["data_available"] is False
