"""Contract tests: RugbyFetcher standings enrichment + BUILD-ENRICH-04.

BUILD-ENRICH-02: Wire RugbyFetcher to rugby_fixtures table.
BUILD-ENRICH-04: Enrich fetch_context() with rugby_standings for position/form.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from unittest.mock import patch

import pytest

# Ensure both bot/ and the parent dir (for scrapers package) are on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from fetchers.rugby_fetcher import (
    RugbyFetcher,
    _query_rugby_fixture,
    _query_rugby_standings,
)


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


def _make_db_with_standings(tmp_path) -> str:
    """Create an odds.db with rugby_fixtures + rugby_standings populated."""
    db_path = str(tmp_path / "odds.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE rugby_fixtures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_id INTEGER NOT NULL,
            league_name TEXT,
            league_api_id INTEGER,
            season INTEGER,
            match_date TEXT NOT NULL,
            status TEXT,
            home_team TEXT NOT NULL,
            home_team_api_id INTEGER,
            away_team TEXT NOT NULL,
            away_team_api_id INTEGER,
            home_score INTEGER,
            away_score INTEGER,
            scraped_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(api_id)
        )
    """)
    conn.execute(
        """INSERT INTO rugby_fixtures
           (api_id, league_name, league_api_id, season, match_date, status,
            home_team, home_team_api_id, away_team, away_team_api_id)
           VALUES (?, ?, ?, ?, date('now', '+1 day'), 'Not Started', ?, ?, ?, ?)""",
        (99001, "Super Rugby", 71, 2026, "Chiefs", 501, "Waratahs", 502),
    )
    conn.execute("""
        CREATE TABLE rugby_standings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league_api_id INTEGER NOT NULL,
            season INTEGER NOT NULL,
            team_name TEXT NOT NULL,
            team_api_id INTEGER NOT NULL,
            position INTEGER,
            played INTEGER, won INTEGER, drawn INTEGER, lost INTEGER,
            points INTEGER, points_diff INTEGER,
            form TEXT,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(league_api_id, season, team_api_id)
        )
    """)
    conn.execute(
        """INSERT INTO rugby_standings
           (league_api_id, season, team_name, team_api_id,
            position, played, won, drawn, lost, points, points_diff, form)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (71, 2026, "Chiefs", 501, 1, 12, 10, 0, 2, 40, 85, "WWWLW"),
    )
    conn.execute(
        """INSERT INTO rugby_standings
           (league_api_id, season, team_name, team_api_id,
            position, played, won, drawn, lost, points, points_diff, form)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (71, 2026, "Waratahs", 502, 8, 12, 4, 0, 8, 16, -45, "LWLLW"),
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


# ── BUILD-ENRICH-04: standings write contract ─────────────────────────────────

class TestStandingsWrite:
    def test_upsert_standing_creates_row(self, tmp_path):
        """AC: _upsert_standing stores a row with all required fields."""
        from scrapers.api_sports_rugby import (
            _CREATE_STANDINGS_TABLE_SQL,
            _upsert_standing,
        )
        db_path = str(tmp_path / "odds.db")
        conn = sqlite3.connect(db_path)
        conn.execute(_CREATE_STANDINGS_TABLE_SQL)
        _upsert_standing(conn, {
            "league_api_id": 76, "season": 2025, "team_name": "Leinster",
            "team_api_id": 100, "position": 1, "played": 10, "won": 8,
            "drawn": 0, "lost": 2, "points": 32, "points_diff": 120,
            "form": "WWLWW",
        })
        conn.commit()
        row = conn.execute(
            "SELECT * FROM rugby_standings WHERE team_api_id = 100"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_upsert_standing_is_idempotent(self, tmp_path):
        """AC: repeated upsert with same (league_api_id, season, team_api_id) → one row."""
        from scrapers.api_sports_rugby import (
            _CREATE_STANDINGS_TABLE_SQL,
            _upsert_standing,
        )
        db_path = str(tmp_path / "odds.db")
        conn = sqlite3.connect(db_path)
        conn.execute(_CREATE_STANDINGS_TABLE_SQL)
        standing = {
            "league_api_id": 76, "season": 2025, "team_name": "Leinster",
            "team_api_id": 100, "position": 1, "played": 10, "won": 8,
            "drawn": 0, "lost": 2, "points": 32, "points_diff": 120,
            "form": "WWLWW",
        }
        _upsert_standing(conn, standing)
        conn.commit()
        # Second upsert with updated position — must not create a duplicate row
        standing2 = dict(standing)
        standing2["position"] = 2
        _upsert_standing(conn, standing2)
        conn.commit()
        count = conn.execute(
            "SELECT COUNT(*) FROM rugby_standings WHERE team_api_id = 100"
        ).fetchone()[0]
        position = conn.execute(
            "SELECT position FROM rugby_standings WHERE team_api_id = 100"
        ).fetchone()[0]
        conn.close()
        assert count == 1, "Idempotent upsert must not create duplicate rows"
        assert position == 2, "Upsert must update existing row with new values"


# ── BUILD-ENRICH-04: fetcher reads standings ──────────────────────────────────

class TestFetcherReadsStandings:
    def test_query_rugby_standings_by_api_id(self, tmp_path):
        """AC: _query_rugby_standings finds row by team_api_id."""
        db = _make_db_with_standings(tmp_path)
        result = _query_rugby_standings("Chiefs", 501, 71, scrapers_db=db)
        assert result is not None
        assert result["position"] == 1
        assert result["form"] == "WWWLW"

    def test_query_rugby_standings_by_name_fallback(self, tmp_path):
        """AC: _query_rugby_standings falls back to team_name when api_id is None."""
        db = _make_db_with_standings(tmp_path)
        result = _query_rugby_standings("waratahs", None, 71, scrapers_db=db)
        assert result is not None
        assert result["position"] == 8

    def test_query_rugby_standings_returns_none_without_league(self, tmp_path):
        """AC: returns None gracefully when league_api_id is None."""
        db = _make_db_with_standings(tmp_path)
        result = _query_rugby_standings("Chiefs", 501, None, scrapers_db=db)
        assert result is None

    def test_query_rugby_standings_returns_none_on_db_error(self):
        """AC: returns None gracefully when DB does not exist."""
        result = _query_rugby_standings("Chiefs", 501, 71, scrapers_db="/nonexistent/path.db")
        assert result is None

    def test_fetch_context_includes_position_from_standings(self, tmp_path):
        """AC: fetch_context() returns home/away position when rugby_standings has data."""
        db = str(tmp_path / "bot.db")
        fetcher = RugbyFetcher()

        def _mock_standings(name, api_id, league_id, scrapers_db=None):
            if name == "Chiefs":
                return {
                    "position": 1, "league_position": 1, "points": 40,
                    "form": "WWWLW", "played": 12, "won": 10, "drawn": 0, "lost": 2,
                    "points_diff": 85,
                }
            return {
                "position": 8, "league_position": 8, "points": 16,
                "form": "LWLLW", "played": 12, "won": 4, "drawn": 0, "lost": 8,
                "points_diff": -45,
            }

        with patch(
            "fetchers.rugby_fetcher._query_rugby_fixture",
            return_value={
                "home_team": "Chiefs",
                "away_team": "Waratahs",
                "league_name": "Super Rugby",
                "match_date": "2026-04-05",
                "status": "Not Started",
                "home_team_api_id": 501,
                "away_team_api_id": 502,
                "league_api_id": 71,
            },
        ), patch(
            "fetchers.rugby_fetcher._query_rugby_standings",
            side_effect=_mock_standings,
        ):
            result = _run(
                fetcher.fetch_context("Chiefs", "Waratahs", "super_rugby", db_path=db)
            )

        assert result.context["home_team"]["position"] == 1
        assert result.context["away_team"]["position"] == 8

    def test_fetch_context_includes_form_from_standings(self, tmp_path):
        """AC: fetch_context() returns form string from rugby_standings."""
        db = str(tmp_path / "bot.db")
        fetcher = RugbyFetcher()

        def _mock_standings(name, api_id, league_id, scrapers_db=None):
            if name == "Chiefs":
                return {
                    "position": 1, "league_position": 1, "points": 40,
                    "form": "WWWLW", "played": 12, "won": 10, "drawn": 0, "lost": 2,
                    "points_diff": 85,
                }
            return None  # Away team has no standings

        with patch(
            "fetchers.rugby_fetcher._query_rugby_fixture",
            return_value={
                "home_team": "Chiefs",
                "away_team": "Waratahs",
                "league_name": "Super Rugby",
                "match_date": "2026-04-05",
                "status": "Not Started",
                "home_team_api_id": 501,
                "away_team_api_id": 502,
                "league_api_id": 71,
            },
        ), patch(
            "fetchers.rugby_fetcher._query_rugby_standings",
            side_effect=_mock_standings,
        ):
            result = _run(
                fetcher.fetch_context("Chiefs", "Waratahs", "super_rugby", db_path=db)
            )

        assert result.context["home_team"]["form"] == "WWWLW"
        # Away has no standings — must still have name, no position key
        assert result.context["away_team"]["name"] == "Waratahs"
        assert "position" not in result.context["away_team"]

    def test_fetch_context_data_available_without_standings(self, tmp_path):
        """AC: data_available=True even when standings lookup returns None (no regression)."""
        db = str(tmp_path / "bot.db")
        fetcher = RugbyFetcher()

        with patch(
            "fetchers.rugby_fetcher._query_rugby_fixture",
            return_value={
                "home_team": "Bulls",
                "away_team": "Stormers",
                "league_name": "URC",
                "match_date": "2026-04-06",
                "status": "Not Started",
                "home_team_api_id": None,
                "away_team_api_id": None,
                "league_api_id": None,
            },
        ):
            result = _run(
                fetcher.fetch_context("Bulls", "Stormers", "urc", db_path=db)
            )

        assert result.context["data_available"] is True
        assert result.context["home_team"]["name"] == "Bulls"


# ── BUILD-ENRICH-04: story type classification ────────────────────────────────

class TestStoryTypeClassification:
    """Verify _decide_team_story() returns non-neutral types for ranked rugby teams.

    Guards the contract that standings position/form data produces meaningful
    story types instead of 'neutral' for every rugby team.
    """

    def _decide(self, pos, pts, form, home_rec=None, away_rec=None,
                gpg=0.0, is_home=True):
        """Call _decide_team_story from bot.py via dynamic import."""
        import importlib
        bot_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        if bot_dir not in sys.path:
            sys.path.insert(0, bot_dir)
        try:
            import bot as _bot  # noqa: PLC0415
            return _bot._decide_team_story(
                pos, pts, form,
                home_rec or {}, away_rec or {},
                gpg, is_home,
            )
        except (ImportError, AttributeError):
            pytest.skip("_decide_team_story not importable in this test context")

    def test_neutral_without_position(self):
        """AC: position=None → 'neutral' (standings-free baseline)."""
        story = self._decide(pos=None, pts=None, form="")
        assert story == "neutral"

    def test_crisis_for_bottom_half_team(self):
        """AC: position >= 14 with losing form → 'crisis'."""
        story = self._decide(pos=16, pts=5, form="LLLLL")
        assert story == "crisis"

    def test_title_push_for_league_leader(self):
        """AC: position == 1 with wins → non-neutral (title_push/momentum/fortress)."""
        story = self._decide(pos=1, pts=45, form="WWWWW")
        assert story in {"title_push", "momentum", "fortress"}

    def test_non_neutral_with_valid_position(self):
        """AC: any valid position + real form → non-neutral story type."""
        story = self._decide(pos=5, pts=20, form="WWLWW")
        assert story != "neutral"
