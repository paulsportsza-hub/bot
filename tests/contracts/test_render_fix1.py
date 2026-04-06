"""RENDER-FIX1 contract tests — assign_tier() triple gate replaces R15-BUILD-02.

Tests required by brief:
1. Triple-gate Diamond: composite=55, ev=6%, confirming=2 → display_tier = "diamond"
2. Single-gate Gold: composite=55, ev=3%, confirming=1 → display_tier = "gold" (NOT diamond)
3. Gold lockout regression: get_edge_access_level("gold", "gold") returns "full"
4. Bronze fallback: composite=10, ev=0.2%, confirming=0 → display_tier = "bronze"
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ensure_scrapers_importable
ensure_scrapers_importable()

from scrapers.edge.tier_engine import assign_tier
from tier_gate import get_edge_access_level


class TestRenderFix1TripleGateDiamond:
    """Test 1: All three gates satisfied → diamond."""

    def test_diamond_requires_triple_gate(self):
        """composite=55 ≥ 52, ev=6.0 ≥ 5.0, confirming=2 ≥ 2 → diamond."""
        tier = assign_tier(55, 6.0, 2, red_flags=[]) or "bronze"
        assert tier == "diamond", f"Expected diamond, got {tier}"

    def test_composite_only_not_enough_for_diamond(self):
        """composite=55 but ev=3% < 5.0% → should NOT be diamond (fails ev gate)."""
        tier = assign_tier(55, 3.0, 2, red_flags=[]) or "bronze"
        assert tier != "diamond", f"Expected non-diamond (R15-BUILD-02 bug), got {tier}"

    def test_composite_only_no_confirming_not_diamond(self):
        """composite=55 but confirming=0 < 2 → should NOT be diamond."""
        tier = assign_tier(55, 6.0, 0, red_flags=[]) or "bronze"
        assert tier != "diamond", f"Expected non-diamond (R15-BUILD-02 bug), got {tier}"


class TestRenderFix1GoldNotDiamond:
    """Test 2: High composite but fails diamond ev or confirming gate → gold."""

    def test_high_composite_low_ev_gets_gold_not_diamond(self):
        """composite=55, ev=3%, confirming=1 → gold (not diamond: ev < 5% & confirming < 2)."""
        tier = assign_tier(55, 3.0, 1, red_flags=[]) or "bronze"
        assert tier == "gold", f"Expected gold, got {tier}"

    def test_display_tier_logic_simulated(self):
        """Simulates the RENDER-FIX1 replacement block for a single tip dict."""
        tip = {
            "edge_score": 55,
            "ev": 3.0,
            "edge_v2": {"confirming_signals": 1},
        }
        _cs = tip.get("edge_score", 0) or 0
        _ev = tip.get("ev", 0) or 0
        _conf = (tip.get("edge_v2") or {}).get("confirming_signals", 0) or 0
        _assigned = assign_tier(_cs, _ev, _conf, red_flags=[])
        tip["display_tier"] = _assigned or "bronze"

        assert tip["display_tier"] == "gold"

    def test_r15_build02_bug_reproduced(self):
        """Confirms the old composite-only logic WOULD have returned diamond (the bug)."""
        composite = 55
        # Old R15-BUILD-02 logic:
        old_tier = None
        if composite >= 52:
            old_tier = "diamond"
        elif composite >= 40:
            old_tier = "gold"
        elif composite >= 38:
            old_tier = "silver"
        elif composite >= 15:
            old_tier = "bronze"

        # New RENDER-FIX1 logic (ev=3%, confirming=1):
        new_tier = assign_tier(composite, 3.0, 1, red_flags=[]) or "bronze"

        assert old_tier == "diamond", "Old logic should have produced diamond (the bug)"
        assert new_tier == "gold", "New logic should produce gold (the fix)"
        assert new_tier != old_tier, "Fix must change the result"


class TestRenderFix1GoldLockoutRegression:
    """Test 3: Gold subscriber sees Gold/Silver/Bronze tips as 'full' (not blurred)."""

    def test_gold_user_sees_gold_tip_as_full(self):
        assert get_edge_access_level("gold", "gold") == "full"

    def test_gold_user_sees_silver_tip_as_full(self):
        assert get_edge_access_level("gold", "silver") == "full"

    def test_gold_user_sees_bronze_tip_as_full(self):
        assert get_edge_access_level("gold", "bronze") == "full"

    def test_gold_user_sees_diamond_tip_as_blurred(self):
        """Gold subscribers do NOT see Diamond — it should be blurred."""
        assert get_edge_access_level("gold", "diamond") == "blurred"


class TestRenderFix1BronzeFallback:
    """Test 4: Low composite/ev/confirming → falls back to bronze."""

    def test_below_threshold_gets_bronze_fallback(self):
        """composite=10 < 30 (bronze min_composite) → assign_tier returns None → bronze fallback."""
        tier = assign_tier(10, 0.2, 0, red_flags=[]) or "bronze"
        assert tier == "bronze", f"Expected bronze fallback, got {tier}"

    def test_assign_tier_returns_none_below_thresholds(self):
        """assign_tier() returns None (not 'bronze') when nothing passes — fallback is caller's job."""
        result = assign_tier(10, 0.2, 0, red_flags=[])
        assert result is None, f"assign_tier should return None below all thresholds, got {result}"

    def test_display_tier_bronze_from_none(self):
        """The 'or bronze' fallback in RENDER-FIX1 replacement block works correctly."""
        _assigned = assign_tier(10, 0.2, 0, red_flags=[])
        display = _assigned or "bronze"
        assert display == "bronze"
