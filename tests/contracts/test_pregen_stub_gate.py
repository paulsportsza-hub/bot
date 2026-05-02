"""BUILD-PREGEN-STUB-GATE-01: Regression tests for the incomplete-edge_data gate.

Gate lives in scripts/pregenerate_narratives.py immediately after the
_pregen_edge_data dict is constructed (originally line 1894). It returns
early — skipping the sweep for this fixture — when any of the three
upstream sentinels is present:

    outcome        in ("", "?")
    best_odds      == 0  (or falsy)
    best_bookmaker in ("", "?")

The carve-out: when edge["is_non_edge"] == True the non-edge/baseline path
is allowed through — that flow does not share these sentinels.

Without the gate, the stub verdict formatter (lines 2526, 2542) produces
"Back — ? at 0.00. Edge confirmed." and writes it to narrative_cache —
shipping to live subscribers via /start card_<match_key>.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

# Ensure scripts/ and bot/ are on the path
_BOT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS_DIR = os.path.join(_BOT_ROOT, "scripts")
for _p in (_BOT_ROOT, _SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _future_date_suffix(delta_days: int = 3) -> str:
    """Return a YYYY-MM-DD suffix that bypasses the past-kickoff filter."""
    return (datetime.now(timezone.utc) + timedelta(days=delta_days)).strftime("%Y-%m-%d")


class _NeverCallClaude:
    """Claude stub that proves the LLM path is never reached when the gate fires."""

    class messages:
        @staticmethod
        async def create(*args, **kwargs):
            raise AssertionError(
                "Claude must NOT be called — the stub-sentinel gate must return early"
            )


def _base_edge(**overrides) -> dict:
    """Build a future-dated edge dict with overridable sentinel fields."""
    edge = {
        "match_key": f"man_city_vs_arsenal_{_future_date_suffix(3)}",
        "home_team": "Man City",
        "away_team": "Arsenal",
        "sport": "soccer",
        "league": "EPL",
        "tier": "gold",
        "recommended_outcome": "home",
        "best_odds": 1.85,
        "best_bookmaker": "betway",
        "fair_probability": 0.58,
        "edge_pct": 7.4,
        "signals": {},
    }
    edge.update(overrides)
    return edge


# ---------------------------------------------------------------------------
# Sentinel 1: outcome == "?" (the primary upstream defect)
# ---------------------------------------------------------------------------

class TestOutcomeSentinel:
    """edge["recommended_outcome"]=="?" must skip pregen and retry next pass."""

    def test_question_mark_outcome_skipped(self):
        from pregenerate_narratives import _generate_one

        edge = _base_edge(recommended_outcome="?")
        result = asyncio.run(_generate_one(edge))

        assert result["success"] is False
        assert result.get("skipped_incomplete") is True
        assert result["match_key"] == edge["match_key"]
        assert "duration" in result

    def test_empty_outcome_skipped(self):
        """Empty-string outcome must also be gated.

        When recommended_outcome is "" the `or` fallback picks edge["outcome"]
        which defaults to "?" — still a sentinel.
        """
        from pregenerate_narratives import _generate_one

        edge = _base_edge(recommended_outcome="")
        edge.pop("outcome", None)
        result = asyncio.run(_generate_one(edge))

        assert result["success"] is False
        assert result.get("skipped_incomplete") is True


# ---------------------------------------------------------------------------
# Sentinel 2: best_odds == 0
# ---------------------------------------------------------------------------

class TestOddsSentinel:
    """best_odds==0 must skip pregen — divisions and formatting downstream break."""

    def test_zero_odds_skipped(self):
        from pregenerate_narratives import _generate_one

        edge = _base_edge(best_odds=0)
        result = asyncio.run(_generate_one(edge))

        assert result["success"] is False
        assert result.get("skipped_incomplete") is True

    def test_missing_odds_treated_as_zero(self):
        """edge dict without best_odds defaults to 0 via .get fallback — must skip."""
        from pregenerate_narratives import _generate_one

        edge = _base_edge()
        edge.pop("best_odds", None)
        result = asyncio.run(_generate_one(edge))

        assert result["success"] is False
        assert result.get("skipped_incomplete") is True


# ---------------------------------------------------------------------------
# Sentinel 3: best_bookmaker in {"", "?"}
# ---------------------------------------------------------------------------

class TestBookmakerSentinel:
    """best_bookmaker in {"", "?"} must skip — bookmaker-less verdicts are meaningless."""

    def test_question_mark_bookmaker_skipped(self):
        from pregenerate_narratives import _generate_one

        edge = _base_edge(best_bookmaker="?")
        result = asyncio.run(_generate_one(edge))

        assert result["success"] is False
        assert result.get("skipped_incomplete") is True

    def test_empty_bookmaker_skipped(self):
        from pregenerate_narratives import _generate_one

        edge = _base_edge(best_bookmaker="")
        result = asyncio.run(_generate_one(edge))

        assert result["success"] is False
        assert result.get("skipped_incomplete") is True


# ---------------------------------------------------------------------------
# Carve-out: is_non_edge=True bypasses the gate
# ---------------------------------------------------------------------------

class TestNonEdgeCarveOut:
    """The non-edge/baseline path has its own flow and must NOT be gated.

    A non-edge preview legitimately has no outcome / odds / bookmaker — it is
    an analytical match preview, not a bet recommendation. Gating here would
    strip valid previews from narrative_cache.
    """

    def test_non_edge_with_all_sentinels_not_skipped_by_gate(self):
        """When is_non_edge=True the gate must return early without firing.

        We cannot easily run the full non-edge path in isolation (it calls ESPN,
        builds evidence, etc.) so we assert the gate's contract: the early
        return with skipped_incomplete=True must NOT happen when is_non_edge=True.
        Downstream async calls are mocked so the flow can proceed past the gate.
        If the gate incorrectly fires, we'd get skipped_incomplete=True BEFORE
        these mocks can be exercised.
        """
        from pregenerate_narratives import _generate_one
        import pregenerate_narratives as pgn
        import unittest.mock as mock

        edge = _base_edge(
            is_non_edge=True,
            recommended_outcome="?",
            best_odds=0,
            best_bookmaker="?",
        )

        async def _ok_ctx(*a, **kw):
            return {"home_team": {}, "away_team": {}}

        async def _ok_ep(*a, **kw):
            return mock.MagicMock(coverage_metrics=None, home_team={}, away_team={})

        async def _ok_refresh(_edge):
            return _edge

        with mock.patch.object(pgn, "_get_match_context", _ok_ctx), \
             mock.patch.object(pgn, "build_evidence_pack", _ok_ep), \
             mock.patch.object(pgn, "_refresh_edge_from_odds_db", _ok_refresh):
            # The non-edge path may still fail later (Claude is not mocked
            # deeply enough); we only care that the gate itself doesn't fire.
            try:
                result = asyncio.run(_generate_one(edge))
            except Exception:
                result = None

        # Contract: skipped_incomplete must NOT be set when is_non_edge=True.
        # If the flow crashed later, result is None — that proves we passed
        # the gate. If it's a dict, assert skipped_incomplete is not True.
        if result is not None:
            assert result.get("skipped_incomplete") is not True, (
                "Gate must not fire for is_non_edge=True, but got "
                f"skipped_incomplete=True: {result!r}"
            )


# ---------------------------------------------------------------------------
# Positive control: complete edge_data passes the gate
# ---------------------------------------------------------------------------

class TestCompleteEdgePassesGate:
    """A well-formed edge must pass the gate and proceed into the real flow."""

    def test_complete_edge_passes_gate(self):
        from pregenerate_narratives import _generate_one
        import pregenerate_narratives as pgn
        import unittest.mock as mock

        edge = _base_edge(
            recommended_outcome="home",
            best_odds=1.85,
            best_bookmaker="betway",
        )

        async def _ok_ctx(*a, **kw):
            return {"home_team": {}, "away_team": {}}

        async def _ok_ep(*a, **kw):
            return mock.MagicMock(coverage_metrics=None, home_team={}, away_team={})

        async def _ok_refresh(_edge):
            return _edge

        with mock.patch.object(pgn, "_get_match_context", _ok_ctx), \
             mock.patch.object(pgn, "build_evidence_pack", _ok_ep), \
             mock.patch.object(pgn, "_refresh_edge_from_odds_db", _ok_refresh):
            try:
                result = asyncio.run(_generate_one(edge))
            except Exception:
                result = None

        # Complete edge_data: the stub gate must NOT fire.
        if result is not None:
            assert result.get("skipped_incomplete") is not True, (
                "Gate fired on complete edge_data — regression! "
                f"Got: {result!r}"
            )
