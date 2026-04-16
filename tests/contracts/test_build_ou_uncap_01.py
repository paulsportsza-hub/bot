"""Contract tests for BUILD-OU-UNCAP-01.

AC-1: OU_SHARP_BENCHMARK_ENABLED = True flag exists in edge_config.py
AC-2: OU_MAX_TIER = None when flag is True — O/U can reach Gold/Diamond
AC-3: BTTS_MAX_TIER = "silver" in edge_config.py — BTTS still capped
AC-4: tier_engine.py checks O/U and BTTS caps in separate conditionals
AC-5: signal_collectors.py maps "over_under" → "OVER_UNDER_25"
AC-6: O/U with composite=70, edge_pct=6.0 → "gold" or higher (not silver) when flag True
AC-7: BTTS with composite=70, edge_pct=6.0 → "silver" (BTTS_MAX_TIER enforced)
AC-8: flipping OU_SHARP_BENCHMARK_ENABLED = False → O/U capped at silver
"""

import os
import sys
import importlib
from unittest import mock

_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
)
sys.path.insert(0, _ROOT)


# ---------------------------------------------------------------------------
# AC-1: OU_SHARP_BENCHMARK_ENABLED exists in edge_config
# ---------------------------------------------------------------------------

def test_ou_sharp_benchmark_enabled_exists():
    import scrapers.edge.edge_config as cfg
    assert hasattr(cfg, "OU_SHARP_BENCHMARK_ENABLED"), (
        "OU_SHARP_BENCHMARK_ENABLED must exist in edge_config.py"
    )


# ---------------------------------------------------------------------------
# AC-2: OU_MAX_TIER is None when flag is True
# ---------------------------------------------------------------------------

def test_ou_max_tier_is_none_when_flag_true():
    import scrapers.edge.edge_config as cfg
    assert cfg.OU_SHARP_BENCHMARK_ENABLED is True, (
        "OU_SHARP_BENCHMARK_ENABLED must be True (production default)"
    )
    assert cfg.OU_MAX_TIER is None, (
        "OU_MAX_TIER must be None when OU_SHARP_BENCHMARK_ENABLED=True"
    )


# ---------------------------------------------------------------------------
# AC-3: BTTS_MAX_TIER = "silver"
# ---------------------------------------------------------------------------

def test_btts_max_tier_is_silver():
    import scrapers.edge.edge_config as cfg
    assert hasattr(cfg, "BTTS_MAX_TIER"), (
        "BTTS_MAX_TIER must exist in edge_config.py"
    )
    assert cfg.BTTS_MAX_TIER == "silver", (
        f"BTTS_MAX_TIER must be 'silver', got {cfg.BTTS_MAX_TIER!r}"
    )


# ---------------------------------------------------------------------------
# AC-4: tier_engine imports both OU_MAX_TIER and BTTS_MAX_TIER
# ---------------------------------------------------------------------------

def test_tier_engine_imports_btts_max_tier():
    import scrapers.edge.tier_engine as te
    # If BTTS_MAX_TIER is imported and used, assign_tier("btts") must apply a cap.
    # We verify the cap is active by calling with high-composite BTTS.
    result = te.assign_tier(
        composite=70, edge_pct=6.0, confirming=2,
        red_flags=[], market_type="btts",
    )
    assert result == "silver", (
        f"BTTS cap must hold at 'silver' regardless of composite; got {result!r}"
    )


# ---------------------------------------------------------------------------
# AC-5: signal_collectors maps over_under → OVER_UNDER_25
# ---------------------------------------------------------------------------

def test_signal_collectors_ou_sharp_market_type():
    """The sharp_mt mapping in signal_collectors must map over_under → OVER_UNDER_25."""
    import ast
    sc_path = os.path.join(_ROOT, "scrapers", "edge", "signal_collectors.py")
    with open(sc_path) as f:
        source = f.read()
    # Verify the mapping exists literally in the source
    assert '"over_under": "OVER_UNDER_25"' in source, (
        'signal_collectors.py must contain "over_under": "OVER_UNDER_25" in the sharp_mt mapping'
    )


# ---------------------------------------------------------------------------
# AC-6: O/U composite=70, edge_pct=6.0 → gold or higher when flag True
# ---------------------------------------------------------------------------

def test_ou_reaches_gold_when_flag_enabled():
    """With OU_SHARP_BENCHMARK_ENABLED=True (OU_MAX_TIER=None), high-composite O/U must reach gold."""
    import scrapers.edge.tier_engine as te
    result = te.assign_tier(
        composite=70, edge_pct=6.0, confirming=1,
        red_flags=[], market_type="over_under",
    )
    _TIER_ORDER = ["bronze", "silver", "gold", "diamond"]
    assert result is not None, "Expected a tier, got None"
    assert _TIER_ORDER.index(result) >= _TIER_ORDER.index("gold"), (
        f"O/U must reach at least 'gold' when OU_SHARP_BENCHMARK_ENABLED=True, got {result!r}"
    )


# ---------------------------------------------------------------------------
# AC-7: BTTS composite=70, edge_pct=6.0 → silver (BTTS_MAX_TIER enforced)
# ---------------------------------------------------------------------------

def test_btts_capped_at_silver():
    """BTTS must be capped at silver regardless of composite."""
    import scrapers.edge.tier_engine as te
    result = te.assign_tier(
        composite=70, edge_pct=6.0, confirming=2,
        red_flags=[], market_type="btts",
    )
    assert result == "silver", (
        f"BTTS must be capped at 'silver', got {result!r}"
    )


# ---------------------------------------------------------------------------
# AC-8: flipping OU_SHARP_BENCHMARK_ENABLED=False → O/U capped at silver
# ---------------------------------------------------------------------------

def test_ou_capped_at_silver_when_flag_false():
    """When OU_MAX_TIER is patched to 'silver' (flag=False), O/U must be capped."""
    import scrapers.edge.tier_engine as te
    with mock.patch.object(te, "OU_MAX_TIER", "silver"):
        result = te.assign_tier(
            composite=70, edge_pct=6.0, confirming=1,
            red_flags=[], market_type="over_under",
        )
    assert result == "silver", (
        f"O/U must be capped at 'silver' when OU_MAX_TIER='silver' (flag=False), got {result!r}"
    )
