"""FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 — AC-1 regression guard.

Premium tier (gold/diamond) edges MUST bypass `_PREGEN_HORIZON_HOURS`.
Silver/Bronze still respect the 240h window.

Synthetic edge_results fixture:
- Gold at +18 days (432h, beyond 240h horizon) — must survive
- Silver at +18 days (432h, beyond horizon) — must NOT survive
- Silver at +5 days (120h, within horizon) — must survive
- Bronze at +2 days (48h, within horizon) — must survive
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from scripts.pregenerate_narratives import _apply_premium_horizon_filter

SAST = ZoneInfo("Africa/Johannesburg")


def _mk(match_key: str, tier: str, hours_ahead: float, ref: datetime) -> dict:
    return {
        "match_key": match_key,
        "tier": tier,
        "_resolved_kickoff": ref + timedelta(hours=hours_ahead),
    }


def _scenario():
    now = datetime.now(SAST)
    cutoff = now + timedelta(hours=240)
    edges = [
        _mk("epl_liverpool_vs_chelsea_2026_05_09", "gold", 18 * 24, now),
        _mk("epl_arsenal_vs_spurs_2026_05_09", "diamond", 18 * 24, now),
        _mk("psl_chiefs_vs_pirates_far", "silver", 18 * 24, now),
        _mk("psl_sundowns_vs_amazulu_close", "silver", 5 * 24, now),
        _mk("psl_supersport_vs_galaxy_close", "bronze", 2 * 24, now),
        _mk("psl_polokwane_vs_stellies_far", "bronze", 18 * 24, now),
    ]
    return edges, cutoff


def test_gold_diamond_survive_horizon_filter():
    edges, cutoff = _scenario()
    out, _ = _apply_premium_horizon_filter(edges, cutoff)
    keys = {e["match_key"] for e in out}
    assert "epl_liverpool_vs_chelsea_2026_05_09" in keys, (
        "Gold edge at +18 days must survive horizon filter (premium bypass)"
    )
    assert "epl_arsenal_vs_spurs_2026_05_09" in keys, (
        "Diamond edge at +18 days must survive horizon filter (premium bypass)"
    )


def test_silver_bronze_respect_horizon():
    edges, cutoff = _scenario()
    out, _ = _apply_premium_horizon_filter(edges, cutoff)
    keys = {e["match_key"] for e in out}
    # Within-window Silver/Bronze keep their slots.
    assert "psl_sundowns_vs_amazulu_close" in keys
    assert "psl_supersport_vs_galaxy_close" in keys
    # Beyond-window Silver/Bronze are dropped (no premium bypass).
    assert "psl_chiefs_vs_pirates_far" not in keys, (
        "Silver edge at +18 days must be dropped — only premium tiers bypass horizon"
    )
    assert "psl_polokwane_vs_stellies_far" not in keys, (
        "Bronze edge at +18 days must be dropped — only premium tiers bypass horizon"
    )


def test_premium_bypass_counter_reports_overflow_only():
    edges, cutoff = _scenario()
    _, bypass_count = _apply_premium_horizon_filter(edges, cutoff)
    # 1 Gold + 1 Diamond beyond horizon = 2 bypass slots used.
    assert bypass_count == 2, (
        f"Premium bypass counter must report 2 (1 Gold + 1 Diamond beyond 240h), got {bypass_count}"
    )


def test_premium_within_horizon_does_not_inflate_bypass_count():
    now = datetime.now(SAST)
    cutoff = now + timedelta(hours=240)
    edges = [
        _mk("epl_man_city_vs_brentford_close", "gold", 4 * 24, now),
        _mk("psl_chiefs_vs_pirates_close", "silver", 4 * 24, now),
    ]
    out, bypass_count = _apply_premium_horizon_filter(edges, cutoff)
    assert len(out) == 2
    assert bypass_count == 0, (
        "Premium edges within horizon must not increment bypass counter — "
        "they would have survived under either policy"
    )


def test_edge_tier_field_recognised_when_tier_missing():
    """Some candidate builders write 'edge_tier' instead of 'tier'."""
    now = datetime.now(SAST)
    cutoff = now + timedelta(hours=240)
    edges = [
        {
            "match_key": "ucl_real_vs_arsenal_far",
            "edge_tier": "gold",  # uppercase
            "_resolved_kickoff": now + timedelta(hours=18 * 24),
        },
        {
            "match_key": "ucl_inter_vs_psg_far",
            "edge_tier": "DIAMOND",
            "_resolved_kickoff": now + timedelta(hours=18 * 24),
        },
    ]
    out, _ = _apply_premium_horizon_filter(edges, cutoff)
    keys = {e["match_key"] for e in out}
    assert "ucl_real_vs_arsenal_far" in keys
    assert "ucl_inter_vs_psg_far" in keys


def test_missing_kickoff_dropped_for_non_premium():
    """Non-premium edges with no resolvable kickoff are dropped (best-effort).

    Premium edges with missing kickoff are kept (we never silently drop premium).
    """
    now = datetime.now(SAST)
    cutoff = now + timedelta(hours=240)
    edges = [
        {"match_key": "premium_no_ko", "tier": "gold", "_resolved_kickoff": None},
        {"match_key": "silver_no_ko", "tier": "silver", "_resolved_kickoff": None},
    ]
    out, _ = _apply_premium_horizon_filter(edges, cutoff)
    keys = {e["match_key"] for e in out}
    assert "premium_no_ko" in keys, "Premium edges must never be silently dropped"
    assert "silver_no_ko" not in keys, "Silver with no kickoff cannot pass horizon check"


def test_brief_log_signature_present():
    """The PremiumOverflowCap log marker must be present in the source."""
    from pathlib import Path

    src = Path(__file__).parents[2] / "scripts" / "pregenerate_narratives.py"
    text = src.read_text(encoding="utf-8")
    assert "FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 PremiumOverflowCap" in text, (
        "Premium-overflow log signature must be present (EdgeOps observability)"
    )
    assert "FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 PremiumHorizonBypass" in text, (
        "Premium-horizon-bypass log signature must be present"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
