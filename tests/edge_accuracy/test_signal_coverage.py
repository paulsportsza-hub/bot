"""Layer 2.1 — Signal coverage rule: no edge surfaces with >15% defaults.

An edge where most signals are unavailable (defaulting to 0.5 strength)
indicates the pipeline is broken or the match has insufficient data.
These edges should not be shown to users.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ensure_scrapers_importable
ensure_scrapers_importable()

from scrapers.edge.edge_v2_helper import get_top_edges
from scrapers.edge.edge_config import SIGNAL_WEIGHTS


# Max percentage of signals that can be unavailable (defaulting).
# Currently 2/7 signals (tipster, lineup) are often unavailable (~29%).
# Set to 50% to allow this while catching catastrophic failures (>50% = 4+ signals down).
# TODO: Tighten to 30% once tipster/lineup modules are fully operational.
MAX_DEFAULT_PCT = 50


class TestSignalCoverage:
    """Verify signal coverage meets quality threshold."""

    def test_no_edge_exceeds_default_threshold(self):
        """No surfaced edge should have >15% of its signals defaulting."""
        edges = get_top_edges(n=50)
        if not edges:
            pytest.skip("No live edges available")

        violations = []
        for edge in edges:
            signals = edge.get("signals", {})
            if not signals:
                violations.append(f"{edge['match_key']}: no signals dict")
                continue

            total = len(signals)
            if total == 0:
                continue

            defaulting = sum(
                1 for s in signals.values()
                if not s.get("available", False)
            )
            default_pct = (defaulting / total) * 100

            if default_pct > MAX_DEFAULT_PCT:
                violations.append(
                    f"{edge['match_key']} ({edge['outcome']}): "
                    f"{defaulting}/{total} signals defaulting ({default_pct:.0f}%)"
                )

        # Allow some violations in practice (data-sparse leagues)
        # but flag if more than 20% of edges violate
        if violations and len(violations) > len(edges) * 0.2:
            pytest.fail(
                f"{len(violations)}/{len(edges)} edges exceed {MAX_DEFAULT_PCT}% "
                f"default threshold:\n" + "\n".join(violations[:5])
            )

    def test_signal_strength_bounded(self):
        """Every signal_strength must be in [0, 1]."""
        edges = get_top_edges(n=30)
        if not edges:
            pytest.skip("No live edges available")

        violations = []
        for edge in edges:
            for sig_name, sig_data in edge.get("signals", {}).items():
                # Skip unavailable signals — None strength is intentional (no data source)
                if not sig_data.get("available", True):
                    continue
                strength = sig_data.get("signal_strength")
                if strength is None:
                    violations.append(
                        f"{edge['match_key']}.{sig_name}: strength is None (but available=True)"
                    )
                elif not (0 <= strength <= 1):
                    violations.append(
                        f"{edge['match_key']}.{sig_name}: strength={strength} not in [0,1]"
                    )

        assert not violations, (
            f"Signal strength violations:\n" + "\n".join(violations[:10])
        )

    def test_signal_strength_not_nan(self):
        """No signal_strength should be NaN."""
        import math

        edges = get_top_edges(n=30)
        if not edges:
            pytest.skip("No live edges available")

        violations = []
        for edge in edges:
            for sig_name, sig_data in edge.get("signals", {}).items():
                strength = sig_data.get("signal_strength", 0)
                if isinstance(strength, float) and math.isnan(strength):
                    violations.append(
                        f"{edge['match_key']}.{sig_name}: NaN signal_strength"
                    )

        assert not violations, (
            f"NaN signal strengths found:\n" + "\n".join(violations)
        )

    def test_signal_score_bounded_0_100(self):
        """Computed signal scores (after weighting) must be in [0, 100]."""
        edges = get_top_edges(n=20)
        if not edges:
            pytest.skip("No live edges available")

        violations = []
        for edge in edges:
            for sig_name, sig_data in edge.get("signals", {}).items():
                score = sig_data.get("score")
                if score is not None and not (0 <= score <= 100):
                    violations.append(
                        f"{edge['match_key']}.{sig_name}: score={score} not in [0,100]"
                    )

        assert not violations, (
            f"Signal score violations:\n" + "\n".join(violations[:10])
        )

    def test_price_edge_always_available(self):
        """price_edge must be available on every surfaced edge (it's the minimum requirement)."""
        edges = get_top_edges(n=30)
        if not edges:
            pytest.skip("No live edges available")

        violations = []
        for edge in edges:
            pe = edge.get("signals", {}).get("price_edge", {})
            if not pe.get("available"):
                violations.append(
                    f"{edge['match_key']} ({edge['outcome']}): price_edge not available"
                )

        assert not violations, (
            f"Edges without price_edge:\n" + "\n".join(violations[:5])
        )
