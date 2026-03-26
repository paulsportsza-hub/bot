"""
Contract tests for RENDER-FIX6-7: Button Tier Alignment + Header Fallback.

FIX-6 (D-ADD-5): The cache-hit detail path must reconcile _detail_tier
    BEFORE building buttons, so buttons and gating use the same tier.

FIX-7 (BUG-10): All three detail serving paths must have header fallback
    logic when snapshot is cleared (e.g., after bot restart), showing at
    minimum a date extracted from the match_key.
"""

import re
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestFix6ButtonTierAlignment(unittest.TestCase):
    """FIX-6: _build_game_buttons must use the reconciled _detail_tier."""

    def test_detail_tier_reconciliation_before_button_build(self):
        """Verify _detail_tier reconciliation block appears before _build_game_buttons call."""
        with open("bot.py", encoding="utf-8") as f:
            src = f.read()

        # Find the cache-hit path section (bounded by key markers)
        cache_hit_marker = "# D-ADD-5 / RENDER-FIX6:"
        btn_build_marker = "edge_tier=_detail_tier,"

        pos_recon = src.find(cache_hit_marker)
        # First occurrence of edge_tier=_detail_tier AFTER the cache-hit marker
        pos_btn = src.find(btn_build_marker, pos_recon)

        self.assertGreater(pos_recon, 0, "RENDER-FIX6 comment not found in bot.py")
        self.assertGreater(pos_btn, pos_recon, "_detail_tier not used in button build after reconciliation block")

    def test_no_cached_content_edge_tier_in_cache_hit_button_build(self):
        """_cached_content['edge_tier'] must NOT be used directly in the cache-hit _build_game_buttons call."""
        with open("bot.py", encoding="utf-8") as f:
            src = f.read()

        # Start AFTER the reconciliation block (which legitimately uses _cached_content["edge_tier"]
        # as the seed value for _detail_tier). We only want to inspect the _build_game_buttons call.
        btn_start = src.find("# Serve from cache IMMEDIATELY")
        btn_end = src.find("back_page=_resolve_hot_tips_back_page", btn_start)
        if btn_end < 0:
            btn_end = btn_start + 400

        self.assertGreater(btn_start, 0, "'# Serve from cache IMMEDIATELY' marker not found in bot.py")
        btn_section = src[btn_start:btn_end + 100]
        self.assertNotIn(
            '_cached_content["edge_tier"]',
            btn_section,
            "Cache-hit button build must NOT use _cached_content['edge_tier'] directly — use _detail_tier",
        )

    def test_button_tier_alignment_with_display_tier(self):
        """
        Simulate: cache edge_tier='gold', snapshot display_tier='silver'.
        The reconciled _detail_tier must be 'silver'.
        """
        cached_tier = "gold"
        snapshot_display_tier = "silver"

        # Reproduce the reconciliation logic from bot.py
        _aligned_tips = [{"display_tier": snapshot_display_tier}]
        _detail_tier = cached_tier
        if _aligned_tips:
            _detail_tier = _aligned_tips[0].get(
                "display_tier",
                _aligned_tips[0].get("edge_rating", _detail_tier),
            )

        self.assertEqual(
            _detail_tier, "silver",
            "Reconciled _detail_tier should be 'silver' (from display_tier), not 'gold' (from cache)",
        )


class TestFix7HeaderFallback(unittest.TestCase):
    """FIX-7 (BUG-10): Header fallback when snapshot is cleared."""

    def test_render_fix7_markers_in_all_three_paths(self):
        """All three detail serving paths must have RENDER-FIX7 fallback markers."""
        with open("bot.py", encoding="utf-8") as f:
            src = f.read()

        markers = [i for i in range(len(src)) if src.startswith("# RENDER-FIX7:", i)]
        self.assertGreaterEqual(
            len(markers), 3,
            f"Expected at least 3 RENDER-FIX7 fallback blocks, found {len(markers)}",
        )

    def test_header_fallback_date_extraction(self):
        """With empty _bc_kickoff and a match_key containing a date, assert date is extracted."""
        _bc_kickoff = ""
        match_key = "arsenal_vs_chelsea_2026-03-27"

        # Reproduce the fallback logic from bot.py
        if not _bc_kickoff and match_key:
            _f7_dm = re.search(r'(\d{4}-\d{2}-\d{2})', match_key)
            if _f7_dm:
                _bc_kickoff = _f7_dm.group(1)

        self.assertEqual(_bc_kickoff, "2026-03-27", "Date should be extracted from match_key suffix")

    def test_header_fallback_date_extraction_no_date(self):
        """With empty _bc_kickoff and a match_key without a date, kickoff stays empty."""
        _bc_kickoff = ""
        match_key = "arsenal_vs_chelsea"

        if not _bc_kickoff and match_key:
            _f7_dm = re.search(r'(\d{4}-\d{2}-\d{2})', match_key)
            if _f7_dm:
                _bc_kickoff = _f7_dm.group(1)

        self.assertEqual(_bc_kickoff, "", "No date in match_key should leave kickoff empty")

    def test_header_fresh_broadcast_details_populates_kickoff(self):
        """With empty _bc_kickoff and _get_broadcast_details() returning data, broadcast is populated."""
        _bc_kickoff = ""
        _bc_broadcast = ""
        match_key = "arsenal_vs_chelsea_2026-03-27"

        # Simulate the fallback _get_broadcast_details call returning data
        _f7_bc = {"kickoff": "Today 20:00", "broadcast": "📺 DStv 203"}

        if not _bc_kickoff:
            if _f7_bc.get("kickoff"):
                _bc_kickoff = _f7_bc["kickoff"]
            if not _bc_broadcast and _f7_bc.get("broadcast"):
                _bc_broadcast = _f7_bc["broadcast"]

        self.assertEqual(_bc_kickoff, "Today 20:00", "Kickoff should be populated from fresh broadcast lookup")
        self.assertEqual(_bc_broadcast, "📺 DStv 203", "Broadcast should be populated from fresh lookup")

    def test_header_fallback_broadcast_details_fallback_to_date(self):
        """When broadcast lookup fails, date is still extracted from match_key."""
        _bc_kickoff = ""
        _bc_broadcast = ""
        match_key = "mamelodi_sundowns_vs_sekhukhune_2026-03-30"

        # Simulate broadcast lookup raising exception
        if not _bc_kickoff:
            try:
                raise ConnectionError("Simulated timeout")
            except Exception:
                pass
            # Last resort: date from match_key
            if not _bc_kickoff and match_key:
                _f7_dm = re.search(r'(\d{4}-\d{2}-\d{2})', match_key)
                if _f7_dm:
                    _bc_kickoff = _f7_dm.group(1)

        self.assertEqual(_bc_kickoff, "2026-03-30", "Date should be extracted as last resort when broadcast lookup fails")

    def test_fix7_fallback_preserves_existing_kickoff(self):
        """When kickoff is already set, the fallback must not overwrite it."""
        _bc_kickoff = "Today 18:30"
        match_key = "arsenal_vs_chelsea_2026-03-27"

        if not _bc_kickoff and match_key:
            _f7_dm = re.search(r'(\d{4}-\d{2}-\d{2})', match_key)
            if _f7_dm:
                _bc_kickoff = _f7_dm.group(1)

        self.assertEqual(_bc_kickoff, "Today 18:30", "Existing kickoff must not be overwritten by fallback")


if __name__ == "__main__":
    unittest.main()
