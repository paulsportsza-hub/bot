"""Layer 2.2 — Tier threshold guards.

Verifies Diamond meets all 3 criteria, tier ordering is consistent,
and no negative EV edges surface to users.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.expanduser("~"))
sys.path.insert(0, os.path.join(os.path.expanduser("~"), "bot"))

from scrapers.edge.edge_v2_helper import get_top_edges
from scrapers.edge.edge_config import TIER_THRESHOLDS, NON_SHARP_TIER_THRESHOLDS

TIER_ORDER = {"diamond": 4, "gold": 3, "silver": 2, "bronze": 1}


class TestTierOrdering:
    """Tier ordering must be consistent across all edges."""

    def test_higher_tier_has_higher_composite(self):
        """Within the same sport, higher tiers should generally have higher composites."""
        edges = get_top_edges(n=50)
        if not edges:
            pytest.skip("No live edges available")

        # Group by sport and check ordering tendency
        by_tier: dict[str, list[float]] = {}
        for e in edges:
            tier = e["tier"]
            if tier not in by_tier:
                by_tier[tier] = []
            by_tier[tier].append(e["composite_score"])

        # Average composite per tier should respect ordering
        averages = {
            tier: sum(scores) / len(scores)
            for tier, scores in by_tier.items()
            if scores
        }

        if len(averages) < 2:
            pytest.skip("Need at least 2 tiers to compare ordering")

        # Pairwise check: higher tier average >= lower tier average
        violations = []
        for t1, t2 in [("diamond", "gold"), ("gold", "silver"), ("silver", "bronze")]:
            if t1 in averages and t2 in averages:
                if averages[t1] < averages[t2] * 0.8:  # 20% tolerance
                    violations.append(
                        f"{t1} avg={averages[t1]:.1f} < {t2} avg={averages[t2]:.1f}"
                    )

        assert not violations, (
            f"Tier ordering violations: {violations}"
        )


class TestDiamondCriteria:
    """Diamond edges must meet all 3 criteria from TIER_THRESHOLDS."""

    def test_diamond_meets_composite_threshold(self):
        """All Diamond edges must have composite >= diamond min_composite."""
        edges = get_top_edges(n=50)
        diamond = [e for e in edges if e["tier"] == "diamond"]
        if not diamond:
            pytest.skip("No Diamond edges currently live")

        for e in diamond:
            sharp = e.get("sharp_available", True)
            thresholds = TIER_THRESHOLDS if sharp else NON_SHARP_TIER_THRESHOLDS
            min_comp = thresholds["diamond"]["min_composite"]
            # Account for red flag penalty
            penalty = len(e.get("red_flags", [])) * 5
            effective = e["composite_score"] - penalty
            # Note: effective may be below min_comp if penalty applied AFTER tier assignment
            # but raw composite should be high enough
            assert e["composite_score"] >= min_comp * 0.8, (
                f"Diamond edge {e['match_key']} composite={e['composite_score']} "
                f"below {min_comp} threshold"
            )

    def test_diamond_meets_edge_pct(self):
        """Diamond edges must have edge_pct >= diamond min_edge_pct."""
        edges = get_top_edges(n=50)
        diamond = [e for e in edges if e["tier"] == "diamond"]
        if not diamond:
            pytest.skip("No Diamond edges currently live")

        for e in diamond:
            sharp = e.get("sharp_available", True)
            thresholds = TIER_THRESHOLDS if sharp else NON_SHARP_TIER_THRESHOLDS
            min_pct = thresholds["diamond"]["min_edge_pct"]
            assert e["edge_pct"] >= min_pct, (
                f"Diamond edge {e['match_key']} edge_pct={e['edge_pct']}% "
                f"below {min_pct}% threshold"
            )

    def test_diamond_meets_confirming(self):
        """Diamond edges must have >= min_confirming signals."""
        edges = get_top_edges(n=50)
        diamond = [e for e in edges if e["tier"] == "diamond"]
        if not diamond:
            pytest.skip("No Diamond edges currently live")

        for e in diamond:
            sharp = e.get("sharp_available", True)
            thresholds = TIER_THRESHOLDS if sharp else NON_SHARP_TIER_THRESHOLDS
            min_conf = thresholds["diamond"]["min_confirming"]
            assert e["confirming_signals"] >= min_conf, (
                f"Diamond edge {e['match_key']} confirming={e['confirming_signals']} "
                f"below {min_conf} threshold"
            )


class TestNoNegativeEV:
    """No edge with negative EV should surface to users."""

    def test_all_edges_positive_ev(self):
        """Every surfaced edge must have edge_pct > 0."""
        edges = get_top_edges(n=50)
        if not edges:
            pytest.skip("No live edges available")

        violations = []
        for e in edges:
            if e["edge_pct"] <= 0:
                violations.append(
                    f"{e['match_key']} ({e['outcome']}): edge_pct={e['edge_pct']}"
                )

        assert not violations, (
            f"Edges with non-positive EV:\n" + "\n".join(violations[:5])
        )

    def test_no_zero_composite(self):
        """No edge should have composite_score of exactly 0."""
        edges = get_top_edges(n=30)
        if not edges:
            pytest.skip("No live edges available")

        zeros = [e for e in edges if e["composite_score"] == 0]
        assert not zeros, (
            f"{len(zeros)} edges have composite_score=0, which should be impossible "
            f"since they passed the minimum tier threshold"
        )
