"""Contract tests — MMAFetcher queries mma_fixtures and returns data_available=True.

W84-BUILD: MMAFetcher.fetch_context() must:
- Return data_available=True when mma_fixtures has a matching upcoming fight
- Map fighter1_name → home_team, fighter2_name → away_team
- Populate competition from event_slug, weight_class from DB
- Return data_available=False when no fixture found and no API (no regression)
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from unittest.mock import patch

# Ensure scrapers is importable (mirrors test_edge_contracts.py pattern)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ensure_scrapers_importable  # noqa: E402
ensure_scrapers_importable()

import fetchers.mma_fetcher as _mod  # noqa: E402
from fetchers.mma_fetcher import MMAFetcher, _query_mma_fixture  # noqa: E402


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_fixture_db(path: str, days_offset: int = 7) -> None:
    """Create a minimal mma_fixtures DB with one upcoming fight."""
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE mma_fixtures (
               id INTEGER PRIMARY KEY,
               api_id INTEGER NOT NULL,
               event_slug TEXT,
               fight_date TEXT NOT NULL,
               weight_class TEXT,
               status TEXT,
               fighter1_name TEXT NOT NULL,
               fighter1_api_id INTEGER,
               fighter2_name TEXT NOT NULL,
               fighter2_api_id INTEGER,
               winner_name TEXT,
               method TEXT,
               scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
           )"""
    )
    conn.execute(
        f"""INSERT INTO mma_fixtures
               (api_id, event_slug, fight_date, weight_class, status,
                fighter1_name, fighter2_name)
            VALUES (?, ?, date('now', '+{days_offset} days'), ?, ?, ?, ?)""",
        (1001, "UFC Fight Night: Makhachev vs Tsarukyan", "Lightweight",
         "Scheduled", "Islam Makhachev", "Arman Tsarukyan"),
    )
    conn.commit()
    conn.close()


# ── _query_mma_fixture unit tests ──────────────────────────────────────────────

class TestQueryMMAFixture:
    def test_returns_matching_fixture(self, tmp_path):
        """Returns fixture dict when fighter names match exactly."""
        db = str(tmp_path / "odds.db")
        _make_fixture_db(db)

        with patch.object(_mod, "_SCRAPERS_DB", db):
            result = _query_mma_fixture("Islam Makhachev", "Arman Tsarukyan")

        assert result is not None
        assert result["fighter1_name"] == "Islam Makhachev"
        assert result["fighter2_name"] == "Arman Tsarukyan"
        assert result["competition"] == "UFC Fight Night: Makhachev vs Tsarukyan"
        assert result["weight_class"] == "Lightweight"

    def test_handles_swapped_names(self, tmp_path):
        """Returns fixture with fighter1_name=home when names are passed in reverse."""
        db = str(tmp_path / "odds.db")
        _make_fixture_db(db)

        with patch.object(_mod, "_SCRAPERS_DB", db):
            result = _query_mma_fixture("Arman Tsarukyan", "Islam Makhachev")

        assert result is not None
        assert result["fighter1_name"] == "Arman Tsarukyan"
        assert result["fighter2_name"] == "Islam Makhachev"

    def test_returns_none_for_unknown_fighters(self, tmp_path):
        """Returns None when no fixture matches the given names."""
        db = str(tmp_path / "odds.db")
        _make_fixture_db(db)

        with patch.object(_mod, "_SCRAPERS_DB", db):
            result = _query_mma_fixture("Unknown Fighter", "Also Unknown")

        assert result is None

    def test_excludes_cancelled_fights(self, tmp_path):
        """Cancelled fights are not returned."""
        db = str(tmp_path / "odds.db")
        conn = sqlite3.connect(db)
        conn.execute(
            """CREATE TABLE mma_fixtures (
                   id INTEGER PRIMARY KEY, api_id INTEGER NOT NULL,
                   event_slug TEXT, fight_date TEXT NOT NULL,
                   weight_class TEXT, status TEXT,
                   fighter1_name TEXT NOT NULL, fighter1_api_id INTEGER,
                   fighter2_name TEXT NOT NULL, fighter2_api_id INTEGER,
                   winner_name TEXT, method TEXT,
                   scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
               )"""
        )
        conn.execute(
            "INSERT INTO mma_fixtures (api_id, fight_date, status, fighter1_name, fighter2_name) "
            "VALUES (?, date('now', '+3 days'), 'Cancelled', ?, ?)",
            (999, "Islam Makhachev", "Arman Tsarukyan"),
        )
        conn.commit()
        conn.close()

        with patch.object(_mod, "_SCRAPERS_DB", db):
            result = _query_mma_fixture("Islam Makhachev", "Arman Tsarukyan")

        assert result is None

    def test_returns_none_on_db_error(self):
        """Returns None gracefully when the DB path does not exist."""
        with patch.object(_mod, "_SCRAPERS_DB", "/nonexistent/path/odds.db"):
            result = _query_mma_fixture("Fighter A", "Fighter B")
        assert result is None


# ── MMAFetcher.fetch_context integration tests ─────────────────────────────────

class TestMMAFetcherDataAvailable:
    def test_data_available_true_when_fixture_found(self):
        """fetch_context returns data_available=True when mma_fixtures has the fight."""
        fixture = {
            "fighter1_name": "Islam Makhachev",
            "fighter2_name": "Arman Tsarukyan",
            "competition": "UFC Fight Night: Makhachev vs Tsarukyan",
            "fight_date": "2026-04-11",
            "weight_class": "Lightweight",
        }
        fetcher = MMAFetcher()

        with patch.object(_mod, "_query_mma_fixture", return_value=fixture), \
             patch.object(_mod, "_get_api_key", return_value=""):
            result = asyncio.run(
                fetcher.fetch_context("Islam Makhachev", "Arman Tsarukyan", "mma")
            )

        assert result.context["data_available"] is True

    def test_home_name_maps_to_fighter1(self):
        """home_team in context comes from fighter1_name in the DB fixture."""
        fixture = {
            "fighter1_name": "Islam Makhachev",
            "fighter2_name": "Arman Tsarukyan",
            "competition": "UFC Test",
            "fight_date": "2026-04-11",
            "weight_class": "Lightweight",
        }
        fetcher = MMAFetcher()

        with patch.object(_mod, "_query_mma_fixture", return_value=fixture), \
             patch.object(_mod, "_get_api_key", return_value=""):
            result = asyncio.run(
                fetcher.fetch_context("Islam Makhachev", "Arman Tsarukyan", "mma")
            )

        assert result.context["home_team"]["name"] == "Islam Makhachev"
        assert result.context["away_team"]["name"] == "Arman Tsarukyan"

    def test_competition_from_event_slug(self):
        """competition is populated from event_slug in the DB fixture."""
        fixture = {
            "fighter1_name": "Islam Makhachev",
            "fighter2_name": "Arman Tsarukyan",
            "competition": "UFC Fight Night: Makhachev vs Tsarukyan",
            "fight_date": "2026-04-11",
            "weight_class": "Lightweight",
        }
        fetcher = MMAFetcher()

        with patch.object(_mod, "_query_mma_fixture", return_value=fixture), \
             patch.object(_mod, "_get_api_key", return_value=""):
            result = asyncio.run(
                fetcher.fetch_context("Islam Makhachev", "Arman Tsarukyan", "mma")
            )

        assert result.context["competition"] == "UFC Fight Night: Makhachev vs Tsarukyan"

    def test_weight_class_from_db(self):
        """weight_class is populated from the DB fixture."""
        fixture = {
            "fighter1_name": "Islam Makhachev",
            "fighter2_name": "Arman Tsarukyan",
            "competition": "UFC Test",
            "fight_date": "2026-04-11",
            "weight_class": "Lightweight",
        }
        fetcher = MMAFetcher()

        with patch.object(_mod, "_query_mma_fixture", return_value=fixture), \
             patch.object(_mod, "_get_api_key", return_value=""):
            result = asyncio.run(
                fetcher.fetch_context("Islam Makhachev", "Arman Tsarukyan", "mma")
            )

        assert result.context["weight_class"] == "Lightweight"

    def test_data_available_false_no_fixture_no_api(self):
        """fetch_context returns data_available=False when no fixture and no API key."""
        fetcher = MMAFetcher()

        with patch.object(_mod, "_query_mma_fixture", return_value=None), \
             patch.object(_mod, "_get_api_key", return_value=""):
            result = asyncio.run(
                fetcher.fetch_context("Fighter A", "Fighter B", "mma")
            )

        assert result.context["data_available"] is False


# ── BUILD-ENRICH-06: mma_fighters table write + fetcher reads ─────────────────

class TestMMAFighterTableWrite:
    """Contract tests for the mma_fighters DB table and write path (W81-DBLOCK)."""

    def _make_fighters_db(self, path: str) -> None:
        """Create odds.db with both mma_fixtures and mma_fighters tables."""
        conn = sqlite3.connect(path)
        conn.execute(
            """CREATE TABLE mma_fixtures (
                   id INTEGER PRIMARY KEY,
                   api_id INTEGER NOT NULL UNIQUE,
                   event_slug TEXT,
                   fight_date TEXT NOT NULL,
                   weight_class TEXT,
                   status TEXT,
                   fighter1_name TEXT NOT NULL,
                   fighter1_api_id INTEGER,
                   fighter2_name TEXT NOT NULL,
                   fighter2_api_id INTEGER,
                   winner_name TEXT,
                   method TEXT,
                   scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
               )"""
        )
        conn.execute(
            """CREATE TABLE mma_fighters (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   api_id INTEGER NOT NULL UNIQUE,
                   name TEXT NOT NULL,
                   record_wins INTEGER,
                   record_losses INTEGER,
                   record_draws INTEGER,
                   reach TEXT,
                   stance TEXT,
                   weight_class TEXT,
                   ranking INTEGER,
                   scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS api_usage (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   api_name TEXT NOT NULL,
                   endpoint TEXT,
                   status_code INTEGER,
                   cached INTEGER DEFAULT 0,
                   called_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
               )"""
        )
        conn.commit()
        conn.close()

    def test_upsert_fighter_writes_correct_row(self, tmp_path):
        """_upsert_fighter() writes all fields to mma_fighters via connect_odds_db()."""
        import sys
        scrapers_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        if scrapers_path not in sys.path:
            sys.path.insert(0, scrapers_path)
        from scrapers.api_sports_mma import _upsert_fighter
        from scrapers.db_connect import connect_odds_db

        db = str(tmp_path / "odds.db")
        self._make_fighters_db(db)

        conn = connect_odds_db(db)
        try:
            _upsert_fighter(conn, {
                "api_id": 42,
                "name": "Islam Makhachev",
                "record_wins": 26,
                "record_losses": 2,
                "record_draws": 0,
                "reach": "71",
                "stance": "Southpaw",
                "weight_class": "Lightweight",
                "ranking": 1,
            })
            conn.commit()
            row = conn.execute(
                "SELECT * FROM mma_fighters WHERE api_id = 42"
            ).fetchone()
        finally:
            conn.close()

        assert row is not None
        # columns: id, api_id, name, record_wins, record_losses, record_draws,
        #          reach, stance, weight_class, ranking, scraped_at
        assert row[1] == 42          # api_id
        assert row[2] == "Islam Makhachev"  # name
        assert row[3] == 26          # record_wins
        assert row[4] == 2           # record_losses
        assert row[5] == 0           # record_draws
        assert row[8] == "Lightweight"  # weight_class
        assert row[9] == 1           # ranking

    def test_upsert_fighter_is_idempotent(self, tmp_path):
        """_upsert_fighter() updates existing row on repeat call (no duplicates)."""
        import sys
        scrapers_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        if scrapers_path not in sys.path:
            sys.path.insert(0, scrapers_path)
        from scrapers.api_sports_mma import _upsert_fighter
        from scrapers.db_connect import connect_odds_db

        db = str(tmp_path / "odds.db")
        self._make_fighters_db(db)

        conn = connect_odds_db(db)
        try:
            row_base = {"api_id": 7, "name": "Jon Jones", "record_wins": 27,
                        "record_losses": 1, "record_draws": 0,
                        "reach": "84.5", "stance": "Orthodox",
                        "weight_class": "Heavyweight", "ranking": None}
            _upsert_fighter(conn, row_base)
            conn.commit()
            # Update wins after next fight
            _upsert_fighter(conn, {**row_base, "record_wins": 28})
            conn.commit()
            count = conn.execute("SELECT COUNT(*) FROM mma_fighters WHERE api_id = 7").fetchone()[0]
            wins = conn.execute("SELECT record_wins FROM mma_fighters WHERE api_id = 7").fetchone()[0]
        finally:
            conn.close()

        assert count == 1
        assert wins == 28


class TestMMAFighterRecordMapping:
    """Contract tests for fighter record → form string mapping."""

    def test_format_record_str_standard(self):
        """_format_record_str returns W-L-D string."""
        assert _mod._format_record_str(25, 4, 0) == "25-4-0"

    def test_format_record_str_zeros(self):
        """_format_record_str handles None values as zeros."""
        assert _mod._format_record_str(None, None, None) == "0-0-0"

    def test_format_record_str_draws(self):
        """_format_record_str preserves draw count."""
        assert _mod._format_record_str(10, 2, 3) == "10-2-3"


class TestFetchContextFighterRecordIntegration:
    """Contract: fetch_context() reads mma_fighters and populates home_form + home_position."""

    def _make_fighter_db_with_records(self, path: str) -> None:
        """Create DB with a fixture + fighter records."""
        conn = sqlite3.connect(path)
        conn.execute(
            """CREATE TABLE mma_fixtures (
                   id INTEGER PRIMARY KEY,
                   api_id INTEGER NOT NULL UNIQUE,
                   event_slug TEXT,
                   fight_date TEXT NOT NULL,
                   weight_class TEXT,
                   status TEXT,
                   fighter1_name TEXT NOT NULL,
                   fighter1_api_id INTEGER,
                   fighter2_name TEXT NOT NULL,
                   fighter2_api_id INTEGER,
                   winner_name TEXT,
                   method TEXT,
                   scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
               )"""
        )
        conn.execute(
            """CREATE TABLE mma_fighters (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   api_id INTEGER NOT NULL UNIQUE,
                   name TEXT NOT NULL,
                   record_wins INTEGER,
                   record_losses INTEGER,
                   record_draws INTEGER,
                   reach TEXT,
                   stance TEXT,
                   weight_class TEXT,
                   ranking INTEGER,
                   scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
               )"""
        )
        conn.execute(
            f"""INSERT INTO mma_fixtures
                   (api_id, event_slug, fight_date, weight_class, status,
                    fighter1_name, fighter1_api_id, fighter2_name, fighter2_api_id)
                VALUES (1001, 'UFC 300', date('now', '+7 days'),
                        'Lightweight', 'Scheduled',
                        'Islam Makhachev', 101,
                        'Arman Tsarukyan', 202)"""
        )
        conn.execute(
            """INSERT INTO mma_fighters
                   (api_id, name, record_wins, record_losses, record_draws,
                    reach, stance, weight_class, ranking)
               VALUES (101, 'Islam Makhachev', 26, 2, 0, '71', 'Southpaw', 'Lightweight', 1)"""
        )
        conn.execute(
            """INSERT INTO mma_fighters
                   (api_id, name, record_wins, record_losses, record_draws,
                    reach, stance, weight_class, ranking)
               VALUES (202, 'Arman Tsarukyan', 21, 3, 0, '69', 'Orthodox', 'Lightweight', 4)"""
        )
        conn.commit()
        conn.close()

    def test_fetch_context_populates_form_from_fighters_db(self, tmp_path):
        """fetch_context() sets home_team['form'] from mma_fighters (e.g. '26-2-0')."""
        db = str(tmp_path / "odds.db")
        self._make_fighter_db_with_records(db)
        fetcher = MMAFetcher()

        with patch.object(_mod, "_SCRAPERS_DB", db), \
             patch.object(_mod, "_get_api_key", return_value=""):
            result = asyncio.run(
                fetcher.fetch_context("Islam Makhachev", "Arman Tsarukyan", "mma",
                                      db_path=str(tmp_path / "bot.db"))
            )

        home = result.context["home_team"]
        assert home.get("form") == "26-2-0", f"Expected '26-2-0', got {home.get('form')}"

    def test_fetch_context_populates_position_from_fighters_db(self, tmp_path):
        """fetch_context() sets home_team['position'] from mma_fighters ranking."""
        db = str(tmp_path / "odds.db")
        self._make_fighter_db_with_records(db)
        fetcher = MMAFetcher()

        with patch.object(_mod, "_SCRAPERS_DB", db), \
             patch.object(_mod, "_get_api_key", return_value=""):
            result = asyncio.run(
                fetcher.fetch_context("Islam Makhachev", "Arman Tsarukyan", "mma",
                                      db_path=str(tmp_path / "bot.db"))
            )

        home = result.context["home_team"]
        assert home.get("position") == 1, f"Expected ranking 1, got {home.get('position')}"

    def test_fetch_context_away_team_form(self, tmp_path):
        """fetch_context() also sets away_team['form'] from mma_fighters."""
        db = str(tmp_path / "odds.db")
        self._make_fighter_db_with_records(db)
        fetcher = MMAFetcher()

        with patch.object(_mod, "_SCRAPERS_DB", db), \
             patch.object(_mod, "_get_api_key", return_value=""):
            result = asyncio.run(
                fetcher.fetch_context("Islam Makhachev", "Arman Tsarukyan", "mma",
                                      db_path=str(tmp_path / "bot.db"))
            )

        away = result.context["away_team"]
        assert away.get("form") == "21-3-0", f"Expected '21-3-0', got {away.get('form')}"

    def test_fetch_context_no_fighter_record_no_crash(self, tmp_path):
        """fetch_context() succeeds even when mma_fighters has no matching rows."""
        db = str(tmp_path / "odds.db")
        # Fixture exists but no fighter records
        conn = sqlite3.connect(db)
        conn.execute(
            """CREATE TABLE mma_fixtures (
                   id INTEGER PRIMARY KEY, api_id INTEGER NOT NULL UNIQUE,
                   event_slug TEXT, fight_date TEXT NOT NULL,
                   weight_class TEXT, status TEXT,
                   fighter1_name TEXT NOT NULL, fighter1_api_id INTEGER,
                   fighter2_name TEXT NOT NULL, fighter2_api_id INTEGER,
                   winner_name TEXT, method TEXT,
                   scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
               )"""
        )
        conn.execute(
            """CREATE TABLE mma_fighters (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   api_id INTEGER NOT NULL UNIQUE,
                   name TEXT NOT NULL,
                   record_wins INTEGER, record_losses INTEGER, record_draws INTEGER,
                   reach TEXT, stance TEXT, weight_class TEXT, ranking INTEGER,
                   scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
               )"""
        )
        conn.execute(
            """INSERT INTO mma_fixtures (api_id, fight_date, status,
                   fighter1_name, fighter1_api_id, fighter2_name, fighter2_api_id)
               VALUES (999, date('now', '+3 days'), 'Scheduled',
                       'Alex Pereira', 55, 'Jamahal Hill', 66)"""
        )
        conn.commit()
        conn.close()

        fetcher = MMAFetcher()
        with patch.object(_mod, "_SCRAPERS_DB", db), \
             patch.object(_mod, "_get_api_key", return_value=""):
            result = asyncio.run(
                fetcher.fetch_context("Alex Pereira", "Jamahal Hill", "mma",
                                      db_path=str(tmp_path / "bot.db"))
            )

        # Should still find fixture; fighter_data will lack form/position
        assert result.context["data_available"] is True
        assert result.context["home_team"].get("form") is None
