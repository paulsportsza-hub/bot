"""Contract tests for BUILD-ENRICH-05: cricket_standings write + fetcher read.

Guards:
  1. fetch_standings() upserts rows with correct field mapping (actual API fields)
  2. fetch_standings() is idempotent (double-run produces same row count)
  3. _fetch_standings_from_db() returns position + NRR for a known team_id
  4. _fetch_standings_from_db() returns None standings when table is empty
  5. _fetch_standings_from_db() returns None when both team_ids are None
  6. _decide_team_story() returns non-neutral type when position data available
  7. _decide_team_story() returns 'title_push' for top-2 team with 3+ wins
  8. _decide_team_story() returns 'crisis' for bottom-table team (pos >= 14)
"""

import os
import sqlite3
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_standings_db(db_path: str) -> None:
    """Create cricket_standings (+ supporting tables) with sample IPL data."""
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cricket_standings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league_name TEXT NOT NULL,
            season_id INTEGER NOT NULL,
            team_name TEXT NOT NULL,
            team_id INTEGER NOT NULL,
            position INTEGER,
            played INTEGER,
            won INTEGER,
            lost INTEGER,
            no_result INTEGER,
            points INTEGER,
            nrr REAL,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(season_id, team_id)
        );
        CREATE TABLE IF NOT EXISTS api_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_name TEXT,
            endpoint TEXT,
            called_at TEXT,
            status_code INTEGER,
            cached INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS sportmonks_teams (
            team_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            code TEXT,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO sportmonks_teams VALUES (6,  'Mumbai Indians',     'MI',  '2026-04-04');
        INSERT INTO sportmonks_teams VALUES (2,  'Chennai Super Kings','CSK', '2026-04-04');
        INSERT INTO sportmonks_teams VALUES (4,  'Punjab Kings',       'PBKS','2026-04-04');

        INSERT INTO cricket_standings
            (league_name, season_id, team_name, team_id, position, played, won, lost,
             no_result, points, nrr)
        VALUES
            ('IPL', 1795, 'Punjab Kings',        4, 1, 2, 2, 0, 0, 4,  0.637),
            ('IPL', 1795, 'Chennai Super Kings', 2, 3, 2, 1, 1, 0, 2, -0.050),
            ('IPL', 1795, 'Mumbai Indians',      6, 8, 3, 1, 2, 0, 2, -0.400);
        """
    )
    conn.commit()
    conn.close()


def _make_empty_standings_db(db_path: str) -> None:
    """Create schema but no rows."""
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cricket_standings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league_name TEXT NOT NULL,
            season_id INTEGER NOT NULL,
            team_name TEXT NOT NULL,
            team_id INTEGER NOT NULL,
            position INTEGER,
            played INTEGER,
            won INTEGER,
            lost INTEGER,
            no_result INTEGER,
            points INTEGER,
            nrr REAL,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(season_id, team_id)
        );
        CREATE TABLE IF NOT EXISTS api_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_name TEXT, endpoint TEXT, called_at TEXT,
            status_code INTEGER, cached INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS sportmonks_teams (
            team_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            code TEXT,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
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
        """
    )
    conn.commit()
    conn.close()


# ── Test: standings write ──────────────────────────────────────────────────────


class TestFetchStandingsWrite:
    """Contract: fetch_standings() writes correct data to cricket_standings."""

    def _mock_api_get(self, endpoint, token, params=None):
        """Mock _api_get: return sample standings data for season 1795."""
        if "standings/season/1795" in endpoint:
            return 200, {
                "data": [
                    {
                        "team_id": 4,
                        "position": 1,
                        "played": 2,
                        "won": 2,
                        "lost": 0,
                        "draw": 0,
                        "noresult": 0,
                        "points": 4,
                        "netto_run_rate": 0.637,
                        "season_id": 1795,
                    },
                    {
                        "team_id": 6,
                        "position": 8,
                        "played": 3,
                        "won": 1,
                        "lost": 2,
                        "draw": 0,
                        "noresult": 0,
                        "points": 2,
                        "netto_run_rate": -0.400,
                        "season_id": 1795,
                    },
                ]
            }
        # All other seasons: no data
        return 200, {"data": []}

    def test_upserts_correct_fields(self):
        """fetch_standings() writes position, nrr, played, won, lost with correct values."""
        import unittest.mock as mock
        from scrapers.sportmonks_cricket import fetch_standings

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _make_empty_standings_db(db_path)
            from scrapers.db_connect import connect_odds_db
            conn = connect_odds_db(db_path)

            with mock.patch("scrapers.sportmonks_cricket._api_get", side_effect=self._mock_api_get), \
                 mock.patch("scrapers.sportmonks_cricket._log_api_call"), \
                 mock.patch("scrapers.sportmonks_cricket._resolve_team_name",
                            side_effect=lambda conn, tid, tok: {4: "Punjab Kings", 6: "Mumbai Indians"}.get(tid, f"Team {tid}")):
                summary = fetch_standings(conn, token="test_token")

            conn.close()

            # Verify data written to DB
            verify_conn = sqlite3.connect(db_path)
            row = verify_conn.execute(
                "SELECT position, nrr, played, won, lost, no_result, points, league_name "
                "FROM cricket_standings WHERE team_id = 4 AND season_id = 1795"
            ).fetchone()
            verify_conn.close()

            assert row is not None, "No row written for team_id=4 season_id=1795"
            position, nrr, played, won, lost, no_result, points, league_name = row
            assert position == 1
            assert abs(nrr - 0.637) < 0.001
            assert played == 2
            assert won == 2
            assert lost == 0
            assert no_result == 0
            assert points == 4
            assert league_name == "IPL"
        finally:
            os.unlink(db_path)

    def test_uses_noresult_field_not_no_result(self):
        """fetch_standings() reads 'noresult' (actual API field), not 'no_result'."""
        import unittest.mock as mock
        from scrapers.sportmonks_cricket import fetch_standings

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _make_empty_standings_db(db_path)
            from scrapers.db_connect import connect_odds_db
            conn = connect_odds_db(db_path)

            # Entry has noresult=1, no 'no_result' field (actual API)
            def mock_api(endpoint, token, params=None):
                if "1795" in endpoint:
                    return 200, {"data": [{"team_id": 9, "position": 5, "played": 3,
                                           "won": 2, "lost": 0, "draw": 0, "noresult": 1,
                                           "points": 5, "netto_run_rate": 0.2, "season_id": 1795}]}
                return 200, {"data": []}

            with mock.patch("scrapers.sportmonks_cricket._api_get", side_effect=mock_api), \
                 mock.patch("scrapers.sportmonks_cricket._log_api_call"), \
                 mock.patch("scrapers.sportmonks_cricket._resolve_team_name", return_value="Sunrisers Hyderabad"):
                fetch_standings(conn, token="test_token")

            conn.close()

            verify_conn = sqlite3.connect(db_path)
            row = verify_conn.execute(
                "SELECT no_result FROM cricket_standings WHERE team_id=9"
            ).fetchone()
            verify_conn.close()

            assert row is not None
            assert row[0] == 1, f"no_result should be 1, got {row[0]}"
        finally:
            os.unlink(db_path)

    def test_is_idempotent(self):
        """Double-run of fetch_standings() produces same row count (upsert, not insert)."""
        import unittest.mock as mock
        from scrapers.sportmonks_cricket import fetch_standings

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _make_empty_standings_db(db_path)
            from scrapers.db_connect import connect_odds_db
            conn = connect_odds_db(db_path)

            with mock.patch("scrapers.sportmonks_cricket._api_get", side_effect=self._mock_api_get), \
                 mock.patch("scrapers.sportmonks_cricket._log_api_call"), \
                 mock.patch("scrapers.sportmonks_cricket._resolve_team_name",
                            side_effect=lambda conn, tid, tok: f"Team {tid}"):
                fetch_standings(conn, token="test_token")
                count_after_first = conn.execute(
                    "SELECT COUNT(*) FROM cricket_standings"
                ).fetchone()[0]
                fetch_standings(conn, token="test_token")
                count_after_second = conn.execute(
                    "SELECT COUNT(*) FROM cricket_standings"
                ).fetchone()[0]

            conn.close()

            assert count_after_first == count_after_second, (
                f"Idempotency failed: {count_after_first} rows after first run, "
                f"{count_after_second} after second"
            )
        finally:
            os.unlink(db_path)

    def test_handles_empty_standings_gracefully(self):
        """fetch_standings() handles seasons with no data without crashing."""
        import unittest.mock as mock
        from scrapers.sportmonks_cricket import fetch_standings

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _make_empty_standings_db(db_path)
            from scrapers.db_connect import connect_odds_db
            conn = connect_odds_db(db_path)

            with mock.patch("scrapers.sportmonks_cricket._api_get", return_value=(200, {"data": []})), \
                 mock.patch("scrapers.sportmonks_cricket._log_api_call"):
                summary = fetch_standings(conn, token="test_token")

            conn.close()

            assert isinstance(summary, dict)
            assert summary["total_rows"] == 0
            assert not summary["errors"]
        finally:
            os.unlink(db_path)


# ── Test: fetcher reads standings ─────────────────────────────────────────────


class TestFetchStandingsFromDB:
    """Contract: _fetch_standings_from_db() returns position + NRR from cricket_standings."""

    def test_returns_position_and_nrr_for_known_team(self):
        """Returns position and NRR when team_id exists in cricket_standings."""
        from fetchers.cricket_fetcher import _fetch_standings_from_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _make_standings_db(db_path)
            result = _fetch_standings_from_db(4, 6, scrapers_db=db_path)
            home_standing = result.get("home_standing")
            away_standing = result.get("away_standing")

            assert home_standing is not None, "home_standing should not be None for team_id=4"
            assert home_standing["position"] == 1
            assert abs(home_standing["nrr"] - 0.637) < 0.001

            assert away_standing is not None, "away_standing should not be None for team_id=6"
            assert away_standing["position"] == 8
            assert abs(away_standing["nrr"] - (-0.400)) < 0.001
        finally:
            os.unlink(db_path)

    def test_returns_none_standing_when_table_empty(self):
        """Returns None standings when cricket_standings has no rows."""
        from fetchers.cricket_fetcher import _fetch_standings_from_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _make_empty_standings_db(db_path)
            result = _fetch_standings_from_db(4, 6, scrapers_db=db_path)
            assert result["home_standing"] is None
            assert result["away_standing"] is None
        finally:
            os.unlink(db_path)

    def test_returns_empty_when_both_team_ids_none(self):
        """Returns empty dict when both team_ids are None."""
        from fetchers.cricket_fetcher import _fetch_standings_from_db

        result = _fetch_standings_from_db(None, None)
        assert result["home_standing"] is None
        assert result["away_standing"] is None

    def test_partial_match_when_one_team_not_in_standings(self):
        """Returns standing for known team even when other team is not in DB."""
        from fetchers.cricket_fetcher import _fetch_standings_from_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _make_standings_db(db_path)
            # team_id=9999 does not exist in standings
            result = _fetch_standings_from_db(4, 9999, scrapers_db=db_path)
            assert result["home_standing"] is not None
            assert result["home_standing"]["position"] == 1
            assert result["away_standing"] is None
        finally:
            os.unlink(db_path)

    def test_standing_includes_record_string(self):
        """Standing dict includes pre-formatted record string."""
        from fetchers.cricket_fetcher import _fetch_standings_from_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _make_standings_db(db_path)
            result = _fetch_standings_from_db(4, None, scrapers_db=db_path)
            home = result["home_standing"]
            assert home is not None
            assert "record" in home
            assert "W2" in home["record"]
        finally:
            os.unlink(db_path)


# ── Test: story type classification ───────────────────────────────────────────


class TestStoryTypeClassificationWithPosition:
    """Contract: _decide_team_story() returns non-neutral types when position data available."""

    def _get_story_fn(self):
        """Import _decide_team_story from bot.py."""
        import importlib.util
        bot_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "bot.py",
        )
        spec = importlib.util.spec_from_file_location("bot_module", bot_path)
        bot_module = importlib.util.module_from_spec(spec)
        # Use grep to extract the function rather than importing the full bot
        # (importing bot initialises Sentry + PTB which requires env vars)
        return None  # signal to use direct import approach

    def test_title_push_for_top2_with_wins(self):
        """pos=1, 3+ wins → title_push."""
        import sys
        import types

        # Read _decide_team_story directly without importing the whole bot
        import re

        bot_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "bot.py",
        )
        # Extract the function source and exec it in isolation
        with open(bot_path) as f:
            source = f.read()

        fn_match = re.search(
            r"(def _decide_team_story\(.*?)(?=\ndef |\nclass |\Z)",
            source,
            re.DOTALL,
        )
        assert fn_match, "_decide_team_story not found in bot.py"
        fn_source = fn_match.group(1)
        ns: dict = {}
        exec(fn_source, ns)
        decide = ns["_decide_team_story"]

        # pos=1, 3 wins in form → title_push
        result = decide(pos=1, pts=6, form="WWW", home_rec=None, away_rec=None, gpg=None, is_home=True)
        assert result == "title_push", f"Expected title_push, got {result}"

    def test_crisis_for_bottom_table(self):
        """pos=14, losses dominate → crisis."""
        import re
        bot_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "bot.py",
        )
        with open(bot_path) as f:
            source = f.read()
        fn_match = re.search(
            r"(def _decide_team_story\(.*?)(?=\ndef |\nclass |\Z)",
            source,
            re.DOTALL,
        )
        assert fn_match
        ns: dict = {}
        exec(fn_match.group(1), ns)
        decide = ns["_decide_team_story"]

        result = decide(pos=14, pts=2, form="LLL", home_rec=None, away_rec=None, gpg=None, is_home=False)
        assert result == "crisis", f"Expected crisis, got {result}"

    def test_neutral_without_position_data(self):
        """pos=None, no form data → neutral."""
        import re
        bot_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "bot.py",
        )
        with open(bot_path) as f:
            source = f.read()
        fn_match = re.search(
            r"(def _decide_team_story\(.*?)(?=\ndef |\nclass |\Z)",
            source,
            re.DOTALL,
        )
        assert fn_match
        ns: dict = {}
        exec(fn_match.group(1), ns)
        decide = ns["_decide_team_story"]

        result = decide(pos=None, pts=None, form="", home_rec=None, away_rec=None, gpg=None, is_home=True)
        assert result == "neutral", f"Expected neutral, got {result}"

    def test_non_neutral_for_ipl_top4_team(self):
        """pos=2, winning form (as IPL top-4 qualifier) → non-neutral story type."""
        import re
        bot_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "bot.py",
        )
        with open(bot_path) as f:
            source = f.read()
        fn_match = re.search(
            r"(def _decide_team_story\(.*?)(?=\ndef |\nclass |\Z)",
            source,
            re.DOTALL,
        )
        assert fn_match
        ns: dict = {}
        exec(fn_match.group(1), ns)
        decide = ns["_decide_team_story"]

        result = decide(pos=2, pts=4, form="WW", home_rec=None, away_rec=None, gpg=None, is_home=True)
        assert result != "neutral", f"Expected non-neutral story type for top-4 team, got {result}"
