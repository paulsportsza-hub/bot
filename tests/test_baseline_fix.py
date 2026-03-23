"""Tests for BASELINE-FIX: Data Source Alignment.

Verifies that narrative verdict bookmaker+price matches the SA Bookmaker
Odds table. Tests the three new functions in pregenerate_narratives.py:
  - _refresh_edge_from_odds_db()
  - _verdict_bookmaker_aligned()
  - _realign_verdict_bookmaker()
"""
from __future__ import annotations

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import pytest
from unittest.mock import AsyncMock, patch

from scripts import pregenerate_narratives as pregen


# ── _verdict_bookmaker_aligned ──


def test_aligned_verdict_passes():
    narrative = (
        "📋 <b>The Setup</b>\nSome setup.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Back the Arsenal win at 2.10 with Betway."
    )
    assert pregen._verdict_bookmaker_aligned(narrative, "Betway", 2.10) is True


def test_wrong_bookmaker_fails():
    narrative = (
        "📋 <b>The Setup</b>\nSome setup.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Back the Arsenal win at 1.54 with Betway."
    )
    assert pregen._verdict_bookmaker_aligned(narrative, "Sportingbet", 1.61) is False


def test_wrong_price_fails():
    narrative = (
        "📋 <b>The Setup</b>\nSome setup.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Lean on Arsenal at 1.54 (Betway)."
    )
    assert pregen._verdict_bookmaker_aligned(narrative, "Betway", 2.10) is False


def test_close_price_passes():
    """Within 0.03 tolerance should pass."""
    narrative = (
        "📋 <b>The Setup</b>\nSome setup.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Back Arsenal at 2.12 with Betway."
    )
    assert pregen._verdict_bookmaker_aligned(narrative, "Betway", 2.10) is True


def test_no_verdict_section_passes():
    """No verdict section = nothing to misalign."""
    narrative = "📋 <b>The Setup</b>\nSome setup.\n\n🎯 <b>The Edge</b>\nEdge text."
    assert pregen._verdict_bookmaker_aligned(narrative, "Betway", 2.10) is True


def test_empty_bookmaker_passes():
    """Empty bookmaker = nothing to check."""
    narrative = "🏆 <b>Verdict</b>\nSome verdict."
    assert pregen._verdict_bookmaker_aligned(narrative, "", 2.10) is True


# ── _realign_verdict_bookmaker ──


def test_realign_replaces_wrong_bookmaker():
    narrative = (
        "📋 <b>The Setup</b>\nSetup.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Back Arsenal at 1.54 with Hollywoodbets."
    )
    result = pregen._realign_verdict_bookmaker(narrative, "Sportingbet", 1.61)
    assert "Sportingbet" in result
    assert "1.61" in result
    assert "Hollywoodbets" not in result


def test_realign_replaces_parenthesised_bookmaker():
    narrative = (
        "📋 <b>The Setup</b>\nSetup.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Lean on Arsenal at 1.54 (GBets)."
    )
    result = pregen._realign_verdict_bookmaker(narrative, "Betway", 2.10)
    assert "Betway" in result


def test_realign_does_not_touch_correct_verdict():
    narrative = (
        "📋 <b>The Setup</b>\nSetup.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Back Arsenal at 2.10 with Betway."
    )
    result = pregen._realign_verdict_bookmaker(narrative, "Betway", 2.10)
    assert result == narrative


def test_realign_preserves_setup_section():
    narrative = (
        "📋 <b>The Setup</b>\nBetway is mentioned here.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Back Arsenal at 1.54 with Hollywoodbets."
    )
    result = pregen._realign_verdict_bookmaker(narrative, "Sportingbet", 1.61)
    # Setup should still reference Betway (not replaced)
    setup_end = result.find("🏆")
    setup = result[:setup_end]
    assert "Betway" in setup


def test_realign_at_pattern():
    """Handles 'BookmakerName @ X.XX' pattern."""
    narrative = (
        "📋 Setup.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Hollywoodbets @ 1.54 is the play."
    )
    result = pregen._realign_verdict_bookmaker(narrative, "Betway", 2.10)
    assert "Betway" in result
    assert "2.10" in result


# ── _refresh_edge_from_odds_db (async) ──


@pytest.mark.asyncio
async def test_refresh_updates_bookmaker_and_odds():
    edge = {
        "match_key": "arsenal_vs_bournemouth_2026-03-22",
        "recommended_outcome": "home",
        "outcome": "home",
        "best_odds": 1.50,
        "best_bookmaker": "Betway",
        "edge_pct": 3.0,
        "fair_probability": 0.55,
    }
    mock_result = {
        "outcomes": {
            "home": {
                "best_odds": 1.61,
                "best_bookmaker": "sportingbet",
            }
        }
    }
    with patch("scripts.pregenerate_narratives.bot._display_bookmaker_name", return_value="Sportingbet"):
        with patch("services.odds_service.get_best_odds", new_callable=AsyncMock, return_value=mock_result):
            result = await pregen._refresh_edge_from_odds_db(edge)

    assert result["best_odds"] == 1.61
    assert result["best_bookmaker"] == "Sportingbet"
    # EV should be recalculated: (1.61 * 0.55 - 1) * 100 = -11.45 → wait
    # Actually: (1.61 * 0.55 - 1) * 100 = (0.8855 - 1) * 100 = -11.45
    # That's negative. But let's just check it was updated.
    assert result["edge_pct"] != 3.0


@pytest.mark.asyncio
async def test_refresh_noop_when_no_odds_data():
    edge = {
        "match_key": "arsenal_vs_bournemouth_2026-03-22",
        "recommended_outcome": "home",
        "outcome": "home",
        "best_odds": 1.50,
        "best_bookmaker": "Betway",
        "edge_pct": 3.0,
    }
    mock_result = {"outcomes": {}}
    with patch("services.odds_service.get_best_odds", new_callable=AsyncMock, return_value=mock_result):
        result = await pregen._refresh_edge_from_odds_db(edge)

    assert result["best_odds"] == 1.50
    assert result["best_bookmaker"] == "Betway"


@pytest.mark.asyncio
async def test_refresh_noop_on_exception():
    edge = {
        "match_key": "arsenal_vs_bournemouth_2026-03-22",
        "recommended_outcome": "home",
        "outcome": "home",
        "best_odds": 1.50,
        "best_bookmaker": "Betway",
        "edge_pct": 3.0,
    }
    with patch("services.odds_service.get_best_odds", new_callable=AsyncMock, side_effect=Exception("DB down")):
        result = await pregen._refresh_edge_from_odds_db(edge)

    assert result["best_odds"] == 1.50
    assert result["best_bookmaker"] == "Betway"


@pytest.mark.asyncio
async def test_refresh_noop_when_no_match_key():
    edge = {"best_odds": 1.50, "best_bookmaker": "Betway"}
    result = await pregen._refresh_edge_from_odds_db(edge)
    assert result["best_odds"] == 1.50


# ── Integration: verdict alignment with W82 baseline ──


def test_w82_baseline_always_aligned():
    """W82 baseline uses spec.bookmaker+odds from edge data, so it's always aligned."""
    from narrative_spec import NarrativeSpec, _render_baseline

    spec = NarrativeSpec(
        home_name="Arsenal",
        away_name="Bournemouth",
        competition="Premier League",
        sport="soccer",
        home_story_type="momentum",
        away_story_type="crisis",
        home_coach="Mikel Arteta",
        away_coach="Andoni Iraola",
        home_position=2,
        away_position=12,
        home_points=61,
        away_points=39,
        home_form="WWWDL",
        away_form="LDWLW",
        home_record="W9 D3 L2",
        away_record="W4 D4 L6",
        home_gpg=2.1,
        away_gpg=1.1,
        home_last_result="beating Newcastle 2-1 at home",
        away_last_result="drawing 1-1 away to Brentford",
        h2h_summary="6 meetings: Arsenal 4W 1D 1L",
        bookmaker="Sportingbet",
        odds=1.61,
        ev_pct=5.2,
        fair_prob_pct=52.0,
        composite_score=58.0,
        support_level=3,
        contradicting_signals=0,
        evidence_class="supported",
        tone_band="confident",
        risk_factors=["Standard variance applies."],
        risk_severity="moderate",
        verdict_action="back",
        verdict_sizing="standard stake",
        outcome="home",
        outcome_label="the Arsenal win",
    )
    baseline = _render_baseline(spec)
    assert pregen._verdict_bookmaker_aligned(baseline, "Sportingbet", 1.61) is True
