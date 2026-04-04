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
