"""
FIX-PREGEN-WARM-COUNT-01-CLOSEOUT — Unit test for _background_pregen_fill hot-keys path.

Branch under test:
    _background_pregen_fill() when _hot_tips_cache contains tips with match keys
    (i.e. _hot_keys is non-empty, per-fixture path).

Pre-fix behaviour:
    log.info("Pregen [background]: started ... warm_count=%d", _warm_count)
    was reached BEFORE _warm_count was assigned in the hot-keys branch
    → UnboundLocalError: local variable '_warm_count' referenced before assignment.

Post-fix behaviour:
    _warm_count = 0 initialisation at function top ensures the variable is always
    defined regardless of which branch is taken.
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import bot


@pytest.mark.asyncio
async def test_background_pregen_fill_hot_keys_no_unboundlocalerror():
    """Hot-keys branch must not raise UnboundLocalError on _warm_count.

    Setup: cache contains one tip with a match_key. _count_uncached_hot_tips
    returns 1 (uncached tip exists), so the function proceeds past the skip-guard
    and reaches the log.info(... _warm_count) line.  Before the fix this raised
    UnboundLocalError; after the fix _warm_count = 0 is set at function top.
    """
    fake_tips = [{"match_key": "chiefs_vs_pirates_2026-04-25", "ev": 0.05}]

    with (
        patch.object(bot, "_hot_tips_cache", {"global": {"tips": fake_tips}}),
        patch.object(bot, "_pregen_active", False),
        patch.object(bot, "_pregen_lock", asyncio.Lock()),
        patch.object(bot, "_count_uncached_hot_tips", return_value=1),
        patch("scripts.pregenerate_narratives.main", new_callable=AsyncMock),
    ):
        # Must not raise UnboundLocalError — this is the AC-3 regression guard.
        await bot._background_pregen_fill()


@pytest.mark.asyncio
async def test_background_pregen_fill_hot_keys_all_cached_skips():
    """When every hot tip already has a fresh narrative, the function returns early
    without calling pregen.  _warm_count must still be defined (= 0) even on the
    skip path so the log.info call after lock acquisition never runs unguarded."""
    fake_tips = [{"match_key": "sundowns_vs_galaxy_2026-04-26"}]

    with (
        patch.object(bot, "_hot_tips_cache", {"global": {"tips": fake_tips}}),
        patch.object(bot, "_pregen_active", False),
        patch.object(bot, "_pregen_lock", asyncio.Lock()),
        patch.object(bot, "_count_uncached_hot_tips", return_value=0),
        patch("scripts.pregenerate_narratives.main", new_callable=AsyncMock) as mock_pregen,
    ):
        await bot._background_pregen_fill()
        mock_pregen.assert_not_awaited()
