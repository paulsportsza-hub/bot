"""Layer 3 — Sport-specific terminology enforcement contracts.

Validates that:
1. Cricket narratives never contain soccer-specific terminology
2. Rugby narratives use correct sport language
3. Soccer narratives still work correctly
4. SPORT_TERMINOLOGY dict has all required sports
5. check_sport_terminology() catches wrong-sport terms
6. build_verified_narrative() uses sport-appropriate language
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.expanduser("~"), "bot"))
sys.path.insert(0, os.path.expanduser("~"))

from bot import (
    SPORT_TERMINOLOGY,
    _get_sport_term,
    check_sport_terminology,
    build_verified_narrative,
    fact_check_output,
)


# ── SPORT_TERMINOLOGY dict contracts ──


def test_sport_terminology_has_all_sports():
    """All supported sports must have a terminology entry."""
    required = {"soccer", "cricket", "rugby", "mma", "boxing"}
    assert required.issubset(set(SPORT_TERMINOLOGY.keys()))


def test_sport_terminology_required_keys():
    """Each sport must have ranking_metric, score_unit, period, banned_terms."""
    required_keys = {"ranking_metric", "score_unit", "period", "banned_terms"}
    for sport, terms in SPORT_TERMINOLOGY.items():
        missing = required_keys - set(terms.keys())
        assert not missing, f"{sport} missing keys: {missing}"


def test_cricket_ranking_metric_is_nrr():
    """Cricket ranking metric must be NRR, never goal difference."""
    assert "net run rate" in SPORT_TERMINOLOGY["cricket"]["ranking_metric"].lower()


def test_rugby_ranking_metric_is_points_difference():
    """Rugby ranking metric must be points difference."""
    assert "points difference" in SPORT_TERMINOLOGY["rugby"]["ranking_metric"].lower()


def test_soccer_ranking_metric_is_goal_difference():
    """Soccer should use goal difference."""
    assert "goal difference" in SPORT_TERMINOLOGY["soccer"]["ranking_metric"].lower()


# ── check_sport_terminology() contracts ──


def test_no_soccer_terms_in_cricket():
    """Cricket narratives must never contain soccer-specific terminology."""
    text = "India and New Zealand are separated only by goal difference in the standings."
    flags = check_sport_terminology(text, "cricket")
    assert len(flags) > 0
    assert any("goal difference" in f.lower() for f in flags)


def test_no_goals_per_game_in_cricket():
    """Cricket should not mention 'goals per game'."""
    text = "They're averaging 2.1 goals per game this season."
    flags = check_sport_terminology(text, "cricket")
    assert len(flags) > 0


def test_no_clean_sheet_in_cricket():
    """Cricket should not mention 'clean sheet'."""
    text = "The bowlers kept a clean sheet in the last match."
    flags = check_sport_terminology(text, "cricket")
    assert len(flags) > 0


def test_no_goal_difference_in_rugby():
    """Rugby should not mention 'goal difference'."""
    text = "France lead the table by goal difference."
    flags = check_sport_terminology(text, "rugby")
    assert len(flags) > 0


def test_soccer_terms_ok_in_soccer():
    """Soccer narratives should NOT flag soccer terminology."""
    text = "Arsenal lead by goal difference with 2 goals per game average."
    flags = check_sport_terminology(text, "soccer")
    assert len(flags) == 0


def test_no_halftime_in_cricket():
    """Cricket should not mention 'half-time'."""
    text = "At half-time, the momentum shifted."
    flags = check_sport_terminology(text, "cricket")
    assert len(flags) > 0


def test_no_offside_in_cricket():
    """Cricket should not mention 'offside'."""
    text = "The team was caught offside repeatedly."
    flags = check_sport_terminology(text, "cricket")
    assert len(flags) > 0


# ── _get_sport_term() contracts ──


def test_get_sport_term_cricket_period():
    """Cricket period should be 'innings'."""
    assert _get_sport_term("cricket", "period") == "innings"


def test_get_sport_term_rugby_period():
    """Rugby period should be 'half'."""
    assert _get_sport_term("rugby", "period") == "half"


def test_get_sport_term_mma_period():
    """MMA period should be 'round'."""
    assert _get_sport_term("mma", "period") == "round"


def test_get_sport_term_unknown_falls_back_to_soccer():
    """Unknown sport should fall back to soccer defaults."""
    assert _get_sport_term("curling", "period") == "half"  # soccer default
    assert _get_sport_term("curling", "nonexistent_key", "fallback") == "fallback"


# ── build_verified_narrative() sport-appropriate language ──


def test_cricket_narrative_no_goals_per_game():
    """build_verified_narrative for cricket must not say 'goals per game'."""
    ctx = {
        "data_available": True,
        "home_team": {
            "name": "India",
            "league_position": 2,
            "points": 4,
            "goals_per_game": 7.5,
        },
        "away_team": {
            "name": "New Zealand",
            "league_position": 3,
            "points": 4,
        },
    }
    result = build_verified_narrative(ctx, sport="cricket")
    all_text = " ".join(
        s for section in result.values() for s in section
    ).lower()
    assert "goals per game" not in all_text
    assert "runs per innings" in all_text


def test_rugby_narrative_no_goals_per_game():
    """build_verified_narrative for rugby must not say 'goals per game'."""
    ctx = {
        "data_available": True,
        "home_team": {
            "name": "France",
            "league_position": 1,
            "points": 10,
            "goals_per_game": 28.5,
        },
        "away_team": {
            "name": "England",
            "league_position": 2,
            "points": 8,
        },
    }
    result = build_verified_narrative(ctx, sport="rugby")
    all_text = " ".join(
        s for section in result.values() for s in section
    ).lower()
    assert "goals per game" not in all_text
    assert "points per game" in all_text


def test_soccer_narrative_uses_goals_per_game():
    """build_verified_narrative for soccer should use 'goals per game'."""
    ctx = {
        "data_available": True,
        "home_team": {
            "name": "Arsenal",
            "league_position": 1,
            "points": 60,
            "goals_per_game": 2.3,
        },
        "away_team": {
            "name": "Chelsea",
            "league_position": 4,
            "points": 45,
        },
    }
    result = build_verified_narrative(ctx, sport="soccer")
    all_text = " ".join(
        s for section in result.values() for s in section
    ).lower()
    assert "goals per game" in all_text


def test_cricket_risk_no_bad_half():
    """Cricket risk fallback must not say 'one bad half'."""
    ctx = {
        "data_available": True,
        "home_team": {"name": "India", "form": "WW"},
        "away_team": {"name": "NZ", "form": "WW"},
    }
    result = build_verified_narrative(ctx, sport="cricket")
    risk_text = " ".join(result.get("risk", [])).lower()
    assert "one bad half" not in risk_text
    assert "innings" in risk_text


def test_mma_risk_no_bad_half():
    """MMA risk fallback must not say 'one bad half'."""
    ctx = {
        "data_available": True,
        "home_team": {"name": "Fighter A", "form": "WW"},
        "away_team": {"name": "Fighter B", "form": "WW"},
    }
    result = build_verified_narrative(ctx, sport="mma")
    risk_text = " ".join(result.get("risk", [])).lower()
    assert "one bad half" not in risk_text
    assert "round" in risk_text


# ── fact_check_output() sport terminology enforcement ──


def test_fact_checker_strips_goal_difference_in_cricket():
    """fact_check_output must strip lines with 'goal difference' in cricket."""
    narrative = (
        "📋 <b>The Setup</b>\n"
        "India sit 2nd on 4 points.\n"
        "Both teams are separated by goal difference.\n"
        "\n"
        "🎯 <b>The Edge</b>\n"
        "Value on India.\n"
        "\n"
        "⚠️ <b>The Risk</b>\n"
        "Weather could play a role.\n"
        "\n"
        "🏆 <b>Verdict</b>\n"
        "Back India."
    )
    result = fact_check_output(narrative, {}, sport="cricket")
    assert "goal difference" not in result.lower()


def test_fact_checker_keeps_goal_difference_in_soccer():
    """fact_check_output must keep 'goal difference' in soccer narratives."""
    narrative = (
        "📋 <b>The Setup</b>\n"
        "Arsenal lead by goal difference.\n"
        "\n"
        "🎯 <b>The Edge</b>\n"
        "Value on Arsenal.\n"
        "\n"
        "⚠️ <b>The Risk</b>\n"
        "Chelsea are dangerous.\n"
        "\n"
        "🏆 <b>Verdict</b>\n"
        "Back Arsenal."
    )
    result = fact_check_output(narrative, {}, sport="soccer")
    assert "goal difference" in result.lower()
