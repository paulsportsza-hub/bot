"""BUILD-MYMATCHES-DEF678-01 — DEF-7: Kickoff time regression guard.

Asserts that _build_mm_matches_for_card() always populates a non-empty
time field (HH:MM) for events that carry a valid commence_time, regardless
of whether _render_your_games_all() has been called beforehand.

Root cause: the function previously read event["_mm_kickoff"] which is only
set by _render_your_games_all(). On first render the field was absent and
time_str was always empty. Fix: derive time directly from parsed commence_time.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── DEF-7: time is populated from commence_time (not _mm_kickoff) ────────────

def test_kickoff_time_populated_from_commence_time():
    """time field is non-empty when commence_time carries a real kickoff."""
    from bot import _build_mm_matches_for_card

    games = [
        {
            "id": "evt-def7-001",
            "home_team": "Man City",
            "away_team": "Arsenal",
            "league_key": "epl",
            "commence_time": "2026-04-19T15:00:00Z",  # 17:00 SAST
            "sport_emoji": "⚽",
        }
    ]
    result = _build_mm_matches_for_card(games, edge_info={}, odds_map={})
    m = result[0]
    assert m.get("time"), "time must not be empty when commence_time is set"
    # Must match HH:MM pattern
    import re
    assert re.match(r"^\d{2}:\d{2}$", m["time"]), (
        f"time must be HH:MM format, got: {m['time']!r}"
    )


def test_kickoff_time_without_mm_kickoff_preset():
    """time is correct even when _mm_kickoff is absent (fresh event, no prior render)."""
    from bot import _build_mm_matches_for_card

    # Deliberately no _mm_kickoff key — simulates first card render before text render
    games = [
        {
            "id": "evt-def7-002",
            "home_team": "Sundowns",
            "away_team": "Pirates",
            "league_key": "psl",
            "commence_time": "2026-04-19T13:30:00Z",  # 15:30 SAST
            "sport_emoji": "⚽",
        }
    ]
    assert "_mm_kickoff" not in games[0], "Pre-condition: _mm_kickoff must be absent"
    result = _build_mm_matches_for_card(games, edge_info={}, odds_map={})
    m = result[0]
    assert m.get("time"), "time must not be empty for PSL event without _mm_kickoff"


def test_midnight_utc_sentinel_produces_empty_time():
    """02:00 SAST (00:00 UTC placeholder) must produce empty time, not '02:00'."""
    from bot import _build_mm_matches_for_card

    games = [
        {
            "id": "evt-def7-003",
            "home_team": "Chiefs",
            "away_team": "Arrows",
            "league_key": "psl",
            "commence_time": "2026-04-19T00:00:00Z",  # 02:00 SAST — sentinel
            "sport_emoji": "⚽",
        }
    ]
    result = _build_mm_matches_for_card(games, edge_info={}, odds_map={})
    m = result[0]
    assert m.get("time") == "", (
        f"Midnight-UTC sentinel must yield empty time, got: {m.get('time')!r}"
    )


def test_kickoff_time_present_in_date_field():
    """date field is also populated (not empty) when commence_time is set."""
    from bot import _build_mm_matches_for_card

    games = [
        {
            "id": "evt-def7-004",
            "home_team": "Liverpool",
            "away_team": "Chelsea",
            "league_key": "epl",
            "commence_time": "2026-05-01T19:45:00Z",  # future date
            "sport_emoji": "⚽",
        }
    ]
    result = _build_mm_matches_for_card(games, edge_info={}, odds_map={})
    m = result[0]
    assert m.get("date"), "date field must not be empty when commence_time is set"
    assert m.get("time"), "time field must not be empty when commence_time is set"
