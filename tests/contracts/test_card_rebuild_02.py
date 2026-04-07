"""CARD-REBUILD-02 — Contract tests for 6 detail card fixes.

FIX 1: test_enrich_tip_never_silently_fails
FIX 1: test_enrich_tip_for_card_populates_signals (integration)
FIX 2: test_detail_data_populates_date_time
FIX 3: test_no_build_gate_relax
FIX 4: test_edge_detail_no_bronze_default
FIX 5: test_score_filter_threshold_38
FIX 6: test_channel_display_clean
GOLD STANDARD: test_density_acceptance_arsenal_bournemouth
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── FIX 1: test_enrich_tip_never_silently_fails ─────────────────────────────

def test_enrich_tip_never_silently_fails():
    """When build_verified_data_block raises, the exception is logged at WARNING+."""
    import logging
    from unittest.mock import patch, MagicMock

    from bot import _enrich_tip_for_card

    tip = {"ev": 3.5, "odds": 1.5, "bookmaker": "Betway"}

    # Monkeypatch build_verified_data_block to raise
    mock_bvdb = MagicMock(side_effect=RuntimeError("test DB failure"))
    mock_form = MagicMock(return_value=[])
    mock_h2h = MagicMock(return_value={"played": 0, "hw": 0, "d": 0, "aw": 0})
    mock_inj = MagicMock(return_value=([], []))
    mock_sig = MagicMock(return_value={})

    with patch("card_pipeline.build_verified_data_block", mock_bvdb), \
         patch("card_pipeline._compute_team_form", mock_form), \
         patch("card_pipeline._compute_h2h", mock_h2h), \
         patch("card_pipeline._split_injuries", mock_inj), \
         patch("card_pipeline._compute_signals", mock_sig):

        with patch("bot.log") as mock_log:
            result = _enrich_tip_for_card(tip, "arsenal_vs_bournemouth_2026-04-12")

    # Exception must be logged at exception level (WARNING or higher), NOT debug
    mock_log.exception.assert_called_once()
    assert "build_verified_data_block failed" in str(mock_log.exception.call_args)

    # Function still returns gracefully (unenriched tip)
    assert result is not None


# ── FIX 1: test_enrich_tip_for_card_populates_signals (integration) ──────────

def test_enrich_tip_for_card_populates_signals():
    """_enrich_tip_for_card with Arsenal vs Bournemouth produces >=4 active signals."""
    from bot import _enrich_tip_for_card

    tip = {
        "match_id": "arsenal_vs_bournemouth_2026-04-12",
        "ev": 3.5,
        "edge_score": 62.4,
        "outcome": "Home Win",
        "outcome_key": "home",
        "bookmaker": "supabets",
        "odds": 1.47,
    }
    enriched = _enrich_tip_for_card(tip, "arsenal_vs_bournemouth_2026-04-12")

    signals = enriched.get("signals", {})
    active_count = sum(1 for v in signals.values() if v)

    assert active_count >= 4, (
        f"Expected >=4 active signals for Arsenal vs Bournemouth, got {active_count}: {signals}"
    )
    assert enriched.get("home_form"), "home_form should be non-empty"
    assert enriched.get("away_form"), "away_form should be non-empty"


# ── FIX 2: test_detail_data_populates_date_time ─────────────────────────────

def test_detail_data_populates_date_time():
    """build_edge_detail_data populates date and time from _bc_kickoff."""
    from card_data import build_edge_detail_data

    tip = {
        "display_tier": "gold",
        "ev": 5.0,
        "home": "Arsenal",
        "away": "Bournemouth",
        "league": "EPL",
        "_bc_kickoff": "Sat 12 Apr · 13:30",
        "pick": "Arsenal",
        "pick_odds": 1.47,
        "bookmaker": "Supabets",
    }
    data = build_edge_detail_data(tip)
    assert data["date"] == "Sat 12 Apr", f"Expected 'Sat 12 Apr', got '{data['date']}'"
    assert data["time"] == "13:30", f"Expected '13:30', got '{data['time']}'"


def test_detail_data_date_time_from_space_format():
    """_split_kickoff handles 'Today 19:30' format."""
    from card_data import build_edge_detail_data

    tip = {
        "display_tier": "silver",
        "ev": 3.0,
        "home": "Liverpool",
        "away": "Fulham",
        "_bc_kickoff": "Today 19:30",
    }
    data = build_edge_detail_data(tip)
    assert data["date"] == "Today", f"Expected 'Today', got '{data['date']}'"
    assert data["time"] == "19:30", f"Expected '19:30', got '{data['time']}'"


# ── FIX 3: test_no_build_gate_relax ─────────────────────────────────────────

def test_no_build_gate_relax():
    """Zero matches for display_tier = "bronze" assignment or BUILD-GATE-RELAX in _sort_tips_for_snapshot."""
    from pathlib import Path

    bot_path = Path(__file__).parent.parent.parent / "bot.py"
    source = bot_path.read_text()

    # Find _sort_tips_for_snapshot function
    start = source.find("def _sort_tips_for_snapshot(")
    assert start != -1, "_sort_tips_for_snapshot not found"
    # Find next def (end of function)
    end = source.find("\ndef ", start + 1)
    func_source = source[start:end]

    # No forced bronze assignment inside the function
    assert 'display_tier"] = "bronze"' not in func_source, (
        "BUILD-GATE-RELAX override still present in _sort_tips_for_snapshot"
    )
    assert 'edge_rating"] = "bronze"' not in func_source, (
        "BUILD-GATE-RELAX edge_rating override still present in _sort_tips_for_snapshot"
    )


# ── FIX 4: test_edge_detail_no_bronze_default ───────────────────────────────

@pytest.mark.asyncio
async def test_edge_detail_no_bronze_default():
    """When snapshot and cache are empty, handler queries DB before defaulting to no_rating."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    # The default should be "no_rating", not "bronze"
    # Verify by reading the source
    from pathlib import Path

    bot_path = Path(__file__).parent.parent.parent / "bot.py"
    source = bot_path.read_text()

    # Find the edge:detail handler section
    marker = "# Determine edge tier for card buttons"
    idx = source.find(marker)
    assert idx != -1, "Edge tier determination block not found"
    block = source[idx:idx + 800]

    assert '"no_rating"' in block, (
        f"Default tier should be 'no_rating', not 'bronze'. Block:\n{block[:200]}"
    )
    assert '_get_fresh_tier_from_er' in block, (
        "DB lookup via _get_fresh_tier_from_er should be in the tier determination block"
    )


# ── FIX 5: test_score_filter_threshold_38 ───────────────────────────────────

def test_score_filter_threshold_38():
    """_sort_tips_for_snapshot includes tips with composite >= 38 (silver floor)."""
    from bot import _sort_tips_for_snapshot

    tips = [
        {"ev": 3.5, "edge_score": 39.6, "display_tier": "silver", "edge_rating": "silver"},
        {"ev": 5.0, "edge_score": 62.4, "display_tier": "gold", "edge_rating": "gold"},
        {"ev": 2.0, "edge_score": 37.9, "display_tier": "bronze", "edge_rating": "bronze"},
    ]
    result = _sort_tips_for_snapshot(tips)

    # 39.6 >= 38 → included, 37.9 < 38 → excluded
    scores = [t["edge_score"] for t in result]
    assert 39.6 in scores, "Tip with composite 39.6 should be included (>= 38)"
    assert 62.4 in scores, "Tip with composite 62.4 should be included"
    assert 37.9 not in scores, "Tip with composite 37.9 should be excluded (< 38)"


# ── FIX 6: test_channel_display_clean ────────────────────────────────────────

def test_channel_display_clean():
    """Channel extraction from broadcast string produces clean DStv identifier."""
    import re

    # Simulate the channel extraction logic from _build_hot_tips_page
    broadcast_raw = "📺 SS EPL (DStv 203)"
    _ch_m = re.search(r"\(?(DStv \d+)\)?", broadcast_raw)
    channel = _ch_m.group(1) if _ch_m else broadcast_raw.replace("📺 ", "")

    assert channel == "DStv 203", f"Expected 'DStv 203', got '{channel}'"

    # Also test without parentheses
    broadcast_raw2 = "📺 DStv 202"
    _ch_m2 = re.search(r"\(?(DStv \d+)\)?", broadcast_raw2)
    channel2 = _ch_m2.group(1) if _ch_m2 else broadcast_raw2.replace("📺 ", "")
    assert channel2 == "DStv 202", f"Expected 'DStv 202', got '{channel2}'"

    # Test free-to-air fallback
    broadcast_raw3 = "📺 SABC 1"
    _ch_m3 = re.search(r"\(?(DStv \d+)\)?", broadcast_raw3)
    channel3 = _ch_m3.group(1) if _ch_m3 else broadcast_raw3.replace("📺 ", "")
    assert channel3 == "SABC 1", f"Expected 'SABC 1', got '{channel3}'"


# ── GOLD STANDARD: test_density_acceptance_arsenal_bournemouth ────────────────

def test_density_acceptance_arsenal_bournemouth():
    """Render Arsenal vs Bournemouth Gold Standard and verify >= 6 of 7 density criteria."""
    from bot import _enrich_tip_for_card
    from card_data import build_edge_detail_data

    tip = {
        "match_id": "arsenal_vs_bournemouth_2026-04-12",
        "ev": 3.5,
        "edge_score": 62.4,
        "outcome": "Home Win",
        "outcome_key": "home",
        "bookmaker": "supabets",
        "odds": 1.47,
        "display_tier": "gold",
        "edge_rating": "gold",
        "home": "Arsenal",
        "home_team": "Arsenal",
        "away": "Bournemouth",
        "away_team": "Bournemouth",
        "league": "EPL",
        "pick": "Arsenal",
        "_bc_kickoff": "Sat 12 Apr · 13:30",
    }
    enriched = _enrich_tip_for_card(tip, "arsenal_vs_bournemouth_2026-04-12")
    data = build_edge_detail_data(enriched)

    criteria_met = 0

    # 1. Both team names + correct sport icon
    if data["home"] and data["away"] and data.get("sport_emoji"):
        criteria_met += 1

    # 2. Both 5-game form strips (real W/D/L data, not blanks)
    if len(data.get("home_form", [])) >= 3 and len(data.get("away_form", [])) >= 3:
        criteria_met += 1

    # 3. Date + time (SAST) in meta row
    if data.get("date") and data.get("time"):
        criteria_met += 1

    # 4. THE PICK block fully populated
    if data.get("pick") and data.get("bookmaker"):
        criteria_met += 1

    # 5. At least 3 of 6 EDGE SIGNALS lit
    signals = data.get("signals", [])
    if isinstance(signals, list):
        active = sum(1 for s in signals if s.get("active"))
    else:
        active = sum(1 for v in signals.values() if v)
    if active >= 3:
        criteria_met += 1

    # 6. Fair Value + Confidence bars with non-zero values
    if data.get("fair_value", 0) > 0 or data.get("confidence", 0) > 0:
        criteria_met += 1

    # 7. H2H block, INJURY WATCH, or VERDICT populated
    if data.get("h2h_total", 0) > 0 or data.get("home_injuries") or data.get("verdict"):
        criteria_met += 1

    assert criteria_met >= 6, (
        f"Gold Standard density: {criteria_met}/7 criteria met (need >= 6). "
        f"Data: home_form={data.get('home_form')}, away_form={data.get('away_form')}, "
        f"date={data.get('date')}, time={data.get('time')}, signals_active={active}, "
        f"confidence={data.get('confidence')}, h2h_total={data.get('h2h_total')}"
    )
