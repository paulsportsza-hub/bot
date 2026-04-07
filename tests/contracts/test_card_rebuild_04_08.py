"""CARD-REBUILD-04-08 — Contract tests for D-11 and D-13.

D-11: Non-edge cards (tier=None) must hide signals section.
      H2H, form, meta bar remain visible when data is present.
D-13: Non-edge cards must carry tier=None so the template renders
      "No Edge Rating" label instead of a tier badge.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── D-13: tier=None for no-edge tip ───────────────────────────────────────────

def test_d13_no_edge_tier_is_none():
    """build_edge_detail_data with display_tier=None returns tier=None."""
    from card_data import build_edge_detail_data

    tip = {
        "display_tier": None,
        "home": "Kaizer Chiefs",
        "away": "Orlando Pirates",
        "league": "PSL",
        "ev": 0,
    }
    data = build_edge_detail_data(tip)
    assert data["tier"] is None, f"Expected tier=None, got {data['tier']}"
    assert data["tier_emoji"] == ""
    assert data["tier_name"] == ""


def test_d13_no_edge_no_tier_fields_set():
    """Tip with no tier fields at all returns tier=None."""
    from card_data import build_edge_detail_data

    tip = {
        "home": "Sundowns",
        "away": "SuperSport",
        "league": "PSL",
    }
    data = build_edge_detail_data(tip)
    assert data["tier"] is None


# ── D-11: signals section data for non-edge tips ──────────────────────────────

def test_d11_signals_populated_for_non_edge():
    """Even without an edge tier, signals data is passed through.
    Template gate ({% if signals and tier %}) hides it — data layer is intact.
    """
    from card_data import build_edge_detail_data

    tip = {
        "display_tier": None,
        "home": "Kaizer Chiefs",
        "away": "Orlando Pirates",
        "league": "PSL",
        "ev": 0,
        "signals": {
            "price_edge": False,
            "form": True,
            "movement": False,
            "market": True,
            "tipster": True,
            "injury": False,
        },
    }
    data = build_edge_detail_data(tip)
    # tier is None — template will hide the signals section via {% if signals and tier %}
    assert data["tier"] is None
    # signals list is non-empty (data layer correct; template gate handles visibility)
    assert isinstance(data["signals"], list)
    assert len(data["signals"]) == 6


def test_d11_fair_value_zero_for_non_edge():
    """Non-edge tip has fair_value=0 and confidence=0 — bars stay hidden."""
    from card_data import build_edge_detail_data

    tip = {
        "display_tier": None,
        "home": "Chiefs",
        "away": "Pirates",
        "league": "PSL",
        "ev": 0,
        "fair_value": 0,
        "confidence": 0,
    }
    data = build_edge_detail_data(tip)
    assert data["fair_value"] == 0
    assert data["confidence"] == 0


# ── D-11: H2H visible regardless of tier ─────────────────────────────────────

def test_d11_h2h_not_gated_by_tier():
    """H2H data passes through when tier=None — template uses {% if h2h_total %}, not tier."""
    from card_data import build_edge_detail_data

    tip = {
        "display_tier": None,
        "home": "Kaizer Chiefs",
        "away": "Orlando Pirates",
        "league": "PSL",
        "ev": 0,
        "h2h": {"n": 8, "hw": 4, "d": 2, "aw": 2},
    }
    data = build_edge_detail_data(tip)
    assert data["tier"] is None
    assert data["h2h_total"] == 8, "H2H must be populated regardless of tier"
    assert data["h2h_home_wins"] == 4
    assert data["h2h_draws"] == 2
    assert data["h2h_away_wins"] == 2


def test_d11_h2h_zero_hides_naturally():
    """When no H2H data exists, h2h_total=0 — template hides section regardless of tier."""
    from card_data import build_edge_detail_data

    tip = {
        "display_tier": None,
        "home": "New Team A",
        "away": "New Team B",
        "league": "PSL",
        "ev": 0,
    }
    data = build_edge_detail_data(tip)
    assert data["h2h_total"] == 0


# ── D-11: form strips independent of tier ────────────────────────────────────

def test_d11_form_passes_through_for_non_edge():
    """Form strips are not gated by tier — they pass through directly."""
    from card_data import build_edge_detail_data

    tip = {
        "display_tier": None,
        "home": "Chiefs",
        "away": "Pirates",
        "league": "PSL",
        "ev": 0,
        "home_form": ["W", "W", "D", "L", "W"],
        "away_form": ["L", "D", "W", "W", "L"],
    }
    data = build_edge_detail_data(tip)
    assert data["tier"] is None
    assert data["home_form"] == ["W", "W", "D", "L", "W"]
    assert data["away_form"] == ["L", "D", "W", "W", "L"]


# ── Edge card signals still visible ──────────────────────────────────────────

def test_edge_card_signals_unaffected():
    """Edge cards still pass signals through — template shows them via {% if signals and tier %}."""
    from card_data import build_edge_detail_data

    tip = {
        "display_tier": "gold",
        "home": "Arsenal",
        "away": "Chelsea",
        "league": "EPL",
        "ev": 8.5,
        "pick": "Arsenal",
        "odds": 2.20,
        "bookmaker": "Betway",
        "signals": {
            "price_edge": True,
            "form": True,
            "movement": False,
            "market": True,
            "tipster": False,
            "injury": False,
        },
    }
    data = build_edge_detail_data(tip)
    assert data["tier"] == "gold"
    assert isinstance(data["signals"], list)
    assert len(data["signals"]) == 6
    active = [s for s in data["signals"] if s["active"]]
    assert len(active) >= 1, "At least one signal should be active for gold edge"
