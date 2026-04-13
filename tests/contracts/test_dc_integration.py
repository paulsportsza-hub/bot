"""Contract tests for P4-05 — DC + CLV + Glicko-2 integration into edge_v2.

AC-1: DC probabilities used as model_probability signal for soccer
AC-2: USE_DIXON_COLES flag selects DC vs Elo soccer weight profiles
AC-3: Non-soccer sports excluded from model_probability composite
AC-4: Unknown teams → fallback to Elo gracefully, no crash
AC-5: clv_avg + clv_sample_size always present in calculate_composite_edge() output
AC-6: Non-soccer model_probability has weight=0 (excluded from composite)
AC-7: DC soccer weight for model_probability is 25–30%

Total: 9 tests.
"""

import os
import sys
import unittest.mock as mock

_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
)
sys.path.insert(0, _ROOT)


# ---------------------------------------------------------------------------
# AC-2 / AC-7: Feature flag — weight profiles
# ---------------------------------------------------------------------------

def test_dc_weights_active_when_flag_true():
    """USE_DIXON_COLES=True → soccer uses DC_SOCCER_WEIGHTS with model_probability 25–30%."""
    import scrapers.edge.edge_config as cfg

    with mock.patch.object(cfg, "has_sharp_coverage", return_value=True):
        # Patch the module-level flag directly
        original = cfg.USE_DIXON_COLES
        try:
            cfg.USE_DIXON_COLES = True
            weights = cfg.get_weights("soccer", "epl")
        finally:
            cfg.USE_DIXON_COLES = original

    assert "model_probability" in weights, "model_probability key missing from DC weights (AC-2)"
    mp = weights["model_probability"]
    assert 0.25 <= mp <= 0.30, f"DC model_probability weight={mp}, expected 0.25–0.30 (AC-7)"
    # price_edge should be reduced to accommodate DC signal
    assert weights["price_edge"] <= 0.22, (
        f"price_edge={weights['price_edge']} should reduce when DC active"
    )


def test_elo_weights_active_when_flag_false():
    """USE_DIXON_COLES=False → soccer uses ELO_SOCCER_WEIGHTS with model_probability ~20%."""
    import scrapers.edge.edge_config as cfg

    with mock.patch.object(cfg, "has_sharp_coverage", return_value=True):
        original = cfg.USE_DIXON_COLES
        try:
            cfg.USE_DIXON_COLES = False
            weights = cfg.get_weights("soccer", "epl")
        finally:
            cfg.USE_DIXON_COLES = original

    assert "model_probability" in weights, "model_probability key must exist in Elo soccer weights"
    mp = weights["model_probability"]
    assert abs(mp - 0.20) < 0.02, f"Elo model_probability={mp}, expected ~0.20"


def test_non_soccer_sports_have_zero_model_probability_weight():
    """Rugby and cricket SPORT_WEIGHTS carry model_probability=0.0 (AC-6)."""
    import scrapers.edge.edge_config as cfg

    # URC is in SA_ONLY_LEAGUES so has_sharp_coverage may return False;
    # use mock to isolate weight profile selection from DB checks.
    with mock.patch.object(cfg, "has_sharp_coverage", return_value=True):
        rugby_w = cfg.get_weights("rugby", "six_nations")
        cricket_w = cfg.get_weights("cricket", "ipl")

    # RUGBY-FIX-01: rugby now has model_probability=0.18 (Glicko-2 active)
    assert abs(rugby_w.get("model_probability", 0) - 0.18) < 0.02, (
        f"Rugby model_probability should be ~0.18 (Glicko-2 active, RUGBY-FIX-01), got {rugby_w.get('model_probability')}"
    )
    assert cricket_w.get("model_probability", 0) == 0.0, (
        "Cricket model_probability must be 0 (no model active for cricket)"
    )


# ---------------------------------------------------------------------------
# AC-3: Non-soccer signal exclusion
# ---------------------------------------------------------------------------

def test_model_probability_returns_signal_for_rugby():
    """RUGBY-FIX-01: rugby match → Glicko-2 signal (included in composite)."""
    from scrapers.edge.signal_collectors import collect_model_probability_signal

    result = collect_model_probability_signal("sharks_vs_bulls_2026-03-15", "home", "rugby")

    # RUGBY-FIX-01: rugby now uses Glicko-2 model — returns a real signal
    assert result["available"] is True, (
        "Rugby model_probability should be available (Glicko-2 active, RUGBY-FIX-01)"
    )
    assert isinstance(result["signal_strength"], float), (
        f"Rugby signal_strength should be a float, got {type(result['signal_strength'])}"
    )


def test_model_probability_returns_none_strength_for_cricket():
    """Cricket match → signal_strength=None (AC-3)."""
    from scrapers.edge.signal_collectors import collect_model_probability_signal

    result = collect_model_probability_signal("india_vs_australia_2026-03-15", "home", "cricket")

    assert result["signal_strength"] is None, "Cricket must return signal_strength=None (AC-3)"
    assert result["available"] is False


# ---------------------------------------------------------------------------
# AC-1: Soccer path — DC prediction wired in
# ---------------------------------------------------------------------------

def test_soccer_dc_signal_uses_prediction():
    """Soccer + DC prediction available → signal_strength in (0,1], model_used='dixon_coles'."""
    from scrapers.edge.signal_collectors import collect_model_probability_signal

    fake_pred = {
        "home_win": 0.50,
        "draw": 0.25,
        "away_win": 0.25,
        "expected_home": 1.8,
        "expected_away": 1.1,
        "confidence": "medium",
    }

    with mock.patch("scrapers.edge.edge_config.USE_DIXON_COLES", True), \
         mock.patch("scrapers.elo.elo_helper.get_dc_probability", return_value=fake_pred):
        result = collect_model_probability_signal(
            "arsenal_vs_chelsea_2026-03-15", "home", "soccer"
        )

    assert result["available"] is True, "DC prediction available → signal should be available"
    assert result["model_used"] == "dixon_coles", "model_used should be 'dixon_coles' (AC-1)"
    assert 0.0 <= result["signal_strength"] <= 1.0, "signal_strength must be bounded [0,1]"
    # home_win=50% → strength ≈ 0.5 + (0.50-0.333)*1.5 ≈ 0.75
    assert result["signal_strength"] > 0.5, "50% home prob should give strength > 0.5"
    assert "expected_home" in result, "DC metadata (expected_home) should be in result"


# ---------------------------------------------------------------------------
# AC-4: Fallback when DC unavailable
# ---------------------------------------------------------------------------

def test_fallback_to_elo_when_dc_returns_none():
    """DC returns None (unfitted/unknown team) → falls back to Elo, no crash (AC-4)."""
    from scrapers.edge.signal_collectors import collect_model_probability_signal

    fake_elo_pred = {
        "home_win": 0.40,
        "draw": 0.30,
        "away_win": 0.30,
        "rating_system": "glicko2",
        "home_mu": 1500,
        "away_mu": 1450,
    }

    with mock.patch("scrapers.edge.edge_config.USE_DIXON_COLES", True), \
         mock.patch("scrapers.elo.elo_helper.get_dc_probability", return_value=None), \
         mock.patch("scrapers.elo.elo_helper.get_elo_probability", return_value=fake_elo_pred):
        result = collect_model_probability_signal(
            "unknown_zzz_vs_unknown_aaa_2026-03-15", "home", "soccer"
        )

    assert result.get("signal_strength") is not None, "Elo fallback must return a valid signal"
    assert result["available"] is True
    assert result["model_used"] in ("glicko2", "elo", "glicko2"), (
        f"Expected elo/glicko2 fallback, got model_used={result.get('model_used')}"
    )


def test_no_crash_when_both_models_unavailable():
    """Both DC and Elo return None → signal_strength=None, no crash (AC-4)."""
    from scrapers.edge.signal_collectors import collect_model_probability_signal

    with mock.patch("scrapers.edge.edge_config.USE_DIXON_COLES", True), \
         mock.patch("scrapers.elo.elo_helper.get_dc_probability", return_value=None), \
         mock.patch("scrapers.elo.elo_helper.get_elo_probability", return_value=None):
        result = collect_model_probability_signal(
            "unknown_zzz_vs_unknown_aaa_2026-03-15", "home", "soccer"
        )

    assert result["signal_strength"] is None, "Both models None → signal_strength must be None"
    assert result["available"] is False


# ---------------------------------------------------------------------------
# AC-5: CLV metadata keys always present in edge output
# ---------------------------------------------------------------------------

def test_clv_metadata_keys_present_in_edge_output():
    """calculate_composite_edge() result always has clv_avg and clv_sample_size (AC-5)."""
    from scrapers.edge.edge_v2 import calculate_composite_edge

    fake_price = {
        "available": True,
        "edge_pct": 4.0,
        "fair_prob": 0.40,
        "best_odds": 2.90,
        "best_bookmaker": "betway",
        "n_bookmakers": 3,
        "stale_price": False,
        "method": "consensus",
        "sharp_source": "",
    }
    fake_signals = {
        "price_edge": fake_price,
        "market_agreement": {"signal_strength": 0.65, "available": True},
        "movement": {"signal_strength": 0.55, "available": True},
        "tipster": {"signal_strength": None, "available": False},
        "lineup_injury": {"signal_strength": None, "available": False},
        "form_h2h": {"signal_strength": None, "available": False},
        "model_probability": {"signal_strength": None, "available": False},
        "weather": {"signal_strength": None, "available": False},
    }

    with mock.patch("scrapers.edge.edge_v2.collect_all_signals", return_value=fake_signals), \
         mock.patch("scrapers.edge.edge_v2.has_sharp_coverage", return_value=True), \
         mock.patch("scrapers.edge.edge_v2.get_weights", return_value={
             "price_edge": 0.35, "market_agreement": 0.12, "movement": 0.13,
             "tipster": 0.08, "lineup_injury": 0.08, "form_h2h": 0.14,
             "model_probability": 0.0, "weather": 0.0,
         }), \
         mock.patch("scrapers.edge.edge_v2.assign_tier", return_value="silver"), \
         mock.patch("scrapers.edge.edge_v2.get_tier_display", return_value="Silver"), \
         mock.patch("scrapers.edge.edge_v2.generate_narrative",
                    return_value={"narrative": "test narrative", "bullets": []}), \
         mock.patch("scrapers.edge.edge_v2.validate_tier", return_value="silver"), \
         mock.patch("scrapers.edge.edge_v2.cap_ev", return_value=(0.04, "ok")), \
         mock.patch("scrapers.sharp.clv_stats.get_clv_stats",
                    return_value={"total_bets": 5, "avg_clv_pct": 1.2}):
        result = calculate_composite_edge(
            "arsenal_vs_chelsea_2026-03-15", "home",
            market_type="1x2", sport="soccer", league="epl",
        )

    assert result is not None, "Expected non-None edge result with valid mock inputs"
    assert "clv_avg" in result, "clv_avg key missing from edge output (AC-5)"
    assert "clv_sample_size" in result, "clv_sample_size key missing from edge output (AC-5)"
