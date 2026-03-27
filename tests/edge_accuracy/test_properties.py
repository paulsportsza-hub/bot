"""Layer 2.5 — Hypothesis property-based tests.

Runs 1000+ random examples to catch edge cases that manual tests miss.
Properties: tier deterministic, sub-threshold never surfaces, composite bounded,
gate returns valid level, draw cap ratio.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ensure_scrapers_importable
ensure_scrapers_importable()

import pytest

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from scrapers.edge.tier_engine import assign_tier
from scrapers.edge.edge_config import (
    TIER_THRESHOLDS,
    NON_SHARP_TIER_THRESHOLDS,
    MAX_DRAW_RATIO,
)
from tier_gate import get_edge_access_level
from services.edge_rating import EdgeRating, calculate_edge_rating, calculate_edge_score


# ── Strategies ──

composites = st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False)
edge_pcts = st.floats(min_value=0, max_value=50, allow_nan=False, allow_infinity=False)
confirmings = st.integers(min_value=0, max_value=10)
red_flag_lists = st.lists(st.text(min_size=5, max_size=50), min_size=0, max_size=5)
tiers = st.sampled_from(["bronze", "silver", "gold", "diamond"])
market_types = st.sampled_from(["1x2", "over_under", "btts"])
booleans = st.booleans()
odds_values = st.floats(min_value=1.01, max_value=50.0, allow_nan=False, allow_infinity=False)
probabilities = st.floats(min_value=0.01, max_value=0.99, allow_nan=False, allow_infinity=False)


# ── Property 1: Tier assignment is deterministic ──

class TestTierDeterministic:

    @settings(max_examples=1000)
    @given(composite=composites, edge_pct=edge_pcts, confirming=confirmings,
           red_flags=red_flag_lists, market_type=market_types, sharp=booleans)
    def test_same_input_same_output(self, composite, edge_pct, confirming,
                                     red_flags, market_type, sharp):
        """assign_tier must return the same result for identical inputs."""
        r1 = assign_tier(composite, edge_pct, confirming, red_flags, market_type, sharp)
        r2 = assign_tier(composite, edge_pct, confirming, red_flags, market_type, sharp)
        assert r1 == r2, (
            f"Non-deterministic: assign_tier({composite}, {edge_pct}, {confirming}, "
            f"{red_flags}, {market_type}, {sharp}) returned {r1} then {r2}"
        )


# ── Property 2: Sub-threshold never surfaces ──

class TestSubThresholdNeverSurfaces:

    @settings(max_examples=1000)
    @given(composite=st.floats(min_value=0, max_value=14.99,
                                allow_nan=False, allow_infinity=False),
           edge_pct=st.floats(min_value=0, max_value=0.49,
                               allow_nan=False, allow_infinity=False))
    def test_below_bronze_returns_none(self, composite, edge_pct):
        """Inputs below bronze thresholds must return None."""
        result = assign_tier(composite, edge_pct, confirming=0,
                             red_flags=[], market_type="1x2", sharp_available=True)
        assert result is None, (
            f"composite={composite}, edge_pct={edge_pct} should be None, got {result!r}"
        )


# ── Property 3: Composite bounded 0-100 ──

class TestCompositeBounded:

    @settings(max_examples=1000)
    @given(
        odds=st.lists(
            st.fixed_dictionaries({
                "bookmaker": st.text(min_size=2, max_size=10),
                "outcome": st.sampled_from(["home", "away", "draw"]),
                "odds": odds_values,
                "timestamp": st.just("2026-03-06T12:00:00"),
            }),
            min_size=0,
            max_size=5,
        ),
        confidence=probabilities,
        implied_prob=probabilities,
    )
    def test_edge_score_bounded(self, odds, confidence, implied_prob):
        """calculate_edge_score must return a value in [0, 100]."""
        model = {
            "outcome": "home",
            "confidence": confidence,
            "implied_prob": implied_prob,
        }
        score = calculate_edge_score(odds, model)
        assert 0 <= score <= 100, (
            f"Edge score {score} out of [0, 100] bounds"
        )


# ── Property 4: Gate returns valid access level ──

class TestGateReturnsValidLevel:

    VALID_LEVELS = {"full", "partial", "blurred", "locked"}

    @settings(max_examples=1000)
    @given(user_tier=tiers, edge_tier=tiers)
    def test_always_valid_level(self, user_tier, edge_tier):
        """get_edge_access_level must always return a valid level string."""
        result = get_edge_access_level(user_tier, edge_tier)
        assert result in self.VALID_LEVELS, (
            f"get_edge_access_level({user_tier!r}, {edge_tier!r}) "
            f"returned {result!r}, not in {self.VALID_LEVELS}"
        )

    @settings(max_examples=1000)
    @given(user_tier=tiers, edge_tier=tiers)
    def test_diamond_always_full(self, user_tier, edge_tier):
        """Diamond user always gets full access."""
        assume(user_tier == "diamond")
        result = get_edge_access_level(user_tier, edge_tier)
        assert result == "full", (
            f"Diamond user viewing {edge_tier} got {result!r}, expected 'full'"
        )


# ── Property 5: Draw cap ratio ──

@pytest.mark.timeout(120)
class TestDrawCapRatio:

    def test_draw_ratio_capped(self):
        """get_top_edges output must respect MAX_DRAW_RATIO."""
        from scrapers.edge.edge_v2_helper import get_top_edges

        edges = get_top_edges(n=50)
        if not edges or len(edges) < 3:
            return  # Not enough edges to test ratio

        draws = sum(1 for e in edges if e.get("outcome") == "draw")
        total = len(edges)

        # Draw ratio should be <= MAX_DRAW_RATIO (with small tolerance for rounding)
        actual_ratio = draws / total
        assert actual_ratio <= MAX_DRAW_RATIO + 0.05, (
            f"Draw ratio {actual_ratio:.2f} exceeds MAX_DRAW_RATIO {MAX_DRAW_RATIO} "
            f"({draws} draws out of {total} edges)"
        )


# ── Property 6: EdgeRating enum values ──

class TestEdgeRatingEnum:

    @settings(max_examples=1000)
    @given(
        odds=st.lists(
            st.fixed_dictionaries({
                "bookmaker": st.text(min_size=2, max_size=10),
                "outcome": st.just("home"),
                "odds": odds_values,
                "timestamp": st.just("2026-03-06T12:00:00"),
            }),
            min_size=1,
            max_size=5,
        ),
        confidence=probabilities,
        implied_prob=probabilities,
    )
    def test_rating_is_valid_enum(self, odds, confidence, implied_prob):
        """calculate_edge_rating must return a valid EdgeRating value."""
        model = {
            "outcome": "home",
            "confidence": confidence,
            "implied_prob": implied_prob,
        }
        rating = calculate_edge_rating(odds, model)
        valid = {EdgeRating.DIAMOND, EdgeRating.GOLD, EdgeRating.SILVER,
                 EdgeRating.BRONZE, EdgeRating.HIDDEN}
        assert rating in valid, (
            f"calculate_edge_rating returned {rating!r}, not a valid EdgeRating"
        )
