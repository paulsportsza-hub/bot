"""BUILD-NARRATIVE-WATERTIGHT-01 D.3 — premium W82 write-path policy.

The old blanket refusal for ``narrative_source`` IN ('w82', 'baseline_no_edge')
and premium tiers was lifted when W82 became the canonical narrative path. The
write path must instead run the unified persistence validator and refuse
premium rows that fail CRITICAL or MAJOR gates.

The serve path likewise must not reject premium W82 rows solely by source; it
keeps freshness and validator-era guards while allowing W82 as the safety-net
cache source.
"""
from __future__ import annotations

import inspect

import pytest


@pytest.fixture(scope="module")
def bot_module():
    import bot

    return bot


def test_store_narrative_cache_has_premium_validator_guard(bot_module):
    fn = getattr(bot_module, "_store_narrative_cache", None)
    if fn is None:
        pytest.skip("_store_narrative_cache not exported — skipping write-guard check")
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        pytest.skip("cannot inspect source of _store_narrative_cache")

    assert "Rule 24 premium-W82 refusal lifted" in src
    assert "validate_narrative_for_persistence" in src
    assert '("gold", "diamond")' in src
    assert "PremiumValidatorRefused" in src
    assert "return" in src[src.index("PremiumValidatorRefused"):], (
        "Premium validator failures must still refuse persistence before INSERT."
    )


def test_serve_path_allows_premium_w82_safety_net(bot_module):
    """Sibling guard: _get_cached_narrative must preserve the lifted premium-W82
    policy and not reintroduce the removed blanket rejection block.
    """
    fn = getattr(bot_module, "_get_cached_narrative", None)
    if fn is None:
        pytest.skip("_get_cached_narrative not exported")
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        pytest.skip("cannot inspect source of _get_cached_narrative")
    assert "serve w82 baselines for premium tiers" in src
    assert "serving w82 baseline as safety-net" in src
    start = src.index('if narrative_source in ("w82", "baseline_no_edge")')
    end = src.index("# MY-MATCHES-RELIABILITY-FIX", start)
    premium_w82_block = src[start:end]
    assert "\n                    return None" not in premium_w82_block, (
        "Premium W82 rows must not be rejected solely by narrative_source."
    )
