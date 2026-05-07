"""FIX-CTA-PIN-TO-VERDICT-BOOKMAKER-01 regression test.

Contract: when _select_best_bookmaker_for_outcome receives a preferred_bookmaker
(the verdict-bound bookmaker), it MUST return that bookmaker if the bookmaker
has any valid price for the outcome — even if another bookmaker has a higher
live price.

Two concrete production failures motivating this contract (7 May 2026):
1. PSG vs Arsenal: verdict = PlayaBets 3.11; CTA was picking SuperSportBet 3.20
2. Marumo Gallants vs Richards Bay: verdict = HWB 2.60; CTA was picking Supabets 2.30

Both cases: max-price across live odds_snapshots != bookmaker the verdict was
written for. The user reading the verdict expects the CTA to take them to that
bookmaker. Live max-price hunting is a separate concern (compare row already
exposes that to shoppers).
"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ensure_scrapers_importable
ensure_scrapers_importable()


def test_preferred_bookmaker_wins_when_outpriced_nested_dict():
    """PSG vs Arsenal scenario: verdict = PlayaBets, but SuperSportBet has higher live price.
    
    CTA must still go to PlayaBets (the verdict bookmaker).
    """
    import bot
    odds_by_bk = {
        "playabets":     {"home": 2.22, "draw": 3.43, "away": 3.14},
        "supersportbet": {"home": 2.23, "draw": 3.45, "away": 3.20},  # higher away
        "sportingbet":   {"home": 2.25, "draw": 3.50, "away": 3.10},
        "betway":        {"home": 2.17, "draw": 3.35, "away": 3.05},
        "gbets":         {"home": 2.27, "draw": 3.34, "away": 3.13},
    }
    bk, price = bot._select_best_bookmaker_for_outcome(
        odds_by_bk, "away", preferred_bookmaker="playabets"
    )
    assert bk == "playabets", f"CTA must pin to verdict bookmaker (playabets), got {bk}"
    assert price == 3.14


def test_preferred_bookmaker_wins_when_outpriced_flat_dict():
    """Same contract for flat outcome-specific maps."""
    import bot
    odds_by_bk = {
        "playabets":     3.14,
        "supersportbet": 3.20,
        "sportingbet":   3.10,
    }
    bk, price = bot._select_best_bookmaker_for_outcome(
        odds_by_bk, "away", preferred_bookmaker="playabets"
    )
    assert bk == "playabets"
    assert price == 3.14


def test_marumo_gallants_hollywoodbets_pinning():
    """Marumo Gallants scenario: verdict = HWB at 2.60, but HWB not even in live odds.
    
    Live snapshots have Supabets/Sportingbet/Betway/etc. for HOME — HWB absent.
    The CTA must still say HWB (the verdict bookmaker) so the URL goes to HWB
    even though we have no fresh price from them.
    """
    import bot
    odds_by_bk = {
        "supabets":      {"home": 2.30, "draw": 2.95, "away": 3.38},
        "betway":        {"home": 2.28, "draw": 3.00, "away": 3.35},
        "sportingbet":   {"home": 2.20, "draw": 2.95, "away": 3.30},
        # hollywoodbets absent from live snapshots
    }
    bk, price = bot._select_best_bookmaker_for_outcome(
        odds_by_bk, "home", preferred_bookmaker="hollywoodbets"
    )
    assert bk == "hollywoodbets", (
        f"CTA must pin to verdict bookmaker (hollywoodbets) even when absent from "
        f"live snapshots, got {bk}"
    )
    assert price is None, "no live price available, must signal None for caller fallback"


def test_no_preferred_falls_back_to_best_price():
    """When no preferred_bookmaker is given, fall back to highest-price selection."""
    import bot
    odds_by_bk = {
        "playabets":     3.14,
        "supersportbet": 3.20,
    }
    bk, price = bot._select_best_bookmaker_for_outcome(
        odds_by_bk, "away", preferred_bookmaker=None
    )
    assert bk == "supersportbet"
    assert price == 3.20


def test_empty_odds_with_preferred_returns_preferred_with_none_price():
    """Empty odds_by_bk + preferred_bookmaker → return preferred so CTA URL still resolves."""
    import bot
    bk, price = bot._select_best_bookmaker_for_outcome(
        {}, "home", preferred_bookmaker="hollywoodbets"
    )
    assert bk == "hollywoodbets"
    assert price is None


def test_empty_odds_no_preferred_returns_none():
    """Empty odds_by_bk + no preferred → both None."""
    import bot
    bk, price = bot._select_best_bookmaker_for_outcome(
        {}, "home", preferred_bookmaker=None
    )
    assert bk is None
    assert price is None
