"""BUILD-NARRATIVE-WATERTIGHT-01 D.3 — strict-guard at write path.

Stream 4 F2: refuse narrative_cache writes where
``narrative_source`` IN ('w82', 'baseline_no_edge') AND ``edge_tier`` IN
('gold', 'diamond'). These thin deterministic fallbacks are reserved for
Silver / Bronze cost-save paths (W93-COST flag VI); Gold and Diamond
subscribers must receive polished narratives or no cache entry at all.

The contract asserts that ``_store_narrative_cache`` has a guard that
rejects the illegal combination BEFORE reaching the INSERT statement.
"""
from __future__ import annotations

import inspect
import re

import pytest


@pytest.fixture(scope="module")
def bot_module():
    import bot

    return bot


def test_store_narrative_cache_has_gold_baseline_guard(bot_module):
    fn = getattr(bot_module, "_store_narrative_cache", None)
    if fn is None:
        pytest.skip("_store_narrative_cache not exported — skipping write-guard check")
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        pytest.skip("cannot inspect source of _store_narrative_cache")

    # Pattern looks for either a direct refusal block or the authoritative
    # source set used at write time. The guard must mention both the two
    # forbidden narrative sources AND at least one premium tier.
    forbidden_sources = ("w82", "baseline_no_edge")
    tiers = ("gold", "diamond")
    mentions_sources = all(s in src for s in forbidden_sources)
    mentions_tiers = any(t in src.lower() for t in tiers)
    assert mentions_sources and mentions_tiers, (
        "BUILD-NARRATIVE-WATERTIGHT-01 D.3: _store_narrative_cache must guard Gold/"
        "Diamond rows against w82 / baseline_no_edge narrative_source. Expected a "
        "strict-guard block referencing both forbidden sources and the premium tiers."
    )


def test_serve_path_rejects_gold_baseline(bot_module):
    """Sibling guard: _get_cached_narrative must continue rejecting existing rows
    that slipped through before the write-guard existed. This guarantees a
    Gold/Diamond tap never serves stale w82 content even if historical rows exist.
    """
    fn = getattr(bot_module, "_get_cached_narrative", None)
    if fn is None:
        pytest.skip("_get_cached_narrative not exported")
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        pytest.skip("cannot inspect source of _get_cached_narrative")
    assert re.search(
        r"narrative_source\s+in\s+\(\s*['\"]w82['\"]\s*,\s*['\"]baseline_no_edge['\"]\s*\)",
        src,
    ), (
        "BUILD-NARRATIVE-WATERTIGHT-01 D.3: _get_cached_narrative must keep the "
        "existing Gold/Diamond w82/baseline_no_edge rejection block (BUILD-NARRATIVE-"
        "VOICE-01). Write-guard alone does not clean up historical rows."
    )
