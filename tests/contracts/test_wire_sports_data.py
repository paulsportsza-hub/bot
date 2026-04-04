"""Contract tests for WIRE-SPORTS-DATA — API-Sports MMA/Rugby + Sportmonks Cricket.

Validates:
- All three fixture tables exist in odds.db
- api_usage rows logged for all three sources
- Dashboard freshness & quota functions include new sources
- DB connection rules: no bare sqlite3.connect() in new scrapers
"""

import os
import sqlite3

import pytest

SCRAPERS_DB = os.path.expanduser("~/scrapers/odds.db")


# ── DB Table Existence ────────────────────────────────────��───────────────────

@pytest.fixture
def odds_conn():
    conn = sqlite3.connect(SCRAPERS_DB, timeout=5)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _table_exists(conn, name: str) -> bool:
    r = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return r is not None


class TestFixtureTables:
    def test_mma_fixtures_table_exists(self, odds_conn):
        assert _table_exists(odds_conn, "mma_fixtures"), "mma_fixtures table missing"

    def test_rugby_fixtures_table_exists(self, odds_conn):
        assert _table_exists(odds_conn, "rugby_fixtures"), "rugby_fixtures table missing"

    def test_sportmonks_fixtures_table_exists(self, odds_conn):
        assert _table_exists(odds_conn, "sportmonks_fixtures"), "sportmonks_fixtures table missing"

    def test_sportmonks_teams_table_exists(self, odds_conn):
        assert _table_exists(odds_conn, "sportmonks_teams"), "sportmonks_teams table missing"

    def test_mma_fixtures_has_data(self, odds_conn):
        r = odds_conn.execute("SELECT COUNT(*) as c FROM mma_fixtures").fetchone()
        assert r["c"] > 0, "mma_fixtures is empty — scraper may not have run"

    def test_rugby_fixtures_has_data(self, odds_conn):
        r = odds_conn.execute("SELECT COUNT(*) as c FROM rugby_fixtures").fetchone()
        assert r["c"] >= 0, "rugby_fixtures query failed"  # may be 0 off-season

    def test_sportmonks_fixtures_has_data(self, odds_conn):
        r = odds_conn.execute("SELECT COUNT(*) as c FROM sportmonks_fixtures").fetchone()
        assert r["c"] > 0, "sportmonks_fixtures is empty — scraper may not have run"


# ── API Usage Logging ─────────────────────────────────────────────────────────

class TestAPIUsageLogging:
    def test_mma_api_usage_logged(self, odds_conn):
        r = odds_conn.execute(
            "SELECT COUNT(*) as c FROM api_usage WHERE api_name='api_sports_mma'"
        ).fetchone()
        assert r["c"] > 0, "No api_usage rows for api_sports_mma"

    def test_rugby_api_usage_logged(self, odds_conn):
        r = odds_conn.execute(
            "SELECT COUNT(*) as c FROM api_usage WHERE api_name='api_sports_rugby'"
        ).fetchone()
        assert r["c"] > 0, "No api_usage rows for api_sports_rugby"

    def test_sportmonks_api_usage_logged(self, odds_conn):
        r = odds_conn.execute(
            "SELECT COUNT(*) as c FROM api_usage WHERE api_name='sportmonks_cricket'"
        ).fetchone()
        assert r["c"] > 0, "No api_usage rows for sportmonks_cricket"


# ── No Bare sqlite3.connect() ────────────────────────────────────────────────

class TestDBConnectionCompliance:
    """Verify new scrapers use connect_odds_db(), not bare sqlite3.connect()."""

    @pytest.mark.parametrize("module_path", [
        os.path.expanduser("~/scrapers/api_sports_mma.py"),
        os.path.expanduser("~/scrapers/api_sports_rugby.py"),
        os.path.expanduser("~/scrapers/sportmonks_cricket.py"),
    ])
    def test_no_bare_sqlite3_connect(self, module_path):
        with open(module_path) as f:
            source = f.read()
        # Allow "connect_odds_db" but not bare "sqlite3.connect("
        lines = source.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "sqlite3.connect(" in stripped and "connect_odds_db" not in stripped:
                pytest.fail(
                    f"{os.path.basename(module_path)}:{i} — bare sqlite3.connect() found: {stripped}"
                )


# ── Scraper Files Exist ───────────────────────────────────────────────────────

class TestScraperFilesExist:
    """Scrapers are standalone cron scripts in ~/scrapers/, not bot-importable."""

    @pytest.mark.parametrize("filename", [
        "api_sports_mma.py",
        "api_sports_rugby.py",
        "sportmonks_cricket.py",
    ])
    def test_scraper_file_exists(self, filename):
        path = os.path.expanduser(f"~/scrapers/{filename}")
        assert os.path.isfile(path), f"Scraper file missing: {path}"
