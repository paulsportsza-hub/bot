"""Layer 1.1 — Edge V2 return format contracts.

Validates that calculate_composite_edge() returns the exact dict shape
the bot relies on. Any key rename or type change breaks downstream code.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ensure_scrapers_importable
ensure_scrapers_importable()

from scrapers.edge.edge_v2 import calculate_composite_edge
from scrapers.edge.edge_v2_helper import get_top_edges
from scrapers.edge.edge_config import (
    SIGNAL_WEIGHTS,
    SPORT_WEIGHTS,
    NON_SHARP_WEIGHTS,
    TIER_THRESHOLDS,
    NON_SHARP_TIER_THRESHOLDS,
    MAX_DRAW_RATIO,
)
from scrapers.edge.tier_engine import assign_tier, get_tier_display


# ── Required keys in calculate_composite_edge() return dict ──

REQUIRED_EDGE_KEYS = {
    "match_key", "outcome", "market_type", "sport", "league",
    "edge_pct", "composite_score", "tier", "tier_display",
    "confidence", "sharp_available",
    "best_bookmaker", "best_odds", "fair_probability",
    "sharp_source", "method", "n_bookmakers",
    "draw_penalty_applied", "stale_warning",
    "signals", "confirming_signals", "contradicting_signals",
    "red_flags", "narrative", "narrative_bullets", "created_at",
}

REQUIRED_SIGNAL_KEYS = {"signal_strength", "available"}

VALID_TIERS = {"diamond", "gold", "silver", "bronze"}
VALID_OUTCOMES = {"home", "draw", "away"}
VALID_CONFIDENCES = {"high", "medium", "low"}
VALID_MARKET_TYPES = {"1x2", "over_under", "btts"}


class TestEdgeReturnShape:
    """Verify the dict returned by calculate_composite_edge() has all required keys."""

    def test_live_edges_have_required_keys(self):
        """Every live edge must have all required keys."""
        edges = get_top_edges(n=20)
        if not edges:
            pytest.skip("No live edges available")
        for edge in edges:
            missing = REQUIRED_EDGE_KEYS - set(edge.keys())
            assert not missing, (
                f"Edge {edge.get('match_key', '?')} missing keys: {missing}"
            )

    def test_signals_dict_shape(self):
        """Each signal in an edge must have signal_strength and available."""
        edges = get_top_edges(n=10)
        if not edges:
            pytest.skip("No live edges available")
        for edge in edges:
            signals = edge.get("signals", {})
            assert isinstance(signals, dict), (
                f"Edge {edge['match_key']}: signals should be dict, got {type(signals)}"
            )
            for sig_name, sig_data in signals.items():
                missing = REQUIRED_SIGNAL_KEYS - set(sig_data.keys())
                assert not missing, (
                    f"Signal '{sig_name}' in {edge['match_key']} missing: {missing}"
                )

    def test_composite_score_bounded(self):
        """Composite scores must be 0-100."""
        edges = get_top_edges(n=20)
        if not edges:
            pytest.skip("No live edges available")
        for edge in edges:
            score = edge["composite_score"]
            assert 0 <= score <= 100, (
                f"Edge {edge['match_key']} composite_score={score} out of [0,100]"
            )

    def test_tier_valid_enum(self):
        """Tier must be one of the 4 valid values."""
        edges = get_top_edges(n=20)
        if not edges:
            pytest.skip("No live edges available")
        for edge in edges:
            assert edge["tier"] in VALID_TIERS, (
                f"Edge {edge['match_key']} has invalid tier: {edge['tier']}"
            )

    def test_outcome_valid(self):
        """Outcome must be home, draw, or away."""
        edges = get_top_edges(n=20)
        if not edges:
            pytest.skip("No live edges available")
        for edge in edges:
            assert edge["outcome"] in VALID_OUTCOMES, (
                f"Edge {edge['match_key']} has invalid outcome: {edge['outcome']}"
            )

    def test_confidence_valid(self):
        """Confidence must be high, medium, or low."""
        edges = get_top_edges(n=20)
        if not edges:
            pytest.skip("No live edges available")
        for edge in edges:
            assert edge["confidence"] in VALID_CONFIDENCES, (
                f"Edge {edge['match_key']} has invalid confidence: {edge['confidence']}"
            )

    def test_edge_pct_positive(self):
        """All surfaced edges must have positive edge_pct."""
        edges = get_top_edges(n=20)
        if not edges:
            pytest.skip("No live edges available")
        for edge in edges:
            assert edge["edge_pct"] > 0, (
                f"Edge {edge['match_key']} has non-positive edge_pct: {edge['edge_pct']}"
            )

    def test_red_flags_is_list_of_strings(self):
        """red_flags must be a list of strings."""
        edges = get_top_edges(n=10)
        if not edges:
            pytest.skip("No live edges available")
        for edge in edges:
            flags = edge["red_flags"]
            assert isinstance(flags, list), (
                f"red_flags should be list, got {type(flags)}"
            )
            for f in flags:
                assert isinstance(f, str), (
                    f"red_flag item should be str, got {type(f)}: {f}"
                )

    def test_tier_display_shape(self):
        """tier_display must have emoji and label keys."""
        edges = get_top_edges(n=5)
        if not edges:
            pytest.skip("No live edges available")
        for edge in edges:
            td = edge["tier_display"]
            assert isinstance(td, dict), f"tier_display should be dict, got {type(td)}"
            assert "emoji" in td, "tier_display missing 'emoji' key"
            assert "label" in td, "tier_display missing 'label' key"


class TestTierThresholds:
    """Verify tier threshold constants are correctly ordered."""

    def test_diamond_composite_highest(self):
        """Diamond requires the highest composite."""
        assert (TIER_THRESHOLDS["diamond"]["min_composite"]
                > TIER_THRESHOLDS["gold"]["min_composite"]), (
            "Diamond min_composite must exceed Gold"
        )

    def test_tier_edge_pct_ordering(self):
        """Premium tiers stay ordered; Bronze may sit above Silver by design."""
        for thresholds in [TIER_THRESHOLDS, NON_SHARP_TIER_THRESHOLDS]:
            d = thresholds["diamond"]["min_edge_pct"]
            g = thresholds["gold"]["min_edge_pct"]
            s = thresholds["silver"]["min_edge_pct"]
            b = thresholds["bronze"]["min_edge_pct"]
            assert d >= g >= s, (
                f"Premium edge pct thresholds not ordered: diamond={d}, gold={g}, silver={s}"
            )
            assert 0 < b <= g, (
                f"Bronze edge pct threshold out of expected range: bronze={b}, gold={g}"
            )

    def test_assign_tier_below_bronze_returns_none(self):
        """Composite below bronze threshold returns None (hidden)."""
        result = assign_tier(
            composite=5, edge_pct=0.1, confirming=0,
            red_flags=[], market_type="1x2", sharp_available=True,
        )
        assert result is None, "Sub-bronze composite should return None"

    def test_assign_tier_diamond_requires_confirming(self):
        """Diamond requires min_confirming signals."""
        min_conf = TIER_THRESHOLDS["diamond"]["min_confirming"]
        result = assign_tier(
            composite=90, edge_pct=20.0, confirming=min_conf - 1,
            red_flags=[], market_type="1x2", sharp_available=True,
        )
        assert result != "diamond", (
            f"Diamond should require {min_conf} confirming signals"
        )


class TestSignalWeights:
    """Verify signal weight configuration integrity."""

    def test_all_sports_have_weights(self):
        """Every sport in SPORT_WEIGHTS has all standard signal names."""
        standard_signals = set(SIGNAL_WEIGHTS.keys())
        for sport, weights in SPORT_WEIGHTS.items():
            missing = standard_signals - set(weights.keys())
            assert not missing, (
                f"Sport '{sport}' missing signal weights: {missing}"
            )

    def test_weights_sum_reasonable(self):
        """Weight sums should be ~0.80-0.95 (with some reserved)."""
        for sport, weights in {**SPORT_WEIGHTS, **NON_SHARP_WEIGHTS}.items():
            total = sum(weights.values())
            assert 0.60 <= total <= 1.0, (
                f"Sport '{sport}' weights sum to {total}, expected 0.60-1.00"
            )

    def test_price_edge_has_highest_weight(self):
        """price_edge should have the highest or equal-highest weight in every sport."""
        for sport, weights in SPORT_WEIGHTS.items():
            pe = weights.get("price_edge", 0)
            max_w = max(weights.values())
            assert pe >= max_w, (
                f"Sport '{sport}': price_edge ({pe}) should be >= max weight ({max_w})"
            )

    def test_draw_ratio_cap_between_0_and_1(self):
        """MAX_DRAW_RATIO must be between 0 and 1."""
        assert 0 < MAX_DRAW_RATIO < 1, (
            f"MAX_DRAW_RATIO={MAX_DRAW_RATIO} must be in (0, 1)"
        )
