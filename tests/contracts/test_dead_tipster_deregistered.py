"""Contract tests: FIX-SOURCE-REGISTRY-DEREGISTER-DEAD-TIPSTERS-01 (2026-04-30)

Verify AfricaPicks, Forebet, BetMMA are fully retired:
  1. source_registry has enabled=0 for all three
  2. tipster_consensus.EXCLUDED_SOURCES excludes them (no consensus contribution)
  3. runner.SCRAPERS has fn=None for all three (no active scrape function)
"""
import sqlite3
import sys

import pytest

sys.path.insert(0, "/home/paulsportsza")

ODDS_DB = "/home/paulsportsza/scrapers/odds.db"
DEAD_SOURCE_IDS = {"tipster_africapicks", "tipster_forebet", "tipster_betmma"}
DEAD_SCRAPER_NAMES = {"africapicks", "forebet", "betmma"}


# ---------------------------------------------------------------------------
# 1. source_registry: all three must be enabled=0
# ---------------------------------------------------------------------------

def test_dead_tipsters_disabled_in_source_registry():
    conn = sqlite3.connect(ODDS_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT source_id, enabled FROM source_registry "
        "WHERE source_id IN ('tipster_africapicks','tipster_forebet','tipster_betmma')"
    ).fetchall()
    conn.close()

    assert len(rows) == 3, "All 3 dead tipsters must have rows in source_registry"
    for row in rows:
        assert row["enabled"] == 0, (
            f"{row['source_id']} is still enabled=1 in source_registry — "
            "health monitor will fire false-positive stale alerts"
        )


def test_dead_tipsters_have_retirement_notes():
    conn = sqlite3.connect(ODDS_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT source_id, notes FROM source_registry "
        "WHERE source_id IN ('tipster_africapicks','tipster_forebet','tipster_betmma')"
    ).fetchall()
    conn.close()

    for row in rows:
        assert row["notes"], f"{row['source_id']} missing retirement notes in source_registry"
        assert "Retired" in row["notes"], (
            f"{row['source_id']} notes don't contain 'Retired': {row['notes']}"
        )


# ---------------------------------------------------------------------------
# 2. tipster_consensus.EXCLUDED_SOURCES: dead sources must be excluded
# ---------------------------------------------------------------------------

def test_dead_tipsters_in_consensus_excluded_sources():
    from scrapers.tipsters.tipster_consensus import EXCLUDED_SOURCES
    for name in DEAD_SCRAPER_NAMES:
        assert name in EXCLUDED_SOURCES, (
            f"'{name}' not in tipster_consensus.EXCLUDED_SOURCES — "
            "dead source may contaminate consensus with stale predictions"
        )


# ---------------------------------------------------------------------------
# 3. runner.SCRAPERS: all three must have fn=None (no active scrape function)
# ---------------------------------------------------------------------------

def test_dead_tipsters_have_no_scraper_function():
    from scrapers.tipsters.runner import SCRAPERS
    for name in DEAD_SCRAPER_NAMES:
        assert name in SCRAPERS, f"'{name}' missing from runner.SCRAPERS — add with fn=None"
        assert SCRAPERS[name]["fn"] is None, (
            f"runner.SCRAPERS['{name}']['fn'] is not None — retired scraper still active"
        )
