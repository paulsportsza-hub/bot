"""Tests for scripts/sports_data.py — caching, curated lists, fuzzy matching."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from scripts.sports_data import (
    ALIASES,
    CURATED_LISTS,
    _read_cache,
    _write_cache,
    fuzzy_match_team,
    get_top_teams_for_sport,
)


# ── Curated data integrity ───────────────────────────────

class TestCuratedLists:
    def test_curated_lists_not_empty(self):
        assert len(CURATED_LISTS) > 0

    def test_psl_teams(self):
        psl = CURATED_LISTS.get("soccer_south_africa_premiership", [])
        assert "Kaizer Chiefs" in psl
        assert "Orlando Pirates" in psl
        assert "Mamelodi Sundowns" in psl

    def test_epl_teams(self):
        epl = CURATED_LISTS.get("soccer_epl", [])
        assert "Arsenal" in epl
        assert "Liverpool" in epl

    def test_boxing_fighters(self):
        boxing = CURATED_LISTS.get("Boxing", [])
        assert "Canelo Alvarez" in boxing

    def test_mma_fighters(self):
        mma = CURATED_LISTS.get("Mixed Martial Arts", [])
        assert "Dricus Du Plessis" in mma
        assert "Islam Makhachev" in mma

    def test_rugby_teams(self):
        rugby = CURATED_LISTS.get("Rugby Union", [])
        assert "Springboks" in rugby

    def test_cricket_teams(self):
        cricket = CURATED_LISTS.get("Cricket", [])
        assert "South Africa" in cricket
        assert "India" in cricket

    def test_all_lists_have_items(self):
        for key, lst in CURATED_LISTS.items():
            assert len(lst) > 0, f"CURATED_LISTS[{key!r}] is empty"


class TestAliases:
    def test_aliases_not_empty(self):
        assert len(ALIASES) > 0

    def test_all_keys_lowercase(self):
        for key in ALIASES:
            assert key == key.lower(), f"alias key '{key}' is not lowercase"

    def test_sa_soccer_aliases(self):
        assert ALIASES["chiefs"] == "Kaizer Chiefs"
        assert ALIASES["pirates"] == "Orlando Pirates"
        assert ALIASES["sundowns"] == "Mamelodi Sundowns"
        assert ALIASES["amakhosi"] == "Kaizer Chiefs"

    def test_epl_aliases(self):
        assert ALIASES["gunners"] == "Arsenal"
        assert ALIASES["pool"] == "Liverpool"
        assert ALIASES["red devils"] == "Manchester United"

    def test_boxing_aliases(self):
        assert ALIASES["canelo"] == "Canelo Alvarez"
        assert ALIASES["tank"] == "Gervonta Davis"

    def test_mma_aliases(self):
        assert ALIASES["dricus"] == "Dricus Du Plessis"
        assert ALIASES["poatan"] == "Alex Pereira"

    def test_cricket_aliases(self):
        assert ALIASES["proteas"] == "South Africa"
        assert ALIASES["boks"] == "Springboks"

    def test_rugby_aliases(self):
        assert ALIASES["boks"] == "Springboks"


# ── Caching layer ────────────────────────────────────────

class TestCache:
    def test_write_and_read_cache(self, tmp_path):
        with patch("scripts.sports_data.CACHE_DIR", tmp_path):
            _write_cache("test_key", {"hello": "world"})
            result = _read_cache("test_key", ttl_hours=24)
            assert result == {"hello": "world"}

    def test_cache_expired(self, tmp_path):
        with patch("scripts.sports_data.CACHE_DIR", tmp_path):
            # Write a cache entry with old timestamp
            path = tmp_path / "old_key.json"
            old_time = datetime.now(timezone.utc) - timedelta(hours=25)
            path.write_text(json.dumps({
                "payload": "stale",
                "fetched_at": old_time.isoformat(),
            }))
            result = _read_cache("old_key", ttl_hours=24)
            assert result is None

    def test_cache_fresh(self, tmp_path):
        with patch("scripts.sports_data.CACHE_DIR", tmp_path):
            path = tmp_path / "fresh_key.json"
            now = datetime.now(timezone.utc)
            path.write_text(json.dumps({
                "payload": "fresh",
                "fetched_at": now.isoformat(),
            }))
            result = _read_cache("fresh_key", ttl_hours=24)
            assert result == "fresh"

    def test_cache_miss(self, tmp_path):
        with patch("scripts.sports_data.CACHE_DIR", tmp_path):
            result = _read_cache("nonexistent", ttl_hours=24)
            assert result is None


# ── Fuzzy matching ───────────────────────────────────────

class TestFuzzyMatch:
    KNOWN = [
        "Kaizer Chiefs", "Orlando Pirates", "Mamelodi Sundowns",
        "Arsenal", "Liverpool", "Manchester City", "Chelsea",
    ]

    def test_exact_match(self):
        results = fuzzy_match_team("Arsenal", self.KNOWN)
        assert len(results) == 1
        assert results[0]["name"] == "Arsenal"
        assert results[0]["confidence"] == 100
        assert results[0]["match_type"] == "exact"

    def test_exact_match_case_insensitive(self):
        results = fuzzy_match_team("arsenal", self.KNOWN)
        assert results[0]["name"] == "Arsenal"
        assert results[0]["confidence"] == 100

    def test_alias_match(self):
        results = fuzzy_match_team("gunners", self.KNOWN)
        assert results[0]["name"] == "Arsenal"
        assert results[0]["match_type"] == "alias"
        assert results[0]["confidence"] >= 95

    def test_alias_sa_slang(self):
        results = fuzzy_match_team("amakhosi", self.KNOWN)
        assert results[0]["name"] == "Kaizer Chiefs"
        assert results[0]["match_type"] == "alias"

    def test_fuzzy_typo(self):
        results = fuzzy_match_team("Arsnal", self.KNOWN)
        assert any(r["name"] == "Arsenal" for r in results)

    def test_substring_match(self):
        results = fuzzy_match_team("Chiefs", self.KNOWN)
        assert any(r["name"] == "Kaizer Chiefs" for r in results)

    def test_empty_input(self):
        assert fuzzy_match_team("", self.KNOWN) == []

    def test_empty_known_names(self):
        results = fuzzy_match_team("test", [])
        assert results == []

    def test_max_three_results(self):
        results = fuzzy_match_team("a", self.KNOWN)
        assert len(results) <= 3

    def test_results_sorted_by_confidence(self):
        results = fuzzy_match_team("man", self.KNOWN)
        if len(results) > 1:
            for i in range(len(results) - 1):
                assert results[i]["confidence"] >= results[i + 1]["confidence"]

    def test_alias_not_in_list_still_returned(self):
        """Alias target not in known_names should still return the canonical name."""
        results = fuzzy_match_team("tank", ["Some Other Fighter"])
        assert results[0]["name"] == "Gervonta Davis"
        assert results[0]["match_type"] == "alias"


# ── get_top_teams_for_sport ──────────────────────────────

pytestmark = pytest.mark.asyncio


async def test_top_teams_curated_fallback():
    """When no API data, returns curated list."""
    with patch("scripts.sports_data.fetch_teams_for_sport", new_callable=AsyncMock, return_value=[]):
        result = await get_top_teams_for_sport("Boxing", sport_key=None)
        assert "Canelo Alvarez" in result


async def test_top_teams_api_first():
    """API results take priority over curated."""
    api_teams = ["Team A", "Team B", "Team C"]
    with patch("scripts.sports_data.fetch_teams_for_sport", new_callable=AsyncMock, return_value=api_teams):
        result = await get_top_teams_for_sport("Soccer", sport_key="soccer_epl", limit=3)
        assert result == api_teams


async def test_top_teams_limit():
    """Respects limit parameter."""
    result = await get_top_teams_for_sport("Boxing", sport_key=None, limit=3)
    assert len(result) <= 3
