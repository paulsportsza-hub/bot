"""Contract tests for CLEAN-DATA-v2 fetcher framework.

Guards:
  1. base_fetcher.py exports required symbols
  2. football_fetcher.py exports FootballFetcher
  3. MEP definitions cover all scoped sports
  4. FetchResult returns ESPN-compatible context dict shape
  5. SQLite schema creation works
  6. Horizon bucket classification is correct
  7. FootballFetcher produces ESPN-compatible dict structure
  8. MEP check logic works correctly
"""

import json
import os
import sqlite3
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── Import Guards ─────────────────────────────────────────────────────────────

class TestFetcherImports:
    """Guard: fetcher modules export all required symbols."""

    def test_base_fetcher_imports(self):
        from fetchers.base_fetcher import (
            BaseFetcher,
            FetchResult,
            MEP_DEFINITIONS,
            ensure_schema,
            get_cached_context,
            store_match_context,
            get_cached_api_response,
            store_api_response,
            horizon_bucket,
        )
        assert BaseFetcher is not None
        assert FetchResult is not None
        assert isinstance(MEP_DEFINITIONS, dict)

    def test_football_fetcher_imports(self):
        from fetchers.football_fetcher import (
            FootballFetcher,
            LEAGUE_CONFIG,
            _extract_standings,
            _extract_h2h,
            _extract_injuries,
        )
        assert FootballFetcher is not None
        assert isinstance(LEAGUE_CONFIG, dict)

    def test_fetchers_init_get_fetcher(self):
        from fetchers import get_fetcher
        fetcher = get_fetcher("soccer")
        assert fetcher.sport == "soccer"

    def test_fetchers_init_unknown_sport_raises(self):
        from fetchers import get_fetcher
        with pytest.raises(ValueError, match="No fetcher"):
            get_fetcher("curling")


# ── MEP Definitions ──────────────────────────────────────────────────────────

class TestMEPDefinitions:
    """Guard: MEP definitions cover required sports and horizons."""

    def test_soccer_mep_has_three_horizons(self):
        from fetchers.base_fetcher import MEP_DEFINITIONS
        soccer = MEP_DEFINITIONS["soccer"]
        assert "far" in soccer
        assert "mid" in soccer
        assert "near" in soccer

    def test_soccer_far_required_fields(self):
        from fetchers.base_fetcher import MEP_DEFINITIONS
        far = MEP_DEFINITIONS["soccer"]["far"]
        assert "team_names" in far
        assert "competition" in far
        assert "standings_position" in far
        assert "recent_form" in far
        assert "h2h_last_5" in far

    def test_soccer_near_adds_injuries(self):
        from fetchers.base_fetcher import MEP_DEFINITIONS
        near = MEP_DEFINITIONS["soccer"]["near"]
        assert "injuries_list" in near
        assert "predicted_lineups" in near

    def test_mep_covers_all_sports(self):
        from fetchers.base_fetcher import MEP_DEFINITIONS
        for sport in ("soccer", "rugby", "cricket", "mma"):
            assert sport in MEP_DEFINITIONS, f"MEP missing for {sport}"


# ── Horizon Bucket ───────────────────────────────────────────────────────────

class TestHorizonBucket:
    def test_far(self):
        from fetchers.base_fetcher import horizon_bucket
        assert horizon_bucket(200) == "far"

    def test_mid(self):
        from fetchers.base_fetcher import horizon_bucket
        assert horizon_bucket(72) == "mid"

    def test_near(self):
        from fetchers.base_fetcher import horizon_bucket
        assert horizon_bucket(12) == "near"

    def test_boundary_48h(self):
        from fetchers.base_fetcher import horizon_bucket
        assert horizon_bucket(48) == "near"


# ── FetchResult Shape ────────────────────────────────────────────────────────

class TestFetchResult:
    def test_default_fields(self):
        from fetchers.base_fetcher import FetchResult
        result = FetchResult(
            context={"data_available": True, "home_team": {"name": "Test"}},
        )
        assert result.context["data_available"] is True
        assert isinstance(result.confidence, dict)
        assert isinstance(result.sources, dict)
        assert result.mep_met is False
        assert result.mep_missing == []
        assert result.fetched_at  # auto-populated

    def test_espn_compatible_shape(self):
        """Context dict must have the shape consumed by build_narrative_spec."""
        from fetchers.base_fetcher import FetchResult
        ctx = {
            "data_available": True,
            "data_freshness": "2026-03-26T10:00:00+00:00",
            "home_team": {
                "name": "Sundowns",
                "position": 1,
                "points": 55,
                "form": "WWDWL",
                "coach": "Mokwena",
            },
            "away_team": {
                "name": "Chiefs",
                "position": 5,
                "points": 30,
                "form": "LDWWL",
            },
            "h2h": [{"home": "Sundowns", "away": "Chiefs", "home_goals": 2, "away_goals": 0}],
            "competition": "South African PSL",
            "season": "2025/2026",
        }
        result = FetchResult(context=ctx)
        # These are the fields build_narrative_spec reads
        assert result.context["home_team"]["position"] == 1
        assert result.context["home_team"]["form"] == "WWDWL"
        assert result.context["away_team"]["name"] == "Chiefs"
        assert len(result.context["h2h"]) == 1


# ── SQLite Schema ────────────────────────────────────────────────────────────

class TestSchema:
    def test_ensure_schema_creates_tables(self):
        from fetchers.base_fetcher import ensure_schema
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            ensure_schema(db_path)
            from db_connection import get_connection
            conn = get_connection(db_path, readonly=True)
            tables = [
                r["name"] for r in
                conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            ]
            conn.close()
            assert "context_cache" in tables
            assert "match_context" in tables
        finally:
            os.unlink(db_path)

    def test_context_cache_columns(self):
        from fetchers.base_fetcher import ensure_schema
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            ensure_schema(db_path)
            from db_connection import get_connection
            conn = get_connection(db_path)
            info = conn.execute("PRAGMA table_info(context_cache)").fetchall()
            cols = {r["name"] for r in info}
            conn.close()
            assert "cache_key" in cols
            assert "sport" in cols
            assert "league" in cols
            assert "endpoint" in cols
            assert "data" in cols
            assert "fetched_at" in cols
            assert "expires_at" in cols
        finally:
            os.unlink(db_path)

    def test_match_context_columns(self):
        from fetchers.base_fetcher import ensure_schema
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            ensure_schema(db_path)
            from db_connection import get_connection
            conn = get_connection(db_path)
            info = conn.execute("PRAGMA table_info(match_context)").fetchall()
            cols = {r["name"] for r in info}
            conn.close()
            assert "match_key" in cols
            assert "context_json" in cols
            assert "confidence_json" in cols
            assert "mep_met" in cols
            assert "mep_missing" in cols
            assert "horizon_bucket" in cols
        finally:
            os.unlink(db_path)


# ── Cache Round-Trip ─────────────────────────────────────────────────────────

class TestCacheRoundTrip:
    def test_store_and_retrieve_match_context(self):
        from fetchers.base_fetcher import (
            ensure_schema, FetchResult,
            store_match_context, get_cached_context,
        )
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            ensure_schema(db_path)
            ctx = {"data_available": True, "home_team": {"name": "Test"}}
            result = FetchResult(context=ctx, confidence={"home": 1.0})
            store_match_context(
                "test_vs_other", result, "soccer", "psl", "far",
                ttl_hours=1.0, db_path=db_path,
            )
            cached = get_cached_context("test_vs_other", db_path=db_path)
            assert cached is not None
            assert cached["data_available"] is True
            assert cached["home_team"]["name"] == "Test"
        finally:
            os.unlink(db_path)

    def test_store_and_retrieve_api_response(self):
        from fetchers.base_fetcher import (
            ensure_schema,
            store_api_response, get_cached_api_response,
        )
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            ensure_schema(db_path)
            data = {"response": [{"team": "test"}]}
            store_api_response(
                "test:key", data, "soccer", "psl", "standings",
                ttl_hours=1.0, db_path=db_path,
            )
            cached = get_cached_api_response("test:key", db_path=db_path)
            assert cached is not None
            assert cached["response"][0]["team"] == "test"
        finally:
            os.unlink(db_path)


# ── MEP Check Logic ──────────────────────────────────────────────────────────

class TestMEPCheck:
    def test_full_soccer_far_passes(self):
        from fetchers.football_fetcher import FootballFetcher
        from fetchers.base_fetcher import FetchResult
        fetcher = FootballFetcher()
        ctx = {
            "data_available": True,
            "home_team": {"name": "Sundowns", "position": 1, "form": "WWWWW"},
            "away_team": {"name": "Chiefs", "position": 5, "form": "LDWWL"},
            "h2h": [{"home": "a", "away": "b"}],
            "competition": "PSL",
            "venue": "Loftus Versfeld",
            "elo_home": 1800.0,
            "elo_away": 1600.0,
        }
        result = FetchResult(context=ctx)
        met, missing = fetcher.check_mep(result, 200)
        assert met is True, f"MEP not met, missing: {missing}"

    def test_partial_soccer_far_fails(self):
        from fetchers.football_fetcher import FootballFetcher
        from fetchers.base_fetcher import FetchResult
        fetcher = FootballFetcher()
        ctx = {
            "data_available": True,
            "home_team": {"name": "Sundowns"},
            "away_team": {"name": "Chiefs"},
            "h2h": [],
            "competition": "PSL",
        }
        result = FetchResult(context=ctx)
        met, missing = fetcher.check_mep(result, 200)
        assert met is False
        assert len(missing) > 0


# ── FootballFetcher League Config ────────────────────────────────────────────

class TestFootballFetcherConfig:
    def test_psl_configured(self):
        from fetchers.football_fetcher import LEAGUE_CONFIG
        assert "psl" in LEAGUE_CONFIG
        assert LEAGUE_CONFIG["psl"]["api_id"] == 288

    def test_epl_configured(self):
        from fetchers.football_fetcher import LEAGUE_CONFIG
        assert "epl" in LEAGUE_CONFIG
        assert LEAGUE_CONFIG["epl"]["api_id"] == 39

    def test_champions_league_configured(self):
        from fetchers.football_fetcher import LEAGUE_CONFIG
        assert "champions_league" in LEAGUE_CONFIG
        assert LEAGUE_CONFIG["champions_league"]["api_id"] == 2


# ── Extraction Functions ─────────────────────────────────────────────────────

class TestExtraction:
    def test_extract_standings(self):
        from fetchers.football_fetcher import _extract_standings
        raw = {
            "response": [{
                "league": {
                    "standings": [[
                        {
                            "rank": 1,
                            "team": {"id": 2699, "name": "Mamelodi Sundowns"},
                            "points": 55,
                            "goalsDiff": 30,
                            "form": "WWDWL",
                            "all": {"played": 25, "win": 17, "draw": 5, "lose": 3,
                                    "goals": {"for": 40, "against": 10}},
                            "home": {"played": 12, "win": 10, "draw": 2, "lose": 0,
                                     "goals": {"for": 22, "against": 4}},
                            "away": {"played": 13, "win": 7, "draw": 3, "lose": 3,
                                     "goals": {"for": 18, "against": 6}},
                        },
                    ]],
                },
            }],
        }
        standings = _extract_standings(raw, 288)
        assert "mamelodi sundowns" in standings
        team = standings["mamelodi sundowns"]
        assert team["position"] == 1
        assert team["points"] == 55
        assert team["form"] == "WWDWL"
        assert team["goals_for"] == 40

    def test_extract_h2h(self):
        from fetchers.football_fetcher import _extract_h2h
        raw = {
            "response": [
                {
                    "fixture": {"date": "2026-01-15T15:00:00+00:00", "venue": {"name": "Loftus"}},
                    "teams": {"home": {"name": "Sundowns"}, "away": {"name": "Chiefs"}},
                    "goals": {"home": 2, "away": 0},
                },
                {
                    "fixture": {"date": "2025-09-20T15:00:00+00:00", "venue": {"name": "FNB"}},
                    "teams": {"home": {"name": "Chiefs"}, "away": {"name": "Sundowns"}},
                    "goals": {"home": 1, "away": 1},
                },
            ],
        }
        h2h = _extract_h2h(raw)
        assert len(h2h) == 2
        assert h2h[0]["home"] == "Sundowns"
        assert h2h[0]["home_goals"] == 2
        assert h2h[1]["away_goals"] == 1

    def test_extract_injuries(self):
        from fetchers.football_fetcher import _extract_injuries
        raw = {
            "response": [
                {
                    "team": {"name": "Sundowns"},
                    "player": {"name": "Themba Zwane", "type": "Missing Fixture", "reason": "Knee"},
                },
                {
                    "team": {"name": "Chiefs"},
                    "player": {"name": "Itumeleng Khune", "type": "Doubtful", "reason": "Back"},
                },
            ],
        }
        injuries = _extract_injuries(raw)
        assert "sundowns" in injuries
        assert len(injuries["sundowns"]) == 1
        assert injuries["sundowns"][0]["player"] == "Themba Zwane"
        assert "chiefs" in injuries
