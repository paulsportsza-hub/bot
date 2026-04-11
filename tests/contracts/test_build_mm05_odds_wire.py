"""BUILD-MY-MATCHES-05 — Wire Odds into My Matches List Card (H/A Tiles).

Contract tests guard:
  1. _build_mm_matches_for_card() populates odds_home/draw/away for non-edge matches
     when odds_map is supplied.
  2. _build_mm_matches_for_card() leaves edge matches without odds fields
     (edge tiles use pick/bookmaker, not H/D/A odds).
  3. build_my_matches_data() propagates odds to upcoming_matches card data.
  4. _fetch_mm_odds_map() returns {} gracefully when scrapers DB is absent.
  5. BUILD-MY-MATCHES-01: market_type = '1x2' is enforced in the query string.
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── 1. odds_map wired into non-edge match dict ─────────────────────────────────

def test_build_mm_non_edge_gets_odds_from_map():
    """Non-edge match receives odds_home/draw/away from odds_map."""
    from bot import _build_mm_matches_for_card

    games = [
        {
            "id": "evt-001",
            "home_team": "Kaizer Chiefs",
            "away_team": "Orlando Pirates",
            "league_key": "psl",
            "commence_time": "2026-04-12T15:00:00Z",
            "sport_emoji": "⚽",
        }
    ]
    odds_map = {"evt-001": (2.10, 3.40, 3.20)}
    result = _build_mm_matches_for_card(games, edge_info={}, odds_map=odds_map)

    assert len(result) == 1
    m = result[0]
    assert not m.get("has_edge")
    assert m["odds_home"] == 2.10
    assert m["odds_draw"] == 3.40
    assert m["odds_away"] == 3.20


def test_build_mm_non_edge_no_draw_odds():
    """Non-edge match with draw=None (cricket/combat) keeps draw as None."""
    from bot import _build_mm_matches_for_card

    games = [
        {
            "id": "evt-002",
            "home_team": "SA Proteas",
            "away_team": "India",
            "league_key": "sa20",
            "commence_time": "2026-04-12T10:00:00Z",
            "sport_emoji": "🏏",
        }
    ]
    odds_map = {"evt-002": (1.75, None, 2.10)}
    result = _build_mm_matches_for_card(games, edge_info={}, odds_map=odds_map)

    m = result[0]
    assert m["odds_home"] == 1.75
    assert m["odds_draw"] is None
    assert m["odds_away"] == 2.10


def test_build_mm_non_edge_no_odds_when_map_empty():
    """Non-edge match has no odds fields when odds_map is empty."""
    from bot import _build_mm_matches_for_card

    games = [
        {
            "id": "evt-003",
            "home_team": "Sundowns",
            "away_team": "Cape Town City",
            "league_key": "psl",
            "commence_time": "2026-04-12T17:00:00Z",
        }
    ]
    result = _build_mm_matches_for_card(games, edge_info={}, odds_map={})

    m = result[0]
    assert "odds_home" not in m
    assert "odds_draw" not in m
    assert "odds_away" not in m


# ── 2. Edge matches must NOT receive odds from map ─────────────────────────────

def test_build_mm_edge_match_skips_odds_map():
    """Edge match must not have odds_home/draw/away — it uses pick/bookmaker."""
    from bot import _build_mm_matches_for_card

    games = [
        {
            "id": "evt-010",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "league_key": "epl",
            "commence_time": "2026-04-12T14:00:00Z",
        }
    ]
    edge_info = {
        "evt-010": {
            "display_tier": "gold",
            "edge_tier": "gold",
            "confirming": 2,
            "total_signals": 3,
            "tip": {"outcome": "Arsenal", "bookmaker": "Betway", "edge_rating": "gold"},
        }
    }
    odds_map = {"evt-010": (1.80, 3.50, 4.20)}
    result = _build_mm_matches_for_card(games, edge_info=edge_info, odds_map=odds_map)

    m = result[0]
    assert m.get("has_edge") is True
    assert "odds_home" not in m, "Edge match must not carry H/D/A odds"
    assert "odds_draw" not in m
    assert "odds_away" not in m
    assert m.get("pick") == "Arsenal"


# ── 3. build_my_matches_data propagates odds to template data ──────────────────

def test_build_my_matches_data_propagates_odds():
    """Odds pass through build_my_matches_data into upcoming_matches card slice."""
    from card_data import build_my_matches_data

    matches = [
        {
            "home": "Chiefs",
            "away": "Pirates",
            "league": "PSL",
            "has_edge": False,
            "odds_home": 2.10,
            "odds_draw": 3.40,
            "odds_away": 3.20,
        }
    ]
    result = build_my_matches_data(matches)
    upcoming = result.get("upcoming_matches", [])
    assert len(upcoming) == 1
    card = upcoming[0]
    assert card["odds_home"] == "2.10"
    assert card["odds_draw"] == "3.40"
    assert card["odds_away"] == "3.20"


def test_build_my_matches_data_no_draw_propagates_none():
    """None draw odds produce None in card data (template hides the D box)."""
    from card_data import build_my_matches_data

    matches = [
        {
            "home": "Proteas",
            "away": "India",
            "league": "T20 WC",
            "has_edge": False,
            "odds_home": 1.75,
            "odds_draw": None,
            "odds_away": 2.10,
        }
    ]
    result = build_my_matches_data(matches)
    card = result["upcoming_matches"][0]
    assert card["odds_draw"] is None
    assert card["odds_home"] == "1.75"
    assert card["odds_away"] == "2.10"


# ── 4. _fetch_mm_odds_map graceful degradation ─────────────────────────────────

def test_fetch_mm_odds_map_returns_empty_on_missing_db():
    """Returns {} when scrapers odds DB is absent — never raises."""
    from bot import _fetch_mm_odds_map

    games = [
        {
            "id": "evt-099",
            "home_team": "Sundowns",
            "away_team": "Pirates",
            "commence_time": "2026-04-12T15:00:00Z",
        }
    ]
    # Should not raise even if the DB doesn't exist
    result = _fetch_mm_odds_map(games, edge_event_ids=set())
    assert isinstance(result, dict)


def test_fetch_mm_odds_map_skips_edge_event_ids():
    """Event IDs in edge_event_ids are excluded from the odds lookup."""
    from bot import _fetch_mm_odds_map

    games = [
        {
            "id": "evt-edge",
            "home_team": "Liverpool",
            "away_team": "Man City",
            "commence_time": "2026-04-12T15:00:00Z",
        }
    ]
    # Even if DB existed, edge events should not appear in result
    result = _fetch_mm_odds_map(games, edge_event_ids={"evt-edge"})
    assert "evt-edge" not in result


# ── 5. BUILD-MY-MATCHES-01: query enforces market_type = '1x2' ────────────────

def test_fetch_mm_odds_map_query_enforces_1x2_market():
    """The SQL used in _fetch_mm_odds_map must contain market_type = '1x2'."""
    import bot
    src = inspect.getsource(bot._fetch_mm_odds_map)
    # BUILD-MY-MATCHES-01: market filter is mandatory
    assert "market_type" in src, "market_type filter missing from _fetch_mm_odds_map query"
    assert "1x2" in src, "1x2 market literal missing from _fetch_mm_odds_map query"
