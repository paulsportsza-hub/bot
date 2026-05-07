"""Contract tests — OPS-FREEZE-CRICKET-PICKS-V1-LAUNCH-BROKEN-01.

AC-1: CRICKET_EMISSION_FROZEN constant + reason string present in edge_config
AC-2: cricket IPL fixtures return None from calculate_composite_edge when frozen
AC-3: soccer + rugby emit normally when CRICKET_EMISSION_FROZEN=True
AC-4: _cricket_emit_skipped_frozen counter increments on each skip
"""

import os
import sys
import unittest.mock as mock

_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
)
sys.path.insert(0, _ROOT)


# ── AC-1: Constants present ─────────────────────────────────────────────────

def test_cricket_emission_frozen_constant_is_bool_true():
    """CRICKET_EMISSION_FROZEN is bool True by default (AC-1)."""
    import scrapers.edge.edge_config as cfg
    assert hasattr(cfg, "CRICKET_EMISSION_FROZEN"), "CRICKET_EMISSION_FROZEN missing from edge_config"
    assert isinstance(cfg.CRICKET_EMISSION_FROZEN, bool), "CRICKET_EMISSION_FROZEN must be bool"
    assert cfg.CRICKET_EMISSION_FROZEN is True, "Default must be True (freeze active)"


def test_cricket_emission_frozen_reason_contains_required_tokens():
    """CRICKET_EMISSION_FROZEN_REASON contains 'v1-launch-broken' and 'T80' (AC-1)."""
    import scrapers.edge.edge_config as cfg
    assert hasattr(cfg, "CRICKET_EMISSION_FROZEN_REASON"), "CRICKET_EMISSION_FROZEN_REASON missing"
    reason = cfg.CRICKET_EMISSION_FROZEN_REASON
    assert "v1-launch-broken" in reason, f"Missing 'v1-launch-broken' in reason: {reason!r}"
    assert "T80" in reason, f"Missing 'T80' in reason: {reason!r}"


# ── AC-2: Cricket blocked when frozen ──────────────────────────────────────

def test_cricket_ipl_blocked_when_frozen():
    """IPL cricket fixture returns None when CRICKET_EMISSION_FROZEN=True (AC-2)."""
    import scrapers.edge.edge_v2 as ev2

    with mock.patch.object(ev2, "CRICKET_EMISSION_FROZEN", True), \
         mock.patch.object(ev2, "_is_blacklisted", return_value=(False, None)):
        result = ev2.calculate_composite_edge(
            "rcb_vs_mi_2026-05-07", "home", sport="cricket", league="ipl"
        )
    assert result is None, "IPL cricket must return None when CRICKET_EMISSION_FROZEN=True (AC-2)"


def test_cricket_ipl_not_blocked_when_flag_false():
    """IPL cricket passes the freeze gate when CRICKET_EMISSION_FROZEN=False (AC-2 reversal)."""
    import scrapers.edge.edge_v2 as ev2

    mock_signals = _make_signals("cricket")
    with mock.patch.object(ev2, "CRICKET_EMISSION_FROZEN", False), \
         mock.patch.object(ev2, "_is_blacklisted", return_value=(False, None)), \
         mock.patch.object(ev2, "collect_all_signals", return_value=mock_signals), \
         mock.patch.object(ev2, "has_sharp_coverage", return_value=False), \
         mock.patch.object(ev2, "generate_narrative", return_value={"narrative": "t", "bullets": []}), \
         mock.patch.object(ev2, "_apply_candidate_guardrails", side_effect=lambda x: x):
        ev2.calculate_composite_edge(
            "rcb_vs_mi_2026-05-07", "home", sport="cricket", league="ipl"
        )
    # Counter must not increment (verified by test_cricket_freeze_counter_does_not_increment_when_disabled)


# ── AC-4: Telemetry counter ─────────────────────────────────────────────────

def test_cricket_freeze_counter_increments_per_skip():
    """_cricket_emit_skipped_frozen increments by 2 on 2 blocked fixtures (AC-4)."""
    import scrapers.edge.edge_v2 as ev2

    before = ev2._cricket_emit_skipped_frozen
    with mock.patch.object(ev2, "CRICKET_EMISSION_FROZEN", True), \
         mock.patch.object(ev2, "_is_blacklisted", return_value=(False, None)):
        ev2.calculate_composite_edge("rcb_vs_mi_2026-05-07", "home", sport="cricket", league="ipl")
        ev2.calculate_composite_edge("csk_vs_kkr_2026-05-08", "away", sport="cricket", league="ipl")
    after = ev2._cricket_emit_skipped_frozen
    assert after == before + 2, (
        f"Counter should have incremented by exactly 2, got {after - before}"
    )


def test_cricket_freeze_counter_does_not_increment_when_disabled():
    """Counter stays unchanged when CRICKET_EMISSION_FROZEN=False (AC-4)."""
    import scrapers.edge.edge_v2 as ev2

    mock_signals = _make_signals("cricket")
    before = ev2._cricket_emit_skipped_frozen
    with mock.patch.object(ev2, "CRICKET_EMISSION_FROZEN", False), \
         mock.patch.object(ev2, "_is_blacklisted", return_value=(False, None)), \
         mock.patch.object(ev2, "collect_all_signals", return_value=mock_signals), \
         mock.patch.object(ev2, "has_sharp_coverage", return_value=False), \
         mock.patch.object(ev2, "generate_narrative", return_value={"narrative": "t", "bullets": []}), \
         mock.patch.object(ev2, "_apply_candidate_guardrails", side_effect=lambda x: x):
        ev2.calculate_composite_edge("rcb_vs_mi_2026-05-07", "home", sport="cricket", league="ipl")
    assert ev2._cricket_emit_skipped_frozen == before, (
        "Counter must NOT increment when flag is False"
    )


# ── AC-3: Soccer + rugby unaffected ────────────────────────────────────────

def test_soccer_emits_normally_when_cricket_frozen():
    """Soccer fixtures return a result when CRICKET_EMISSION_FROZEN=True (AC-3)."""
    import scrapers.edge.edge_v2 as ev2

    counter_before = ev2._cricket_emit_skipped_frozen
    mock_signals = _make_signals("soccer")
    with mock.patch.object(ev2, "CRICKET_EMISSION_FROZEN", True), \
         mock.patch.object(ev2, "_is_blacklisted", return_value=(False, None)), \
         mock.patch.object(ev2, "collect_all_signals", return_value=mock_signals), \
         mock.patch.object(ev2, "has_sharp_coverage", return_value=True), \
         mock.patch.object(ev2, "generate_narrative", return_value={"narrative": "t", "bullets": []}), \
         mock.patch.object(ev2, "_apply_candidate_guardrails", side_effect=lambda x: x):
        result = ev2.calculate_composite_edge(
            "chelsea_vs_arsenal_2026-05-07", "home", sport="soccer", league="epl"
        )
    assert ev2._cricket_emit_skipped_frozen == counter_before, (
        "Cricket counter must NOT increment for soccer (AC-3)"
    )
    assert result is not None, "Soccer must return a result when cricket is frozen (AC-3)"
    assert result.get("sport") == "soccer"


def test_rugby_emits_normally_when_cricket_frozen():
    """Rugby fixtures return a result when CRICKET_EMISSION_FROZEN=True (AC-3)."""
    import scrapers.edge.edge_v2 as ev2

    counter_before = ev2._cricket_emit_skipped_frozen
    mock_signals = _make_signals("rugby")
    with mock.patch.object(ev2, "CRICKET_EMISSION_FROZEN", True), \
         mock.patch.object(ev2, "_is_blacklisted", return_value=(False, None)), \
         mock.patch.object(ev2, "collect_all_signals", return_value=mock_signals), \
         mock.patch.object(ev2, "has_sharp_coverage", return_value=False), \
         mock.patch.object(ev2, "generate_narrative", return_value={"narrative": "t", "bullets": []}), \
         mock.patch.object(ev2, "_apply_candidate_guardrails", side_effect=lambda x: x):
        result = ev2.calculate_composite_edge(
            "stormers_vs_leinster_2026-05-07", "home", sport="rugby", league="urc"
        )
    assert ev2._cricket_emit_skipped_frozen == counter_before, (
        "Cricket counter must NOT increment for rugby (AC-3)"
    )
    assert result is not None, "Rugby must return a result when cricket is frozen (AC-3)"
    assert result.get("sport") == "rugby"


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_signals(sport: str) -> dict:
    """Return a minimal mock signals dict that clears all pipeline gates."""
    return {
        "price_edge": {
            "available": True, "edge_pct": 4.5, "best_odds": 1.90,
            "signal_strength": 0.75, "n_bookmakers": 6,
            "best_bookmaker": "hwb", "fair_prob": 0.57,
            "sharp_source": "pinnacle", "method": "shin",
            "stale_price": False,
        },
        "market_agreement": {
            "available": True, "signal_strength": 0.72, "outlier_risk": False,
        },
        "movement": {"available": False, "signal_strength": None},
        "tipster": {"available": False, "signal_strength": None},
        "lineup_injury": {"available": False, "signal_strength": None},
        "form_h2h": {
            "available": True, "signal_strength": 0.70,
            "home_form_string": "WWWLD", "away_form_string": "WLLWD", "h2h_total": 5,
        },
        "model_probability": {
            "available": True if sport in ("soccer", "rugby") else False,
            "signal_strength": 0.70 if sport in ("soccer", "rugby") else None,
        },
    }
