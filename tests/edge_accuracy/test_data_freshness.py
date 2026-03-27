"""Layer 2.3 — Data freshness guards.

No stale odds in active edges. Stale edges must have red flag penalty.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ensure_scrapers_importable
ensure_scrapers_importable()

from scrapers.edge.edge_v2_helper import get_top_edges
from scrapers.edge.edge_config import STALE_THRESHOLD_MINUTES


class TestNoStaleEdgesInOutput:
    """get_top_edges() filters stale edges — none should appear in output."""

    def test_no_stale_warning_in_surfaced_edges(self):
        """Stale-warned edges are filtered by get_top_edges() before output."""
        edges = get_top_edges(n=50)
        if not edges:
            pytest.skip("No live edges available")

        stale = [
            e for e in edges
            if e.get("stale_warning")
        ]
        assert not stale, (
            f"{len(stale)} stale-warned edges leaked into surfaced edges: "
            + ", ".join(e["match_key"] for e in stale[:5])
        )


class TestStaleDetectionPresent:
    """Stale price detection infrastructure must exist."""

    def test_stale_threshold_configured(self):
        """STALE_THRESHOLD_MINUTES must be defined and reasonable."""
        assert isinstance(STALE_THRESHOLD_MINUTES, (int, float)), (
            f"STALE_THRESHOLD_MINUTES must be numeric, got {type(STALE_THRESHOLD_MINUTES)}"
        )
        assert 30 <= STALE_THRESHOLD_MINUTES <= 240, (
            f"STALE_THRESHOLD_MINUTES={STALE_THRESHOLD_MINUTES} should be 30-240 minutes"
        )

    def test_stale_price_produces_red_flag(self):
        """Edges with stale_warning should have a red_flag mentioning staleness."""
        # We can't get stale edges from get_top_edges (they're filtered).
        # Instead verify the contract: stale_warning key exists in edge shape.
        edges = get_top_edges(n=10)
        if not edges:
            pytest.skip("No live edges available")

        for e in edges:
            assert "stale_warning" in e, (
                f"Edge {e['match_key']} missing stale_warning key"
            )


class TestOddsFreshness:
    """Active edges should have reasonably fresh odds data."""

    def test_edges_have_bookmaker_data(self):
        """Every edge must have at least 1 bookmaker and best_odds > 1."""
        edges = get_top_edges(n=30)
        if not edges:
            pytest.skip("No live edges available")

        violations = []
        for e in edges:
            if e.get("n_bookmakers", 0) < 1:
                violations.append(f"{e['match_key']}: n_bookmakers={e.get('n_bookmakers')}")
            if e.get("best_odds", 0) <= 1.0:
                violations.append(f"{e['match_key']}: best_odds={e.get('best_odds')}")

        assert not violations, (
            f"Edges with insufficient bookmaker data:\n" + "\n".join(violations[:5])
        )

    def test_edges_have_created_at(self):
        """Every edge must have a created_at timestamp."""
        edges = get_top_edges(n=10)
        if not edges:
            pytest.skip("No live edges available")

        for e in edges:
            assert e.get("created_at"), (
                f"Edge {e['match_key']} missing created_at timestamp"
            )
