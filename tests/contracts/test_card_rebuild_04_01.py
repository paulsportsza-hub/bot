"""CARD-REBUILD-04-01 — _resolve_tier edge_tier + field normalisation.

Covers:
  - _resolve_tier() with all 5 input shapes
  - build_my_matches_data() no longer defaults missing edge_tier to gold
  - build_edge_detail_data() gates on edge_tier so a tip with ONLY edge_tier resolves
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── _resolve_tier: 5 input shapes ─────────────────────────────────────────────

from card_data import _resolve_tier


def test_resolve_tier_display_tier_wins():
    """display_tier is the first field checked — must be returned as-is."""
    assert _resolve_tier({"display_tier": "Silver", "edge_tier": "gold"}) == "silver"


def test_resolve_tier_edge_rating_fallback():
    """edge_rating used when display_tier absent."""
    assert _resolve_tier({"edge_rating": "GOLD"}) == "gold"


def test_resolve_tier_tier_fallback():
    """tier used when display_tier and edge_rating absent."""
    assert _resolve_tier({"tier": "Bronze"}) == "bronze"


def test_resolve_tier_edge_tier_fallback():
    """edge_tier (canonical DB column) used when earlier fields absent."""
    tip = {"edge_tier": "silver"}
    result = _resolve_tier(tip)
    assert result == "silver", f"Expected 'silver', got {result!r}"


def test_resolve_tier_returns_none_when_no_field():
    """No tier field at all → None (never defaults to gold/bronze)."""
    result = _resolve_tier({"ev": 5.0, "home": "Hurricanes", "away": "Blues"})
    assert result is None, f"Expected None, got {result!r}"


# ── build_my_matches_data: no gold default ─────────────────────────────────────

def test_build_my_matches_data_no_gold_default():
    """Missing edge_tier must produce tier_key=None — not 'gold'."""
    from card_data import build_my_matches_data

    matches = [
        {
            "home": "Hurricanes",
            "away": "Blues",
            "league": "Super Rugby Pacific",
            "has_edge": True,
            # edge_tier intentionally absent — simulates cache miss
        }
    ]
    result = build_my_matches_data(matches)
    edge_cards = result.get("edge_matches", [])
    assert len(edge_cards) == 1
    card = edge_cards[0]
    assert card["edge_tier"] is None, (
        f"edge_tier should be None when missing from source dict, got {card['edge_tier']!r}"
    )
    assert card["tier_emoji"] == "", (
        f"tier_emoji should be empty string for None tier, got {card['tier_emoji']!r}"
    )


# ── build_edge_detail_data: edge_tier-only tip resolves correctly ──────────────

def test_build_edge_detail_data_edge_tier_only():
    """A tip with ONLY edge_tier (no display_tier/edge_rating/tier) must resolve."""
    from card_data import build_edge_detail_data

    tip = {
        "edge_tier": "silver",
        "home": "Liverpool",
        "away": "Fulham",
        "league": "EPL",
        "ev": 3.5,
        "pick": "Liverpool",
        "pick_odds": 1.85,
        "bookmaker": "Betway",
    }
    data = build_edge_detail_data(tip)
    assert data["tier"] == "silver", f"Expected 'silver', got {data['tier']!r}"
    assert data["tier_name"] == "SILVER"
    assert data["tier_emoji"] == "🥈"
