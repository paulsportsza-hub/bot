"""P0-FIX-02 — Contract: list photo and buttons use the SAME tip list.

Root cause (P0-FIX-02):
    build_edge_picks_data() was receiving raw unfiltered tips while
    _build_hot_tips_page() filtered out ev<=0 / edge_score<40.  Photo and
    buttons diverged at every position.

Contract:
    1. _sort_tips_for_snapshot() must filter out ev<=0 and edge_score<40.
    2. build_edge_picks_data(filtered_tips) produces the same pick count
       and match order as the filtered list.
    3. Regression guard: raw tips with sub-threshold entries produce
       DIFFERENT counts than filtered tips (proves the filter matters).
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from bot import _sort_tips_for_snapshot
from card_data import build_edge_picks_data


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _tip(home: str, away: str, ev: float, edge_score: int, tier: str = "gold") -> dict:
    return {
        "home_team": home,
        "away_team": away,
        "ev": ev,
        "edge_score": edge_score,
        "display_tier": tier,
        "odds": 1.80,
        "outcome": home,
        "bookmaker": "betway",
        "match_id": f"{home.lower().replace(' ', '_')}_vs_{away.lower().replace(' ', '_')}_2026-04-09",
        "league": "PSL",
        "sport_key": "soccer_south_africa_premier_division",
    }


# Mix of valid and sub-threshold tips (the scenario that caused the bug)
MIXED_TIPS = [
    _tip("Kaizer Chiefs", "TS Galaxy", ev=3.5, edge_score=62, tier="silver"),
    _tip("Sundowns", "Pirates", ev=8.2, edge_score=78, tier="gold"),
    _tip("Rajasthan Royals", "RCB", ev=-1.0, edge_score=55, tier="silver"),  # neg EV → filtered
    _tip("Man City", "Arsenal", ev=2.1, edge_score=35, tier="bronze"),       # low score → filtered
    _tip("Liverpool", "Chelsea", ev=5.5, edge_score=70, tier="gold"),
    _tip("Bulls", "Stormers", ev=0.0, edge_score=60, tier="silver"),         # zero EV → filtered
]


class TestPhotoButtonIdentity:
    """Photo and buttons MUST show the same tips in the same order."""

    def test_filter_removes_sub_threshold(self):
        """_sort_tips_for_snapshot filters ev<=0 and edge_score<40."""
        filtered = _sort_tips_for_snapshot(MIXED_TIPS)
        assert len(filtered) == 3  # only 3 of 6 pass both thresholds
        # Verify the filtered-out tips are gone
        filtered_homes = [t["home_team"] for t in filtered]
        assert "Rajasthan Royals" not in filtered_homes  # ev=-1.0
        assert "Man City" not in filtered_homes           # edge_score=35
        assert "Bulls" not in filtered_homes              # ev=0.0

    def test_photo_count_equals_filtered_count(self):
        """build_edge_picks_data(filtered) tip count == len(filtered)."""
        filtered = _sort_tips_for_snapshot(MIXED_TIPS)
        card_data = build_edge_picks_data(filtered, page=1, per_page=10)
        # Count all picks across all groups
        photo_count = sum(len(g["picks"]) for g in card_data["groups"])
        assert photo_count == len(filtered)
        assert card_data["total_edges"] == len(filtered)

    def test_photo_order_matches_button_order(self):
        """Picks in photo appear in same order as filtered snapshot."""
        filtered = _sort_tips_for_snapshot(MIXED_TIPS)
        card_data = build_edge_picks_data(filtered, page=1, per_page=10)
        # Extract match labels from card data in display order
        photo_matches = []
        for group in card_data["groups"]:
            for pick in group["picks"]:
                photo_matches.append((pick["home"], pick["away"]))
        # Extract from filtered list in order
        button_matches = [(t["home_team"], t["away_team"]) for t in filtered]
        assert photo_matches == button_matches

    def test_raw_tips_would_diverge(self):
        """Regression: raw unfiltered tips produce MORE picks than filtered."""
        filtered = _sort_tips_for_snapshot(MIXED_TIPS)
        raw_data = build_edge_picks_data(MIXED_TIPS, page=1, per_page=10)
        raw_count = sum(len(g["picks"]) for g in raw_data["groups"])
        # Raw has more tips than filtered — this is the bug that P0-FIX-02 prevents
        assert raw_count > len(filtered), (
            "If raw count equals filtered count, the test fixture needs "
            "sub-threshold tips to demonstrate the divergence"
        )

    def test_snapshot_function_matches_page_builder(self):
        """_sort_tips_for_snapshot produces identical filtering to _build_hot_tips_page."""
        filtered = _sort_tips_for_snapshot(MIXED_TIPS)
        # Replicate _build_hot_tips_page filtering (line 9969 of bot.py)
        page_filtered = [
            t for t in MIXED_TIPS
            if (t.get("ev") or 0) > 0 and (t.get("edge_score") or 0) >= 40
        ]
        # Same tip homes in same set (order may differ by sort, but set must match)
        assert {t["home_team"] for t in filtered} == {t["home_team"] for t in page_filtered}
        assert len(filtered) == len(page_filtered)
