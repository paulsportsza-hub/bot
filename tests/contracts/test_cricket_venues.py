"""Contract tests for BUILD-ENRICH-07 — Cricket Venue Resolution.

Guards:
  1. _DDL_VENUES / _ensure_tables() creates sportmonks_venues table
  2. _get_cached_venue() returns None when not present, dict when cached
  3. _fetch_and_cache_venue() stores venue in DB and returns correct dict
  4. resolve_venues() resolves uncached IDs, skips cached, is idempotent
  5. _fetch_fixture_from_db() returns venue_name + venue_city via JOIN
  6. _fetch_venue_from_db() returns venue dict using readonly connection
  7. fetch_context() includes venue name in returned context dict (DB-only path)
"""

import asyncio
import os
import sqlite3
import sys
import tempfile
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
# Also add /home/paulsportsza so scrapers.* is importable (scrapers/ lives at the parent of bot/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))


# ── DB helpers ────────────────────────────────────────────────────────────────


def _make_scraper_db(db_path: str, with_venue: bool = False) -> None:
    """Create scrapers-side DB with sportmonks tables + optional venue row."""
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS api_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_name TEXT,
            endpoint TEXT,
            called_at TEXT,
            status_code INTEGER,
            cached INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS sportmonks_fixtures (
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
        CREATE TABLE IF NOT EXISTS sportmonks_teams (
            team_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            code TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS cricket_standings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league_name TEXT,
            season_id INTEGER,
            team_name TEXT,
            team_id INTEGER,
            position INTEGER,
            played INTEGER,
            won INTEGER,
            lost INTEGER,
            no_result INTEGER,
            points INTEGER,
            nrr REAL,
            scraped_at TEXT,
            UNIQUE(season_id, team_id)
        );
        CREATE TABLE IF NOT EXISTS sportmonks_venues (
            venue_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            city TEXT,
            country_id INTEGER,
            updated_at TEXT
        );
        INSERT INTO sportmonks_teams VALUES (6,  'Mumbai Indians',     'MI',  '2026-04-04');
        INSERT INTO sportmonks_teams VALUES (2,  'Chennai Super Kings','CSK', '2026-04-04');
        INSERT INTO sportmonks_fixtures VALUES (
            1, 69999, 'IPL', 1, 1795,
            datetime('now', '+2 days'), 'T20', 'NS',
            'Mumbai Indians', 6, 'Chennai Super Kings', 2,
            46, NULL, NULL, '2026-04-04'
        );
        """
    )
    if with_venue:
        conn.execute(
            "INSERT OR REPLACE INTO sportmonks_venues (venue_id, name, city, country_id, updated_at) "
            "VALUES (46, 'Wankhede Stadium', 'Mumbai', 153732, '2026-04-04')"
        )
    conn.commit()
    conn.close()


# ── 1. DDL / _ensure_tables ───────────────────────────────────────────────────


class TestEnsureTablesVenues:
    """sportmonks_venues table is created by _ensure_tables()."""

    def test_ensure_tables_creates_venues_table(self):
        from scrapers.sportmonks_cricket import _ensure_tables
        from scrapers.db_connect import connect_odds_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = connect_odds_db(db_path)
            _ensure_tables(conn)
            # Check table exists
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='sportmonks_venues'"
            ).fetchone()
            assert row is not None, "sportmonks_venues table not created"
            # Check schema has required columns
            cols = {
                r[1] for r in conn.execute("PRAGMA table_info(sportmonks_venues)").fetchall()
            }
            assert "venue_id" in cols
            assert "name" in cols
            assert "city" in cols
            assert "country_id" in cols
            conn.close()
        finally:
            os.unlink(db_path)


# ── 2. _get_cached_venue ─────────────────────────────────────────────────────


class TestGetCachedVenue:
    """_get_cached_venue() returns None when absent, dict when present."""

    def _make_conn(self, db_path: str) -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE sportmonks_venues "
            "(venue_id INTEGER PRIMARY KEY, name TEXT, city TEXT, country_id INTEGER, updated_at TEXT)"
        )
        conn.commit()
        return conn

    def test_returns_none_when_not_present(self):
        from scrapers.sportmonks_cricket import _get_cached_venue

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = self._make_conn(db_path)
            result = _get_cached_venue(conn, 46)
            conn.close()
            assert result is None
        finally:
            os.unlink(db_path)

    def test_returns_dict_when_present(self):
        from scrapers.sportmonks_cricket import _get_cached_venue

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = self._make_conn(db_path)
            conn.execute(
                "INSERT INTO sportmonks_venues VALUES (46, 'Wankhede Stadium', 'Mumbai', 153732, '2026-04-04')"
            )
            conn.commit()
            result = _get_cached_venue(conn, 46)
            conn.close()
            assert result is not None
            assert result["name"] == "Wankhede Stadium"
            assert result["city"] == "Mumbai"
            assert result["country_id"] == 153732
        finally:
            os.unlink(db_path)

    def test_returns_none_for_different_venue_id(self):
        from scrapers.sportmonks_cricket import _get_cached_venue

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = self._make_conn(db_path)
            conn.execute(
                "INSERT INTO sportmonks_venues VALUES (46, 'Wankhede Stadium', 'Mumbai', 153732, '2026-04-04')"
            )
            conn.commit()
            result = _get_cached_venue(conn, 999)
            conn.close()
            assert result is None
        finally:
            os.unlink(db_path)


# ── 3. _fetch_and_cache_venue ─────────────────────────────────────────────────


class TestFetchAndCacheVenue:
    """_fetch_and_cache_venue() stores venue in DB and returns correct dict."""

    _MOCK_API_BODY = {
        "data": {
            "resource": "venues",
            "id": 46,
            "country_id": 153732,
            "name": "Wankhede Stadium",
            "city": "Mumbai",
            "capacity": 32000,
            "floodlight": True,
            "updated_at": "2018-10-10T15:57:10.000000Z",
        }
    }

    def _make_conn(self, db_path: str) -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE sportmonks_venues "
            "(venue_id INTEGER PRIMARY KEY, name TEXT, city TEXT, country_id INTEGER, updated_at TEXT)"
        )
        conn.execute(
            "CREATE TABLE api_usage "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, api_name TEXT, endpoint TEXT, "
            "called_at TEXT, status_code INTEGER, cached INTEGER DEFAULT 0)"
        )
        conn.commit()
        return conn

    def test_stores_and_returns_venue(self):
        from scrapers.sportmonks_cricket import _fetch_and_cache_venue, _get_cached_venue

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = self._make_conn(db_path)
            with patch(
                "scrapers.sportmonks_cricket._api_get",
                return_value=(200, self._MOCK_API_BODY),
            ):
                result = _fetch_and_cache_venue(conn, 46, "fake_token")

            assert result["name"] == "Wankhede Stadium"
            assert result["city"] == "Mumbai"
            assert result["country_id"] == 153732

            # Verify row is in DB
            cached = _get_cached_venue(conn, 46)
            assert cached is not None
            assert cached["name"] == "Wankhede Stadium"
            conn.close()
        finally:
            os.unlink(db_path)

    def test_returns_fallback_on_api_error(self):
        from scrapers.sportmonks_cricket import _fetch_and_cache_venue

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = self._make_conn(db_path)
            with patch(
                "scrapers.sportmonks_cricket._api_get",
                side_effect=RuntimeError("Network error"),
            ):
                result = _fetch_and_cache_venue(conn, 46, "fake_token")

            assert "name" in result
            assert "46" in result["name"]  # fallback includes venue_id
            conn.close()
        finally:
            os.unlink(db_path)

    def test_idempotent_upsert(self):
        """Re-calling with same venue_id replaces the existing row cleanly."""
        from scrapers.sportmonks_cricket import _fetch_and_cache_venue, _get_cached_venue

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = self._make_conn(db_path)
            with patch(
                "scrapers.sportmonks_cricket._api_get",
                return_value=(200, self._MOCK_API_BODY),
            ):
                _fetch_and_cache_venue(conn, 46, "fake_token")
                _fetch_and_cache_venue(conn, 46, "fake_token")

            rows = conn.execute(
                "SELECT COUNT(*) FROM sportmonks_venues WHERE venue_id = 46"
            ).fetchone()[0]
            assert rows == 1, "Expected exactly one row after two calls (INSERT OR REPLACE)"
            conn.close()
        finally:
            os.unlink(db_path)


# ── 4. resolve_venues ────────────────────────────────────────────────────────


class TestResolveVenues:
    """resolve_venues() resolves uncached venue IDs, skips cached, is idempotent."""

    _MOCK_API_BODY = {
        "data": {
            "id": 46,
            "country_id": 153732,
            "name": "Wankhede Stadium",
            "city": "Mumbai",
            "capacity": 32000,
        }
    }

    def test_resolves_uncached_venues(self):
        from scrapers.sportmonks_cricket import resolve_venues

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _make_scraper_db(db_path, with_venue=False)
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS api_usage "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, api_name TEXT, endpoint TEXT, "
                "called_at TEXT, status_code INTEGER, cached INTEGER DEFAULT 0)"
            )
            conn.commit()

            with patch(
                "scrapers.sportmonks_cricket._api_get",
                return_value=(200, self._MOCK_API_BODY),
            ):
                summary = resolve_venues(conn, "fake_token")

            assert summary["total"] == 1       # fixture has venue_id=46
            assert summary["fetched"] == 1
            assert summary["already_cached"] == 0
            assert summary["errors"] == []

            # Verify stored
            row = conn.execute(
                "SELECT name, city FROM sportmonks_venues WHERE venue_id = 46"
            ).fetchone()
            assert row is not None
            assert row[0] == "Wankhede Stadium"
            conn.close()
        finally:
            os.unlink(db_path)

    def test_skips_already_cached_venues(self):
        from scrapers.sportmonks_cricket import resolve_venues

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _make_scraper_db(db_path, with_venue=True)  # venue_id=46 already cached
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS api_usage "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, api_name TEXT, endpoint TEXT, "
                "called_at TEXT, status_code INTEGER, cached INTEGER DEFAULT 0)"
            )
            conn.commit()

            with patch(
                "scrapers.sportmonks_cricket._api_get",
                return_value=(200, self._MOCK_API_BODY),
            ) as mock_api:
                summary = resolve_venues(conn, "fake_token")

            assert summary["already_cached"] == 1
            assert summary["fetched"] == 0
            mock_api.assert_not_called()  # no API calls made
            conn.close()
        finally:
            os.unlink(db_path)

    def test_idempotent_second_call(self):
        """Running resolve_venues twice does not duplicate rows or make extra API calls."""
        from scrapers.sportmonks_cricket import resolve_venues

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _make_scraper_db(db_path, with_venue=False)
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS api_usage "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, api_name TEXT, endpoint TEXT, "
                "called_at TEXT, status_code INTEGER, cached INTEGER DEFAULT 0)"
            )
            conn.commit()

            with patch(
                "scrapers.sportmonks_cricket._api_get",
                return_value=(200, self._MOCK_API_BODY),
            ) as mock_api:
                resolve_venues(conn, "fake_token")
                summary2 = resolve_venues(conn, "fake_token")

            # Second call should hit cache, not API
            assert summary2["already_cached"] == 1
            assert summary2["fetched"] == 0
            assert mock_api.call_count == 1  # only called once total
            conn.close()
        finally:
            os.unlink(db_path)

    def test_no_venues_returns_zero_counts(self):
        """Handles DB with no venue_ids gracefully."""
        from scrapers.sportmonks_cricket import resolve_venues
        from scrapers.db_connect import connect_odds_db
        from scrapers.sportmonks_cricket import _ensure_tables

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = connect_odds_db(db_path)
            _ensure_tables(conn)
            # No fixtures inserted — no venue_ids to resolve
            summary = resolve_venues(conn, "fake_token")
            assert summary["total"] == 0
            assert summary["fetched"] == 0
            assert summary["already_cached"] == 0
            conn.close()
        finally:
            os.unlink(db_path)


# ── 5. _fetch_fixture_from_db returns venue_name + venue_city ─────────────────


class TestFetchFixtureFromDBVenue:
    """_fetch_fixture_from_db() returns venue_name and venue_city via JOIN."""

    def test_venue_name_returned_when_venue_cached(self):
        from fetchers.cricket_fetcher import _fetch_fixture_from_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _make_scraper_db(db_path, with_venue=True)
            result = _fetch_fixture_from_db(
                "Mumbai Indians", "Chennai Super Kings", "ipl",
                scrapers_db=db_path,
            )
            assert result is not None
            assert result["venue_name"] == "Wankhede Stadium"
            assert result["venue_city"] == "Mumbai"
        finally:
            os.unlink(db_path)

    def test_venue_name_empty_when_venue_not_cached(self):
        from fetchers.cricket_fetcher import _fetch_fixture_from_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _make_scraper_db(db_path, with_venue=False)
            result = _fetch_fixture_from_db(
                "Mumbai Indians", "Chennai Super Kings", "ipl",
                scrapers_db=db_path,
            )
            assert result is not None
            assert result["venue_name"] == ""
            assert result["venue_city"] == ""
        finally:
            os.unlink(db_path)

    def test_venue_id_included_in_result(self):
        from fetchers.cricket_fetcher import _fetch_fixture_from_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _make_scraper_db(db_path, with_venue=False)
            result = _fetch_fixture_from_db(
                "Mumbai Indians", "Chennai Super Kings", "ipl",
                scrapers_db=db_path,
            )
            assert result is not None
            assert result["venue_id"] == 46
        finally:
            os.unlink(db_path)


# ── 6. _fetch_venue_from_db ───────────────────────────────────────────────────


class TestFetchVenueFromDB:
    """_fetch_venue_from_db() returns venue dict via readonly connection."""

    def test_returns_venue_when_present(self):
        from fetchers.cricket_fetcher import _fetch_venue_from_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _make_scraper_db(db_path, with_venue=True)
            result = _fetch_venue_from_db(46, scrapers_db=db_path)
            assert result is not None
            assert result["name"] == "Wankhede Stadium"
            assert result["city"] == "Mumbai"
        finally:
            os.unlink(db_path)

    def test_returns_none_when_absent(self):
        from fetchers.cricket_fetcher import _fetch_venue_from_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _make_scraper_db(db_path, with_venue=False)
            result = _fetch_venue_from_db(46, scrapers_db=db_path)
            assert result is None
        finally:
            os.unlink(db_path)

    def test_returns_none_for_unknown_venue_id(self):
        from fetchers.cricket_fetcher import _fetch_venue_from_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _make_scraper_db(db_path, with_venue=True)
            result = _fetch_venue_from_db(9999, scrapers_db=db_path)
            assert result is None
        finally:
            os.unlink(db_path)


# ── 7. fetch_context() includes venue in context dict ────────────────────────


class TestFetchContextVenue:
    """fetch_context() returns venue name in context dict (DB-only path)."""

    def _make_bot_db(self, db_path: str) -> None:
        """Minimal bot-side DB (api_cache table required by base_fetcher)."""
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS api_cache (
                cache_key TEXT PRIMARY KEY,
                response_json TEXT,
                api_name TEXT,
                entity_id TEXT,
                endpoint TEXT,
                cached_at TEXT,
                ttl_hours REAL,
                expires_at TEXT
            );
            """
        )
        conn.commit()
        conn.close()

    def test_venue_in_context_when_venue_cached(self):
        """fetch_context() returns non-empty venue when sportmonks_venues has the row.

        Mocks _fetch_fixture_from_db to return a fixture dict with venue_name + venue_city
        already resolved (as if the JOIN succeeded), then checks the context dict.
        """
        from fetchers.cricket_fetcher import CricketFetcher

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as bot_f:
            bot_db = bot_f.name

        _mock_fixture = {
            "data_available": True,
            "home_name": "Mumbai Indians",
            "away_name": "Chennai Super Kings",
            "competition": "IPL",
            "format": "T20",
            "match_date": "2026-04-06 14:00:00",
            "home_team_id": 6,
            "away_team_id": 2,
            "venue_id": 46,
            "venue_name": "Wankhede Stadium",
            "venue_city": "Mumbai",
        }

        try:
            self._make_bot_db(bot_db)
            fetcher = CricketFetcher()

            with patch(
                "fetchers.cricket_fetcher._fetch_fixture_from_db",
                return_value=_mock_fixture,
            ), patch(
                "fetchers.cricket_fetcher._get_api_token",
                return_value="",
            ), patch(
                "fetchers.cricket_fetcher._fetch_standings_from_db",
                return_value={"home_standing": None, "away_standing": None},
            ), patch(
                "fetchers.cricket_fetcher._get_elo_ratings",
                return_value=(None, None),
            ):
                result = asyncio.get_event_loop().run_until_complete(
                    fetcher.fetch_context(
                        "Mumbai Indians",
                        "Chennai Super Kings",
                        "ipl",
                        db_path=bot_db,
                    )
                )

            assert result.context.get("venue"), (
                f"Expected non-empty venue in context, got: {result.context.get('venue')!r}"
            )
            assert "Wankhede Stadium" in result.context["venue"]
        finally:
            os.unlink(bot_db)

    def test_venue_includes_city_when_available(self):
        """venue field is formatted as 'Name, City' when city is present."""
        from fetchers.cricket_fetcher import _fetch_fixture_from_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _make_scraper_db(db_path, with_venue=True)
            result = _fetch_fixture_from_db(
                "Mumbai Indians", "Chennai Super Kings", "ipl",
                scrapers_db=db_path,
            )
            assert result is not None
            # venue_name and venue_city both present — fetch_context combines them
            assert result["venue_name"] == "Wankhede Stadium"
            assert result["venue_city"] == "Mumbai"
        finally:
            os.unlink(db_path)
