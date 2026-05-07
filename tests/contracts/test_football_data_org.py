"""Contract tests for the football-data.org free-tier client.

BUILD-EVIDENCE-ENRICH-FOOTBALL-DATA-ORG-01 — locks the public API surface,
fixture parsing, stage normalisation, soft-fail paths, and cache behaviour.

Live HTTP is mocked — no real API calls.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock, MagicMock

_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
)
sys.path.insert(0, _ROOT)


# Sample real-shape responses from football-data.org /v4/competitions/{code}/matches.
# Trimmed to fields our client cares about plus a couple it ignores.
_BAYERN_PSG_SF = {
    "homeTeam": {"id": 5, "name": "FC Bayern München", "shortName": "Bayern"},
    "awayTeam": {"id": 524, "name": "Paris Saint-Germain FC", "shortName": "Paris"},
    "stage": "SEMI_FINALS",
    "matchday": 2,
    "referees": [
        {"name": "Szymon Marciniak", "type": "REFEREE"},
        {"name": "Tomasz Listkiewicz", "type": "ASSISTANT_REFEREE_N1"},
    ],
    "season": {"startDate": "2025-09-01", "endDate": "2026-05-31"},
    "utcDate": "2026-05-06T19:00:00Z",
}

_LIVERPOOL_ARSENAL_EPL = {
    "homeTeam": {"id": 64, "name": "Liverpool FC", "shortName": "Liverpool"},
    "awayTeam": {"id": 57, "name": "Arsenal FC", "shortName": "Arsenal"},
    "stage": "REGULAR_SEASON",
    "matchday": 35,
    "referees": [
        {"name": "Michael Oliver", "type": "REFEREE"},
        {"name": "Dan Cook", "type": "ASSISTANT_REFEREE_N1"},
    ],
    "season": {"startDate": "2025-08-15", "endDate": "2026-05-25"},
    "utcDate": "2026-05-04T15:30:00Z",
}

_UCL_LEAGUE_PHASE = {
    "homeTeam": {"name": "Real Madrid CF"},
    "awayTeam": {"name": "Manchester City FC"},
    "stage": "LEAGUE_STAGE",
    "matchday": 8,
    "referees": [{"name": "Felix Zwayer", "type": "REFEREE"}],
    "season": {"startDate": "2025-09-01", "endDate": "2026-05-31"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _aiocall(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _temp_odds_db() -> str:
    """Create a temp odds.db with just the api_cache table."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="fdorg_test_")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE api_cache (
            cache_key TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            fetched_at TIMESTAMP NOT NULL,
            expires_at TIMESTAMP NOT NULL
        )
    """)
    conn.commit()
    conn.close()
    return path


# ---------------------------------------------------------------------------
# Tests 1–3: match-key parsing
# ---------------------------------------------------------------------------

def test_parse_simple_match_key():
    from scrapers.football_data_org import _parse_match_key
    assert _parse_match_key("arsenal_vs_chelsea_2026-05-06") == (
        "arsenal", "chelsea", "2026-05-06",
    )


def test_parse_multiword_match_key():
    """Multi-token team names round-trip cleanly."""
    from scrapers.football_data_org import _parse_match_key
    assert _parse_match_key("paris_saint_germain_vs_bayern_munich_2026-05-06") == (
        "paris_saint_germain", "bayern_munich", "2026-05-06",
    )


def test_parse_returns_none_for_garbage():
    from scrapers.football_data_org import _parse_match_key
    assert _parse_match_key("") is None
    assert _parse_match_key("home_chelsea_arsenal") is None
    assert _parse_match_key("arsenal_vs_chelsea_2026") is None  # date truncated


# ---------------------------------------------------------------------------
# Tests 4–6: competition code mapping
# ---------------------------------------------------------------------------

def test_competition_code_epl():
    from scrapers.football_data_org import _competition_code
    assert _competition_code("epl") == "PL"


def test_competition_code_ucl():
    from scrapers.football_data_org import _competition_code
    assert _competition_code("champions_league") == "CL"


def test_competition_code_unsupported():
    from scrapers.football_data_org import _competition_code
    assert _competition_code("mls") == ""
    assert _competition_code("") == ""
    assert _competition_code("psl") == ""  # No PSL on football-data.org


# ---------------------------------------------------------------------------
# Tests 7–9: team-name fuzzy matching
# ---------------------------------------------------------------------------

def test_team_match_handles_fc_suffix():
    from scrapers.football_data_org import _team_match
    assert _team_match("liverpool", "arsenal", _LIVERPOOL_ARSENAL_EPL) is True


def test_team_match_handles_unicode_and_space():
    from scrapers.football_data_org import _team_match
    assert _team_match("bayern_munich", "paris_saint_germain", _BAYERN_PSG_SF) is True


def test_team_match_rejects_wrong_pair():
    from scrapers.football_data_org import _team_match
    assert _team_match("liverpool", "tottenham", _LIVERPOOL_ARSENAL_EPL) is False


# ---------------------------------------------------------------------------
# Tests 10–13: stage / leg / referee normalisation
# ---------------------------------------------------------------------------

def test_normalise_ucl_semifinal_leg2():
    """AC-6 launch gate: Bayern v PSG SF leg 2 → 'UCL Semi-Final, leg 2'."""
    from scrapers.football_data_org import _normalise_fixture
    result = _normalise_fixture(_BAYERN_PSG_SF, "CL")
    assert result["competition_stage"] == "UCL Semi-Final, leg 2"
    assert result["matchday"] == 2
    assert result["referee"] == "Szymon Marciniak"
    assert result["competition_code"] == "CL"
    assert result["season"] == "2025/26"


def test_normalise_ucl_league_phase():
    from scrapers.football_data_org import _normalise_fixture
    result = _normalise_fixture(_UCL_LEAGUE_PHASE, "CL")
    assert result["competition_stage"] == "UCL League Phase"
    assert result["matchday"] == 8
    assert result["referee"] == "Felix Zwayer"


def test_normalise_epl_regular_season():
    """EPL fixtures get matchday + referee but blank stage."""
    from scrapers.football_data_org import _normalise_fixture
    result = _normalise_fixture(_LIVERPOOL_ARSENAL_EPL, "PL")
    assert result["competition_stage"] == ""  # REGULAR_SEASON → blank
    assert result["matchday"] == 35
    assert result["referee"] == "Michael Oliver"
    assert result["competition_code"] == "PL"


def test_normalise_referee_picks_primary():
    """When multiple referees are listed, MAIN_REFEREE/REFEREE wins over assistants."""
    from scrapers.football_data_org import _normalise_fixture
    fix = {
        "homeTeam": {"name": "X"}, "awayTeam": {"name": "Y"},
        "stage": "REGULAR_SEASON",
        "matchday": 1,
        "referees": [
            {"name": "Cat Sit", "type": "ASSISTANT_REFEREE_N1"},  # assistant first in API
            {"name": "Anthony Taylor", "type": "REFEREE"},
        ],
    }
    assert _normalise_fixture(fix, "PL")["referee"] == "Anthony Taylor"


def test_normalise_handles_legacy_role_field():
    """Forward-compat: if `role` is populated instead of `type`, still extract referee."""
    from scrapers.football_data_org import _normalise_fixture
    fix = {
        "homeTeam": {"name": "X"}, "awayTeam": {"name": "Y"},
        "stage": "REGULAR_SEASON",
        "matchday": 1,
        "referees": [
            {"name": "Anthony Taylor", "role": "REFEREE", "type": None},
        ],
    }
    assert _normalise_fixture(fix, "PL")["referee"] == "Anthony Taylor"


def test_normalise_real_payload_shape_fulham_villa():
    """Real payload shape from live API probe (FUL vs AVL, 2026-04-25, MD 34)."""
    from scrapers.football_data_org import _normalise_fixture
    fix = {
        "homeTeam": {"id": 63, "name": "Fulham FC", "shortName": "Fulham", "tla": "FUL"},
        "awayTeam": {"id": 58, "name": "Aston Villa FC", "shortName": "Aston Villa", "tla": "AVL"},
        "stage": "REGULAR_SEASON",
        "matchday": 34,
        "referees": [
            {"id": 11605, "name": "Michael Oliver", "type": "REFEREE", "role": None},
        ],
        "season": {"startDate": "2025-08-15", "endDate": "2026-05-24"},
    }
    result = _normalise_fixture(fix, "PL")
    assert result["competition_stage"] == ""
    assert result["matchday"] == 34
    assert result["referee"] == "Michael Oliver"
    assert result["competition_code"] == "PL"


# ---------------------------------------------------------------------------
# Tests 14–18: fetch_fixture_meta integration
# ---------------------------------------------------------------------------

def test_fetch_returns_empty_on_missing_key():
    """No FOOTBALL_DATA_ORG_KEY env → soft-fail returns {}."""
    from scrapers import football_data_org as fd
    with patch.dict(os.environ, {"FOOTBALL_DATA_ORG_KEY": ""}, clear=False):
        # Patch connect_odds_db so we don't hit a real DB
        with patch.object(fd, "connect_odds_db", side_effect=sqlite3.OperationalError("no db")):
            result = _aiocall(fd.fetch_fixture_meta(
                "bayern_munich_vs_paris_saint_germain_2026-05-06",
                "champions_league",
            ))
    assert result == {}


def test_fetch_returns_empty_on_unsupported_league():
    """League that's not in _COMPETITION_CODES (e.g. 'psl') → {} without network call."""
    from scrapers import football_data_org as fd
    with patch.dict(os.environ, {"FOOTBALL_DATA_ORG_KEY": "fake"}, clear=False):
        with patch.object(fd, "_fetch_competition_window", new=AsyncMock()) as m:
            result = _aiocall(fd.fetch_fixture_meta(
                "kaizer_chiefs_vs_orlando_pirates_2026-05-06",
                "psl",
            ))
            m.assert_not_awaited()
    assert result == {}


def test_fetch_returns_empty_on_ghost_match_key():
    """Match key that fails regex parse → {} immediately."""
    from scrapers import football_data_org as fd
    with patch.dict(os.environ, {"FOOTBALL_DATA_ORG_KEY": "fake"}, clear=False):
        with patch.object(fd, "_fetch_competition_window", new=AsyncMock()) as m:
            result = _aiocall(fd.fetch_fixture_meta("not_a_match_key", "epl"))
            m.assert_not_awaited()
    assert result == {}


def test_fetch_full_path_with_cache_miss_then_hit():
    """First call: miss → API → cache write. Second call: cache hit, no API."""
    from scrapers import football_data_org as fd
    db_path = _temp_odds_db()
    try:
        api_payload = {"matches": [_BAYERN_PSG_SF]}
        # Patch the live HTTP fetch to return our payload once
        mock_fetch = AsyncMock(return_value=api_payload)
        with patch.dict(os.environ, {"FOOTBALL_DATA_ORG_KEY": "fake"}, clear=False), \
             patch.object(fd, "_fetch_competition_window", mock_fetch), \
             patch.object(fd, "connect_odds_db", lambda: sqlite3.connect(db_path)), \
             patch.object(fd, "connect_odds_db_readonly", lambda: sqlite3.connect(db_path)):
            r1 = _aiocall(fd.fetch_fixture_meta(
                "bayern_munich_vs_paris_saint_germain_2026-05-06",
                "champions_league",
            ))
            r2 = _aiocall(fd.fetch_fixture_meta(
                "bayern_munich_vs_paris_saint_germain_2026-05-06",
                "champions_league",
            ))
        # Both calls return the normalised meta
        assert r1 == r2
        assert r1["competition_stage"] == "UCL Semi-Final, leg 2"
        assert r1["matchday"] == 2
        assert r1["referee"] == "Szymon Marciniak"
        # API was called exactly ONCE (second call hit the cache)
        assert mock_fetch.call_count == 1
    finally:
        os.unlink(db_path)


def test_fetch_returns_empty_when_no_fixture_match():
    """Window returns matches but none for our home/away pair → {}."""
    from scrapers import football_data_org as fd
    db_path = _temp_odds_db()
    try:
        # Window has Liverpool-Arsenal, but we look up Chelsea-Tottenham
        api_payload = {"matches": [_LIVERPOOL_ARSENAL_EPL]}
        mock_fetch = AsyncMock(return_value=api_payload)
        with patch.dict(os.environ, {"FOOTBALL_DATA_ORG_KEY": "fake"}, clear=False), \
             patch.object(fd, "_fetch_competition_window", mock_fetch), \
             patch.object(fd, "connect_odds_db", lambda: sqlite3.connect(db_path)):
            result = _aiocall(fd.fetch_fixture_meta(
                "chelsea_vs_tottenham_2026-05-04",
                "epl",
            ))
        assert result == {}
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Test 19: EvidencePack dataclass extension is backward-compatible
# ---------------------------------------------------------------------------

def test_fetch_fixture_meta_is_async_coroutine():
    """Regression guard: fetch_fixture_meta MUST be async — pipeline awaits it
    directly via asyncio.wait_for, not via _run_with_timeout (which would wrap
    a sync func in to_thread and silently return an unawaited coroutine).
    """
    import inspect
    from scrapers.football_data_org import fetch_fixture_meta
    assert inspect.iscoroutinefunction(fetch_fixture_meta), (
        "fetch_fixture_meta must remain async; build_evidence_pack relies on "
        "asyncio.wait_for to drive it. Wrapping it via to_thread silently "
        "returns the coroutine object."
    )


def test_evidence_pack_new_fields_default_empty():
    """Pre-fix narrative_cache rows must deserialise unchanged.

    AC-3: backward-compat — EvidencePack created without the new fields
    must default to ('', None, '') so cache rows from before this fix
    render normally.
    """
    from evidence_pack import EvidencePack
    pack = EvidencePack(
        match_key="x_vs_y_2026-05-06",
        sport="soccer",
        league="epl",
        built_at="2026-05-06T00:00:00+00:00",
    )
    assert pack.competition_stage == ""
    assert pack.matchday is None
    assert pack.referee == ""


if __name__ == "__main__":
    unittest.main()
