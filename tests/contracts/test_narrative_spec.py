"""W82-SPEC: Tests for narrative_spec.py.

Covers classification boundaries, coherence enforcement, TONE_BANDS structure,
and risk assessment. All tests are pure Python — no bot.py import, no LLM, no DB.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from narrative_spec import (
    NarrativeSpec,
    TONE_BANDS,
    _classify_evidence,
    _check_coherence,
    _enforce_coherence,
    _build_risk_factors,
    _assess_risk_severity,
    _humanise_league,
    _build_outcome_label,
    _build_h2h_summary,
    _build_evidence_clauses,
    # W82-RENDER
    _ordinal_r,
    _pick,
    _coach_possessive,
    _parse_wdl,
    _sentence_case,
    _render_team_para,
    _render_setup,
    _render_edge,
    _render_risk,
    _render_verdict,
    _render_baseline,
)


# ── _classify_evidence() — boundary tests ─────────────────────────────────────

class TestClassifyEvidence:
    """All 5 cases from the mandatory checklist + edge cases."""

    def test_zero_signals_returns_speculative_cautious(self):
        ev_class, tone, action, sizing = _classify_evidence({"confirming_signals": 0})
        assert ev_class == "speculative"
        assert tone == "cautious"
        assert action == "speculative punt"
        assert sizing == "tiny exposure"

    def test_zero_ev_explicit_returns_monitor(self):
        """VERDICT-FIX: EV=0.0 → monitor posture, not PASS recommendation."""
        ev_class, tone, action, sizing = _classify_evidence(
            {"confirming_signals": 2, "edge_pct": 0.0}
        )
        assert ev_class == "speculative"
        assert tone == "cautious"
        assert action == "monitor"
        assert sizing == "monitor"

    def test_negative_ev_returns_monitor(self):
        """VERDICT-FIX: Negative EV → monitor posture, not PASS recommendation."""
        ev_class, tone, action, sizing = _classify_evidence(
            {"confirming_signals": 3, "edge_pct": -1.5}
        )
        assert action == "monitor"

    def test_one_signal_returns_lean_moderate(self):
        ev_class, tone, action, sizing = _classify_evidence(
            {"confirming_signals": 1, "edge_pct": 3.0}
        )
        assert ev_class == "speculative"
        assert tone == "cautious"
        assert action == "speculative punt"
        assert sizing == "tiny exposure"

    def test_three_signals_returns_supported_confident(self):
        ev_class, tone, action, sizing = _classify_evidence(
            {"confirming_signals": 3, "edge_pct": 5.0}
        )
        assert ev_class == "supported"
        assert tone == "confident"
        assert action == "back"
        assert sizing == "standard stake"

    def test_five_signals_high_composite_high_ev_returns_conviction_strong(self):
        ev_class, tone, action, sizing = _classify_evidence({
            "confirming_signals": 5,
            "composite_score": 65,
            "edge_pct": 6,
        })
        assert ev_class == "supported"
        assert tone == "confident"
        assert action == "back"
        assert sizing == "standard stake"

    def test_two_signals_eight_hour_stale_returns_lean_moderate(self):
        """2 signals - 1 stale penalty (8h >= 6h) = 1 effective → downgrade one EV bucket."""
        ev_class, tone, action, sizing = _classify_evidence({
            "confirming_signals": 2,
            "edge_pct": 5.0,
            "stale_minutes": 480,  # 8 hours
        })
        assert ev_class == "lean"
        assert tone == "moderate"
        assert action == "lean"
        assert sizing == "small stake"

    def test_stale_penalty_applied_at_360_minutes(self):
        """Stale penalty kicks in at exactly 360 minutes."""
        ev_class_with_stale, _, _, _ = _classify_evidence({
            "confirming_signals": 1,
            "edge_pct": 3.0,
            "stale_minutes": 360,
        })
        ev_class_no_stale, _, _, _ = _classify_evidence({
            "confirming_signals": 1,
            "edge_pct": 3.0,
            "stale_minutes": 359,
        })
        assert ev_class_with_stale == "speculative"   # 1 - 1 stale = 0 effective
        assert ev_class_no_stale == "speculative"     # EV bucket 2-4 downgraded by low support

    def test_movement_against_applies_penalty(self):
        """Movement against applies -1 penalty to effective support."""
        ev_class, tone, _, _ = _classify_evidence({
            "confirming_signals": 1,
            "edge_pct": 3.0,
            "movement_direction": "against",
        })
        assert ev_class == "speculative"   # 1 - 1 movement = 0 effective
        assert tone == "cautious"

    def test_four_signals_low_composite_stays_supported(self):
        """4+ signals but composite < 60 → supported, not conviction."""
        ev_class, tone, action, _ = _classify_evidence({
            "confirming_signals": 4,
            "composite_score": 55,
            "edge_pct": 6,
        })
        assert ev_class == "supported"
        assert tone == "confident"
        assert action == "back"

    def test_four_signals_high_composite_but_low_ev_stays_supported(self):
        """4+ signals, composite >= 60, but ev < 5 → supported."""
        ev_class, tone, _, _ = _classify_evidence({
            "confirming_signals": 4,
            "composite_score": 65,
            "edge_pct": 4.9,
        })
        assert ev_class == "supported"
        assert tone == "confident"

    def test_sub_two_percent_ev_is_always_speculative(self):
        ev_class, tone, action, sizing = _classify_evidence({
            "confirming_signals": 4,
            "edge_pct": 1.2,
            "composite_score": 70,
        })
        assert ev_class == "speculative"
        assert tone == "cautious"
        assert action == "speculative punt"
        assert sizing == "tiny exposure"

    def test_zero_signals_cap_high_ev_at_speculative(self):
        ev_class, tone, action, sizing = _classify_evidence({
            "confirming_signals": 0,
            "edge_pct": 8.5,
            "composite_score": 75,
        })
        assert ev_class == "supported"
        assert tone == "confident"
        assert action == "back"
        assert sizing == "standard stake"

    def test_high_ev_with_two_signals_shifts_down_one_tier(self):
        ev_class, tone, action, sizing = _classify_evidence({
            "confirming_signals": 2,
            "edge_pct": 7.4,
            "composite_score": 63,
        })
        assert ev_class == "supported"
        assert tone == "confident"
        assert action == "back"
        assert sizing == "standard stake"

    def test_high_ev_with_one_signal_keeps_standard_stake_floor(self):
        ev_class, tone, action, sizing = _classify_evidence({
            "confirming_signals": 1,
            "edge_pct": 10.0,
            "composite_score": 48,
        })
        assert ev_class == "supported"
        assert tone == "confident"
        assert action == "back"
        assert sizing == "standard stake"

    def test_high_ev_with_stale_and_adverse_movement_keeps_standard_stake_floor(self):
        ev_class, tone, action, sizing = _classify_evidence({
            "confirming_signals": 2,
            "edge_pct": 9.3,
            "stale_minutes": 480,
            "movement_direction": "against",
        })
        assert ev_class == "supported"
        assert tone == "confident"
        assert action == "back"
        assert sizing == "standard stake"

    def test_missing_keys_default_to_speculative(self):
        """Empty dict → all defaults → 0 effective → speculative."""
        ev_class, tone, action, sizing = _classify_evidence({})
        assert ev_class == "speculative"
        assert tone == "cautious"
        assert action == "speculative punt"
        assert sizing == "tiny exposure"


# ── TONE_BANDS structure ───────────────────────────────────────────────────────

class TestToneBands:
    """Structural tests for TONE_BANDS dict."""

    def test_all_four_bands_present(self):
        assert set(TONE_BANDS.keys()) == {"cautious", "moderate", "confident", "strong"}

    def test_each_band_has_allowed_and_banned(self):
        for band_name, band in TONE_BANDS.items():
            assert "allowed" in band, f"{band_name} missing 'allowed'"
            assert "banned" in band, f"{band_name} missing 'banned'"

    def test_banned_phrases_non_empty_for_all_bands(self):
        for band_name, band in TONE_BANDS.items():
            assert len(band["banned"]) > 0, f"{band_name} has empty banned list"

    def test_slam_dunk_banned_in_moderate_and_confident(self):
        """'slam dunk' is banned in moderate and confident (strong uses 'lock' etc.)."""
        assert "slam dunk" in TONE_BANDS["moderate"]["banned"]
        assert "slam dunk" in TONE_BANDS["confident"]["banned"]
        # 'strong' uses 'guaranteed'/'lock'/'no-brainer'/"can't lose" instead
        assert "guaranteed" in TONE_BANDS["strong"]["banned"]

    def test_cautious_bans_strong_language(self):
        assert "must back" in TONE_BANDS["cautious"]["banned"]
        assert "no-brainer" in TONE_BANDS["cautious"]["banned"]

    def test_strong_allows_market_mispriced(self):
        assert "market mispriced" in TONE_BANDS["strong"]["allowed"]

    def test_strong_bans_guaranteed(self):
        assert "guaranteed" in TONE_BANDS["strong"]["banned"]


# ── _check_coherence() — contradiction detection ───────────────────────────────

class TestCheckCoherence:
    """Tests for all 6 contradiction patterns."""

    def _make_spec(self, **kwargs) -> NarrativeSpec:
        """Create a minimally valid NarrativeSpec with overrides."""
        defaults = dict(
            home_name="Home FC", away_name="Away FC",
            competition="Premier League", sport="soccer",
            home_story_type="neutral", away_story_type="neutral",
            support_level=0, evidence_class="speculative",
            tone_band="cautious", verdict_action="speculative punt",
            verdict_sizing="tiny exposure",
            risk_severity="moderate", stale_minutes=0,
            movement_direction="neutral", tipster_against=0,
        )
        defaults.update(kwargs)
        return NarrativeSpec(**defaults)

    def test_zero_support_confident_tone_is_violation(self):
        spec = self._make_spec(support_level=0, tone_band="confident",
                               verdict_action="back", evidence_class="supported")
        violations = _check_coherence(spec)
        assert any("0 indicators" in v for v in violations)

    def test_zero_support_strong_tone_is_violation(self):
        spec = self._make_spec(support_level=0, tone_band="strong",
                               verdict_action="strong back", evidence_class="conviction")
        violations = _check_coherence(spec)
        assert any("0 indicators" in v for v in violations)

    def test_one_support_back_verdict_is_violation(self):
        spec = self._make_spec(support_level=1, evidence_class="lean",
                               tone_band="moderate", verdict_action="back",
                               verdict_sizing="standard stake")
        violations = _check_coherence(spec)
        assert any("≤1 indicator" in v for v in violations)

    def test_high_risk_strong_back_is_violation(self):
        spec = self._make_spec(
            support_level=5, evidence_class="conviction", tone_band="strong",
            verdict_action="strong back", verdict_sizing="confident stake",
            risk_severity="high",
        )
        violations = _check_coherence(spec)
        assert any("high risk" in v for v in violations)

    def test_speculative_evidence_non_speculative_verdict_is_violation(self):
        spec = self._make_spec(
            support_level=0, evidence_class="speculative",
            tone_band="cautious", verdict_action="lean",
        )
        violations = _check_coherence(spec)
        assert any("speculative evidence" in v for v in violations)

    def test_stale_12h_non_cautious_tone_is_violation(self):
        spec = self._make_spec(
            stale_minutes=720, tone_band="moderate",
            evidence_class="lean", support_level=1,
            verdict_action="lean", verdict_sizing="small stake",
        )
        violations = _check_coherence(spec)
        assert any("stale" in v.lower() for v in violations)

    def test_two_tipsters_against_strong_tone_is_violation(self):
        spec = self._make_spec(
            support_level=5, evidence_class="conviction", tone_band="strong",
            verdict_action="strong back", verdict_sizing="confident stake",
            tipster_against=2, risk_severity="moderate",
        )
        violations = _check_coherence(spec)
        assert any("tipster" in v for v in violations)

    def test_coherent_spec_returns_no_violations(self):
        spec = self._make_spec(
            support_level=5, evidence_class="conviction", tone_band="strong",
            verdict_action="strong back", verdict_sizing="confident stake",
            risk_severity="low",
        )
        assert _check_coherence(spec) == []

    def test_cautious_tone_with_speculative_evidence_is_coherent(self):
        spec = self._make_spec(
            support_level=0, evidence_class="speculative",
            tone_band="cautious", verdict_action="speculative punt",
        )
        assert _check_coherence(spec) == []


# ── _enforce_coherence() — downgrade loop ─────────────────────────────────────

class TestEnforceCoherence:
    """Tests for the downgrade-until-coherent loop."""

    def _make_spec(self, **kwargs) -> NarrativeSpec:
        defaults = dict(
            home_name="X", away_name="Y", competition="EPL", sport="soccer",
            home_story_type="neutral", away_story_type="neutral",
            support_level=0, evidence_class="speculative",
            tone_band="cautious", verdict_action="speculative punt",
            verdict_sizing="tiny exposure",
            risk_severity="moderate", stale_minutes=0,
            movement_direction="neutral", tipster_against=0,
        )
        defaults.update(kwargs)
        return NarrativeSpec(**defaults)

    def test_strong_with_zero_support_downgrades_to_moderate(self):
        """strong tone + 0 support → downgrade until no violations.

        Downgrade chain: strong → confident → moderate (STOP).
        At moderate: 'lean' is not in ('back','strong back') so ≤1 check passes.
        At moderate: tone is not 'confident'/'strong' so 0-indicators check passes.
        """
        spec = self._make_spec(
            support_level=0, tone_band="strong", evidence_class="conviction",
            verdict_action="strong back", verdict_sizing="confident stake",
        )
        result = _enforce_coherence(spec)
        assert result.tone_band == "moderate"
        assert result.evidence_class == "lean"
        assert result.verdict_action == "lean"

    def test_stale_12h_plus_zero_support_downgrades_to_cautious(self):
        """12h stale adds an extra violation that pushes downgrade to cautious floor."""
        spec = self._make_spec(
            support_level=0, tone_band="strong", evidence_class="conviction",
            verdict_action="strong back", verdict_sizing="confident stake",
            stale_minutes=720,
        )
        result = _enforce_coherence(spec)
        assert result.tone_band == "cautious"
        assert result.evidence_class == "speculative"
        assert result.verdict_action == "speculative punt"

    def test_confident_with_zero_support_downgrades_to_moderate(self):
        """confident + 0 support + non-stale → stops at moderate (lean verdict ok)."""
        spec = self._make_spec(
            support_level=0, tone_band="confident", evidence_class="supported",
            verdict_action="back", verdict_sizing="standard stake",
        )
        result = _enforce_coherence(spec)
        assert result.tone_band == "moderate"

    def test_already_coherent_spec_unchanged(self):
        spec = self._make_spec(
            support_level=5, tone_band="strong", evidence_class="conviction",
            verdict_action="strong back", verdict_sizing="confident stake",
            risk_severity="low",
        )
        result = _enforce_coherence(spec)
        assert result.tone_band == "strong"
        assert result.verdict_action == "strong back"

    def test_high_risk_strong_back_downgrades(self):
        spec = self._make_spec(
            support_level=5, tone_band="strong", evidence_class="conviction",
            verdict_action="strong back", verdict_sizing="confident stake",
            risk_severity="high",
        )
        result = _enforce_coherence(spec)
        assert result.verdict_action != "strong back"

    def test_floor_is_cautious_no_infinite_loop(self):
        """Spec already at cautious with coherence violation terminates."""
        spec = self._make_spec(
            support_level=0, tone_band="cautious", evidence_class="speculative",
            verdict_action="speculative punt",
            stale_minutes=750,  # 12.5h stale — but tone already cautious, so no violation
        )
        result = _enforce_coherence(spec)
        assert result.tone_band == "cautious"  # stays at floor, no loop

    def test_12h_stale_moderate_tone_downgrades_to_cautious(self):
        spec = self._make_spec(
            stale_minutes=720, tone_band="moderate", support_level=1,
            evidence_class="lean", verdict_action="lean", verdict_sizing="small stake",
        )
        result = _enforce_coherence(spec)
        assert result.tone_band == "cautious"


# ── Risk helpers ───────────────────────────────────────────────────────────────

class TestRiskHelpers:

    def test_stale_6h_triggers_stale_factor(self):
        factors = _build_risk_factors({"stale_minutes": 360}, None, "soccer")
        assert any("Stale" in f for f in factors)

    def test_zero_signals_triggers_model_only_factor(self):
        """W84-Q3: Zero confirming signals produces a model-only risk factor."""
        factors = _build_risk_factors({"confirming_signals": 0}, None, "soccer")
        assert any("model" in f.lower() or "confirm" in f.lower() or "signal" in f.lower() for f in factors)

    def test_movement_against_triggers_drift_factor(self):
        factors = _build_risk_factors({"movement_direction": "against"}, None, "soccer")
        assert any("drifting" in f for f in factors)

    def test_two_tipsters_against_triggers_factor(self):
        factors = _build_risk_factors({"tipster_against": 2}, None, "soccer")
        assert any("tipster" in f for f in factors)

    def test_no_risk_signals_returns_standard_variance(self):
        """No active risk signals → standard variance fallback."""
        edge_data = {
            "stale_minutes": 30,
            "confirming_signals": 2,
            "movement_direction": "neutral",
            "tipster_against": 0,
        }
        factors = _build_risk_factors(edge_data, None, "soccer")
        # W84-Q9: replaced "Standard match variance applies." with 3 human variants
        assert len(factors) >= 1 and any(len(f) > 10 for f in factors)

    def test_12h_stale_returns_high_severity(self):
        severity = _assess_risk_severity([], {"stale_minutes": 720})
        assert severity == "high"

    def test_movement_against_plus_2_tipsters_returns_high_severity(self):
        severity = _assess_risk_severity([], {
            "movement_direction": "against", "tipster_against": 2
        })
        assert severity == "high"

    def test_4_signals_fresh_no_opposition_returns_low_severity(self):
        severity = _assess_risk_severity([], {
            "confirming_signals": 4,
            "movement_direction": "for",
            "stale_minutes": 30,
            "tipster_against": 0,
        })
        assert severity == "low"

    def test_default_is_moderate(self):
        severity = _assess_risk_severity([], {"confirming_signals": 2})
        assert severity == "moderate"


# ── Label helpers ──────────────────────────────────────────────────────────────

class TestLabelHelpers:

    def test_humanise_league_known_key(self):
        assert _humanise_league("epl") == "Premier League"
        assert _humanise_league("psl") == "Premiership (PSL)"
        assert _humanise_league("urc") == "United Rugby Championship"
        assert _humanise_league("ufc") == "UFC"

    def test_humanise_league_unknown_key_title_cases(self):
        assert _humanise_league("some_new_league") == "Some New League"

    def test_build_outcome_label_home(self):
        label = _build_outcome_label(
            {"outcome": "home"}, "Arsenal", "Chelsea"
        )
        assert label == "Arsenal win"

    def test_build_outcome_label_away(self):
        label = _build_outcome_label(
            {"outcome": "away"}, "Arsenal", "Chelsea"
        )
        assert label == "Chelsea win"

    def test_build_outcome_label_draw(self):
        label = _build_outcome_label({"outcome": "draw"}, "A", "B")
        assert label == "the draw"

    def test_build_h2h_summary_with_data(self):
        ctx = {
            "head_to_head": [
                {"home_score": 2, "away_score": 1},
                {"home_score": 0, "away_score": 0},
                {"home_score": 1, "away_score": 3},
            ]
        }
        summary = _build_h2h_summary(ctx)
        assert "3 meetings" in summary
        assert "1W" in summary
        assert "1D" in summary
        assert "1L" in summary

    def test_build_h2h_summary_prefers_edge_data_counts(self):
        summary = _build_h2h_summary(
            {"head_to_head": [{"home_score": 0, "away_score": 0}]},
            {
                "h2h_total": 5,
                "h2h_a_wins": 3,
                "h2h_b_wins": 2,
                "h2h_draws": 0,
            },
            home_name="West Ham",
        )
        assert summary == "5 meetings: West Ham 3W 0D 2L"

    def test_build_h2h_summary_parses_espn_score_strings(self):
        summary = _build_h2h_summary(
            {
                "head_to_head": [
                    {"home": "Arsenal", "away": "Bournemouth", "score": "2-1"},
                    {"home": "Bournemouth", "away": "Arsenal", "score": "1-1"},
                    {"home": "Bournemouth", "away": "Arsenal", "score": "0-2"},
                ]
            },
            {},
            home_name="Arsenal",
        )
        assert summary == "3 meetings: Arsenal 2W 1D 0L"

    def test_build_h2h_summary_empty(self):
        assert _build_h2h_summary({}) == ""
        assert _build_h2h_summary(None) == ""


# ── Representative NarrativeSpec samples ──────────────────────────────────────
# Three realistic samples demonstrating evidence_class + tone_band combos.
# These are generated from representative edge data without hitting the DB.

class TestRepresentativeSpecs:
    """
    W82-SPEC compliance: paste 3 NarrativeSpecs showing evidence_class + tone_band.
    """

    def _classify(self, **kwargs):
        return _classify_evidence(kwargs)

    def test_edge_1_sundowns_vs_sekhukhune_zero_signals(self):
        """
        Edge: Sekhukhune Away Win | Stale 8h | 0 signals | EV +3.1%
        Expected: speculative / cautious
        """
        edge_data = {
            "home_team": "Mamelodi Sundowns",
            "away_team": "Sekhukhune United",
            "league": "psl",
            "best_bookmaker": "Hollywoodbets",
            "best_odds": 5.80,
            "edge_pct": 3.1,
            "outcome": "away",
            "confirming_signals": 0,
            "composite_score": 38.0,
            "stale_minutes": 480,
            "movement_direction": "neutral",
            "tipster_against": 0,
        }
        ev_class, tone, action, sizing = _classify_evidence(edge_data)

        # Build representative spec manually (no bot.py needed)
        spec = NarrativeSpec(
            home_name="Mamelodi Sundowns",
            away_name="Sekhukhune United",
            competition=_humanise_league("psl"),
            sport="soccer",
            home_story_type="title_push",
            away_story_type="crisis",
            support_level=0,
            evidence_class=ev_class,
            tone_band=tone,
            risk_factors=_build_risk_factors(edge_data, None, "soccer"),
            risk_severity=_assess_risk_severity([], edge_data),
            verdict_action=action,
            verdict_sizing=sizing,
            stale_minutes=480,
            movement_direction="neutral",
        )
        spec = _enforce_coherence(spec)

        assert spec.evidence_class == "speculative"
        assert spec.tone_band == "cautious"
        assert spec.verdict_action == "speculative punt"
        assert spec.competition == "Premiership (PSL)"

    def test_edge_2_arsenal_vs_man_city_three_signals(self):
        """
        Edge: Arsenal Home Win | Fresh odds | 3 signals | composite 68 | EV +5.2%
        Expected: supported / confident
        """
        edge_data = {
            "home_team": "Arsenal",
            "away_team": "Manchester City",
            "league": "epl",
            "best_bookmaker": "Betway",
            "best_odds": 2.10,
            "edge_pct": 5.2,
            "outcome": "home",
            "confirming_signals": 3,
            "composite_score": 68.0,
            "stale_minutes": 45,
            "movement_direction": "for",
            "tipster_against": 0,
        }
        ev_class, tone, action, sizing = _classify_evidence(edge_data)

        spec = NarrativeSpec(
            home_name="Arsenal",
            away_name="Manchester City",
            competition=_humanise_league("epl"),
            sport="soccer",
            home_story_type="momentum",
            away_story_type="inconsistent",
            support_level=3,
            evidence_class=ev_class,
            tone_band=tone,
            risk_factors=_build_risk_factors(edge_data, None, "soccer"),
            risk_severity=_assess_risk_severity([], edge_data),
            verdict_action=action,
            verdict_sizing=sizing,
            stale_minutes=45,
            movement_direction="for",
        )
        spec = _enforce_coherence(spec)

        assert spec.evidence_class == "supported"
        assert spec.tone_band == "confident"
        assert spec.verdict_action == "back"
        assert spec.verdict_sizing == "standard stake"

    def test_edge_3_six_nations_draw_supported(self):
        """
        Edge: England vs Ireland Draw | 5 signals | composite 72 | EV +6.8%
        Expected: supported / confident under the 7% sizing floor
        """
        edge_data = {
            "home_team": "England",
            "away_team": "Ireland",
            "league": "six_nations",
            "best_bookmaker": "SuperSportBet",
            "best_odds": 4.20,
            "edge_pct": 6.8,
            "outcome": "draw",
            "confirming_signals": 5,
            "composite_score": 72.0,
            "stale_minutes": 20,
            "movement_direction": "neutral",
            "tipster_against": 0,
        }
        ev_class, tone, action, sizing = _classify_evidence(edge_data)

        spec = NarrativeSpec(
            home_name="England",
            away_name="Ireland",
            competition=_humanise_league("six_nations"),
            sport="rugby",
            home_story_type="setback",
            away_story_type="momentum",
            support_level=5,
            evidence_class=ev_class,
            tone_band=tone,
            risk_factors=_build_risk_factors(edge_data, None, "rugby"),
            risk_severity=_assess_risk_severity([], edge_data),
            verdict_action=action,
            verdict_sizing=sizing,
            stale_minutes=20,
            movement_direction="neutral",
        )
        spec = _enforce_coherence(spec)

        assert spec.evidence_class == "supported"
        assert spec.tone_band == "confident"
        assert spec.verdict_action == "back"
        assert spec.verdict_sizing == "standard stake"
        assert spec.competition == "Six Nations"


# ── W82-RENDER: Helper function tests ─────────────────────────────────────────

class TestRenderHelpers:
    """Unit tests for deterministic rendering helper functions."""

    def test_ordinal_r_standard_cases(self):
        assert _ordinal_r(1) == "1st"
        assert _ordinal_r(2) == "2nd"
        assert _ordinal_r(3) == "3rd"
        assert _ordinal_r(4) == "4th"
        assert _ordinal_r(11) == "11th"
        assert _ordinal_r(12) == "12th"
        assert _ordinal_r(13) == "13th"
        assert _ordinal_r(21) == "21st"

    def test_pick_is_deterministic(self):
        """Same seed always returns the same index."""
        idx1 = _pick("Arsenal", 3)
        idx2 = _pick("Arsenal", 3)
        assert idx1 == idx2
        assert 0 <= idx1 < 3

    def test_pick_different_seeds_vary(self):
        """Different seeds should not all map to the same index (statistical check)."""
        teams = ["Arsenal", "Chelsea", "Liverpool", "Manchester City", "Tottenham",
                 "Manchester United", "Newcastle", "Aston Villa"]
        indices = [_pick(t, 3) for t in teams]
        # With 8 teams and 3 variants, not all should be the same
        assert len(set(indices)) > 1

    def test_coach_possessive_with_name(self):
        assert _coach_possessive("Mikel Arteta") == "Arteta's"
        assert _coach_possessive("Pep Guardiola") == "Guardiola's"

    def test_coach_possessive_s_ending(self):
        """Names ending in 's' get apostrophe only."""
        assert _coach_possessive("Jose Mourinhous") == "Mourinhous'"

    def test_coach_possessive_no_coach(self):
        assert _coach_possessive(None) == "the manager's"
        assert _coach_possessive("") == "the manager's"

    def test_parse_wdl_valid(self):
        assert _parse_wdl("W9 D3 L2") == (9, 3, 2)
        assert _parse_wdl("W0 D5 L10") == (0, 5, 10)

    def test_parse_wdl_invalid(self):
        assert _parse_wdl("") == (0, 0, 0)
        assert _parse_wdl("no data") == (0, 0, 0)

    def test_sentence_case_preserves_proper_nouns(self):
        """Capitalises first char only — does not lowercase proper nouns."""
        assert _sentence_case("arsenal win") == "Arsenal win"
        assert _sentence_case("Arsenal win") == "Arsenal win"
        assert _sentence_case("the draw") == "The draw"

    def test_sentence_case_empty(self):
        assert _sentence_case("") == ""


# ── W82-RENDER: _render_team_para tests ───────────────────────────────────────

class TestRenderTeamPara:
    """_render_team_para() produces non-empty prose for all story types."""

    def _para(self, story_type, name="Arsenal", **kwargs):
        defaults = dict(
            coach="Mikel Arteta", position=3, points=52, form="WWDLW",
            record="W9 D3 L2", gpg=2.1, last_result="beating Chelsea 2-1 away",
            injuries=[], competition="Premier League", sport="soccer", is_home=True,
        )
        defaults.update(kwargs)
        return _render_team_para(
            name, defaults["coach"], story_type,
            defaults["position"], defaults["points"], defaults["form"],
            defaults["record"], defaults["gpg"], defaults["last_result"],
            defaults["injuries"], defaults["competition"], defaults["sport"],
            defaults["is_home"],
        )

    def test_title_push_contains_team_name(self):
        para = self._para("title_push")
        assert "Arsenal" in para

    def test_crisis_contains_position(self):
        para = self._para("crisis", name="Luton", position=19, points=20, form="LLLWL")
        assert "Luton" in para
        assert len(para) > 30

    def test_fortress_mentions_home(self):
        para = self._para("fortress", name="Burnley")
        assert "Burnley" in para

    def test_neutral_handles_no_data(self):
        para = _render_team_para(
            "Unknown FC", None, "neutral",
            None, None, "", "", None, "", [], "Some League", "soccer", True,
        )
        assert "Unknown FC" in para
        assert len(para) > 10

    def test_unknown_story_type_falls_back_to_neutral(self):
        para = self._para("bogus_type_xyz", name="Tottenham")
        assert "Tottenham" in para
        assert len(para) > 10

    def test_injuries_injected_when_present(self):
        para = self._para("momentum", injuries=["Saliba (hamstring)"], name="Arsenal")
        assert "Saliba" in para

    def test_all_10_story_types_return_nonempty(self):
        story_types = [
            "title_push", "fortress", "crisis", "recovery", "momentum",
            "inconsistent", "draw_merchants", "setback", "anonymous", "neutral",
        ]
        for st in story_types:
            para = self._para(st)
            assert len(para) > 20, f"Empty or very short para for story_type={st!r}"


# ── W82-RENDER: _render_edge tests ────────────────────────────────────────────

class TestRenderEdge:
    """_render_edge() output matches evidence_class language constraints."""

    def _spec(self, evidence_class, tone_band, verdict_action, verdict_sizing, **kwargs):
        defaults = dict(
            home_name="Arsenal", away_name="Chelsea",
            competition="Premier League", sport="soccer",
            home_story_type="neutral", away_story_type="neutral",
            bookmaker="Betway", odds=2.10, ev_pct=5.2,
            fair_prob_pct=52.0, composite_score=65.0,
            outcome="home", outcome_label="Arsenal win",
            support_level=3, risk_factors=["Standard match variance applies."],
            risk_severity="moderate", stale_minutes=30,
            movement_direction="neutral", tipster_against=0,
        )
        defaults.update(kwargs)
        return NarrativeSpec(
            evidence_class=evidence_class,
            tone_band=tone_band,
            verdict_action=verdict_action,
            verdict_sizing=verdict_sizing,
            **defaults,
        )

    def test_speculative_mentions_ev_or_probability(self):
        """W84-Q3: Speculative edge must reference EV or fair probability."""
        spec = self._spec("speculative", "cautious", "speculative punt", "tiny exposure",
                          support_level=0)
        edge = _render_edge(spec)
        assert "expected value" in edge.lower() or "fair" in edge.lower() or "edge" in edge.lower()

    def test_speculative_no_legacy_phrases(self):
        """W84-Q3: Speculative edge must not contain legacy banned phrases."""
        spec = self._spec("speculative", "cautious", "speculative punt", "tiny exposure",
                          support_level=0)
        edge = _render_edge(spec)
        legacy = ["tread carefully", "signals are absent", "supporting evidence is thin",
                  "numbers-only play", "price is interesting", "pure pricing call"]
        for phrase in legacy:
            assert phrase not in edge.lower(), f"Legacy phrase '{phrase}' in speculative edge"

    def test_lean_mentions_value_or_signal(self):
        """W84-Q3 + FIX-NARRATIVE-VOICE-COMPREHENSIVE-01: Lean edge references
        value, confirming evidence, or a fair-line frame.

        The braai-voice rewrite (2026-04-29 AC-3) replaced "signal" / "indicator"
        with "evidence" + "fair line" — Rule 17 telemetry vocabulary purge.
        """
        spec = self._spec("lean", "moderate", "lean", "small stake", support_level=1)
        edge = _render_edge(spec)
        assert (
            "value" in edge.lower()
            or "confirm" in edge.lower()
            or "evidence" in edge.lower()
            or "fair" in edge.lower()
            or "back" in edge.lower()
        )

    def test_supported_mentions_indicators(self):
        """W84-Q3 + FIX-NARRATIVE-VOICE-COMPREHENSIVE-01: Supported edge
        references confirming evidence or support.

        Renamed semantic check: "indicator" / "signal" purged per Rule 17.
        New vocabulary uses "evidence", "support", "back", "fair" tokens.
        """
        spec = self._spec("supported", "confident", "back", "standard stake", support_level=3)
        edge = _render_edge(spec)
        assert (
            "evidence" in edge.lower()
            or "support" in edge.lower()
            or "confirm" in edge.lower()
            or "back" in edge.lower()
        )

    def test_conviction_strong_language(self):
        """W84-Q3: Conviction edge uses strong language."""
        spec = self._spec("conviction", "strong", "strong back", "confident stake", support_level=5)
        edge = _render_edge(spec)
        assert "strong" in edge.lower() or "mispriced" in edge.lower() or "everything lines up" in edge.lower()

    def test_edge_includes_odds_and_bookmaker(self):
        spec = self._spec("supported", "confident", "back", "standard stake",
                          bookmaker="SuperSportBet", odds=1.95)
        edge = _render_edge(spec)
        assert "1.95" in edge
        assert "SuperSportBet" in edge


# ── W82-RENDER: _render_risk tests ────────────────────────────────────────────

class TestRenderRisk:
    """_render_risk() stays uncertainty-only and leaves staking to Verdict."""

    def _spec(self, risk_severity, risk_factors, verdict_sizing="standard stake"):
        return NarrativeSpec(
            home_name="Arsenal", away_name="Chelsea",
            competition="Premier League", sport="soccer",
            home_story_type="neutral", away_story_type="neutral",
            evidence_class="supported", tone_band="confident",
            verdict_action="back", verdict_sizing=verdict_sizing,
            risk_severity=risk_severity, risk_factors=risk_factors,
            support_level=3, stale_minutes=30,
            movement_direction="neutral", tipster_against=0,
        )

    def test_high_risk_includes_high_risk_text(self):
        spec = self._spec("high", ["Stale price — hasn't updated in 7h, could shift before kickoff."])
        risk = _render_risk(spec)
        assert "High-risk" in risk or "high" in risk.lower()

    def test_low_risk_includes_manageable_text(self):
        """W84-Q3: Low risk uses manageable/clean language."""
        spec = self._spec("low", ["Standard match variance applies."])
        risk = _render_risk(spec)
        assert "manageable" in risk.lower() or "clean" in risk.lower()

    def test_risk_does_not_include_stake_guidance(self):
        """Risk section must not duplicate Verdict stake language."""
        spec = self._spec("moderate", ["Market drifting away from this outcome."],
                          verdict_sizing="small stake")
        risk = _render_risk(spec)
        assert "stake" not in risk.lower()
        assert "size" not in risk.lower()

    def test_risk_factors_appear_in_output(self):
        spec = self._spec("moderate",
                          ["No form, movement, or tipster data backs this up — the case is model-only."])
        risk = _render_risk(spec)
        assert "model-only" in risk


# ── W82-RENDER: _render_verdict tests ─────────────────────────────────────────

class TestRenderVerdict:
    """_render_verdict() uses tone_band-compliant language for all 4 actions."""

    def _spec(self, verdict_action, verdict_sizing, tone_band, outcome_label="Arsenal win"):
        return NarrativeSpec(
            home_name="Arsenal", away_name="Chelsea",
            competition="Premier League", sport="soccer",
            home_story_type="neutral", away_story_type="neutral",
            evidence_class="supported", tone_band=tone_band,
            verdict_action=verdict_action, verdict_sizing=verdict_sizing,
            outcome="home", outcome_label=outcome_label,
            bookmaker="Betway", odds=2.10,
            support_level=3, risk_factors=["Standard match variance applies."],
            risk_severity="moderate", stale_minutes=30,
            movement_direction="neutral", tipster_against=0,
        )

    def test_speculative_sizing_guidance(self):
        """W84-Q3: Speculative verdict includes sizing guidance."""
        spec = self._spec("speculative punt", "tiny exposure", "cautious")
        verdict = _render_verdict(spec)
        assert "punt" in verdict.lower() or "small" in verdict.lower() or "tiny" in verdict.lower()

    def test_lean_references_outcome(self):
        """W84-Q3: Lean verdict references the outcome."""
        spec = self._spec("lean", "small stake", "moderate",
                          outcome_label="the draw")
        verdict = _render_verdict(spec)
        assert "lean" in verdict.lower() or "the draw" in verdict.lower()

    def test_back_uses_back(self):
        """W84-Q3 + FIX-NARRATIVE-W82-VARIANT-EXPANSION-01: Back verdict closes
        with one of the brief AC-3 imperative action verbs.
        """
        spec = self._spec("back", "standard stake", "confident")
        verdict = _render_verdict(spec).lower()
        # Brief AC-3 imperative cluster (any of these counts as a Gold close).
        assert any(verb in verdict for verb in (
            "back", "bet on", "put your money on", "get on", "take",
            "lean on", "ride", "hammer it on", "smash", "green light",
        )), f"Back verdict missing imperative action verb: {verdict!r}"

    def test_strong_back_confident_language(self):
        """W84-Q3 + FIX-NARRATIVE-W82-VARIANT-EXPANSION-01: Strong back verdict
        carries Diamond-tier conviction vocabulary.

        Conviction is now expressed via the imperative action verb itself
        ("Hammer it on" — Diamond) plus the standard-to-heavy stake sizing
        tail. The previous "premium back" / "with conviction" wording lived
        in the legacy 4-variant pool that the W82 7-pattern pool replaced.
        """
        spec = self._spec("strong back", "confident stake", "strong")
        verdict = _render_verdict(spec).lower()
        assert (
            "hammer it on" in verdict
            or "strong" in verdict
            or "premium" in verdict
            or "conviction" in verdict
            or "confidence" in verdict
            or "standard-to-heavy" in verdict
        ), f"Strong back verdict missing Diamond-tier conviction language: {verdict!r}"

    def test_speculative_verdict_contains_no_banned_confident_phrases(self):
        spec = self._spec("speculative punt", "tiny exposure", "cautious")
        verdict = _render_verdict(spec)
        for phrase in TONE_BANDS["cautious"]["banned"]:
            assert phrase.lower() not in verdict.lower(), (
                f"Banned phrase {phrase!r} found in speculative verdict"
            )

    def test_strong_back_contains_no_banned_strong_phrases(self):
        spec = self._spec("strong back", "confident stake", "strong")
        verdict = _render_verdict(spec)
        for phrase in TONE_BANDS["strong"]["banned"]:
            assert phrase.lower() not in verdict.lower(), (
                f"Banned phrase {phrase!r} found in strong back verdict"
            )

    def test_lean_verdict_avoids_verifier_boundary_phrases(self):
        spec = self._spec("lean", "small stake", "moderate", outcome_label="the draw")
        verdict = _render_verdict(spec).lower()
        for phrase in ("worth backing", "solid play", "strong back", "premium value"):
            assert phrase not in verdict, (
                f"Verifier boundary phrase {phrase!r} found in lean verdict"
            )

    def test_rendered_verdict_never_emits_confident(self):
        for action, sizing, tone in (
            ("speculative punt", "tiny exposure", "cautious"),
            ("lean", "small stake", "moderate"),
            ("back", "standard stake", "confident"),
            ("strong back", "confident stake", "strong"),
        ):
            spec = self._spec(action, sizing, tone)
            verdict = _render_verdict(spec).lower()
            assert "confident" not in verdict, (
                f"Rendered verdict for {action!r} leaked banned 'confident' wording"
            )

    def test_speculative_punt_with_one_signal_no_false_zero_claim(self):
        """SIGNAL-FIX-01: When support_level >= 1 and verdict_action == speculative punt,
        the verdict must NOT claim there are zero confirming signals.

        This case occurs when confirming_signals=1 in DB but a stale or movement
        penalty reduces effective support to 0, producing a speculative punt action.
        The card shows 1+ confirming signal; the verdict must not contradict it.
        """
        _FALSE_ZERO_PHRASES = (
            "no confirming signal backs it",
            "until a confirming signal emerges",
            "the signals aren't there yet",
        )
        # support_level=1 mimics confirming_signals=1 in DB (penalty reduces effective to 0)
        spec = NarrativeSpec(
            home_name="Punjab Kings",
            away_name="SRH",
            competition="IPL",
            sport="cricket",
            home_story_type="neutral",
            away_story_type="neutral",
            evidence_class="speculative",
            tone_band="cautious",
            verdict_action="speculative punt",
            verdict_sizing="tiny exposure",
            outcome="home",
            outcome_label="Punjab Kings win",
            bookmaker="Betway",
            odds=2.30,
            ev_pct=2.1,
            support_level=1,  # 1 confirming signal in DB, but effective=0 after stale penalty
            risk_factors=["Stale price — hasn't updated in 6h, could shift before kickoff."],
            risk_severity="moderate",
            stale_minutes=420,
            movement_direction="neutral",
        )
        verdict = _render_verdict(spec)
        for phrase in _FALSE_ZERO_PHRASES:
            assert phrase.lower() not in verdict.lower(), (
                f"SIGNAL-FIX-01: False zero-signal claim {phrase!r} in verdict "
                f"for support_level=1 speculative punt. Verdict: {verdict!r}"
            )

    def test_all_verdict_actions_in_length_window(self):
        """Every verdict action × sizing renders within the locked char range.

        BUILD-VERDICT-FLOOR-01 originally enforced [140, 200].
        FIX-NARRATIVE-VOICE-COMPREHENSIVE-01 (2026-04-28) widened the ceiling to
        VERDICT_HARD_MAX (260).
        FIX-NARRATIVE-W82-VARIANT-EXPANSION-01 (2026-05-01) lowered the floor
        to 100 per AC-3 #6 ("Pass char range 100-260, target 140-200"). The
        new W82 imperative-closing pool produces verdicts as short as ~100
        chars when team / bookmaker names are short — the unified contract
        is now [100, 260], with [140, 200] as the soft target.
        """
        from narrative_spec import VERDICT_HARD_MAX
        cases = [
            ("pass", "monitor", "cautious"),
            ("monitor", "monitor", "cautious"),
            ("speculative punt", "tiny exposure", "cautious"),
            ("lean", "small stake", "moderate"),
            ("back", "standard stake", "confident"),
            ("strong back", "confident stake", "strong"),
        ]
        for action, sizing, tone in cases:
            spec = NarrativeSpec(
                home_name="Mamelodi Sundowns", away_name="Orlando Pirates",
                competition="Premier League", sport="soccer",
                home_story_type="neutral", away_story_type="neutral",
                evidence_class="supported", tone_band=tone,
                verdict_action=action, verdict_sizing=sizing,
                outcome="home", outcome_label="Mamelodi Sundowns win",
                bookmaker="Hollywoodbets", odds=2.10,
                support_level=2, ev_pct=8.5,
                risk_factors=["Standard match variance applies."],
                risk_severity="moderate", stale_minutes=30,
                movement_direction="neutral",
            )
            verdict = _render_verdict(spec)
            assert len(verdict) >= 100, (
                f"Verdict for action={action!r} below floor ({len(verdict)} < 100): {verdict!r}"
            )
            assert len(verdict) <= VERDICT_HARD_MAX, (
                f"Verdict for action={action!r} exceeds hard max ({len(verdict)} > "
                f"{VERDICT_HARD_MAX}): {verdict!r}"
            )


# ── W82-RENDER: _render_baseline structure tests ──────────────────────────────

class TestRenderBaseline:
    """_render_baseline() assembles all 4 sections with correct structure."""

    def _full_spec(self, evidence_class="supported", tone_band="confident",
                   verdict_action="back", verdict_sizing="standard stake"):
        return NarrativeSpec(
            home_name="Mamelodi Sundowns",
            away_name="Kaizer Chiefs",
            competition="Premiership (PSL)",
            sport="soccer",
            home_story_type="title_push",
            away_story_type="inconsistent",
            home_coach="Rulani Mokwena",
            away_coach=None,
            home_position=1,
            away_position=7,
            home_points=58,
            away_points=34,
            home_form="WWWDW",
            away_form="WDLWL",
            home_record="W12 D3 L1",
            away_record="W6 D4 L6",
            home_gpg=2.3,
            away_gpg=1.2,
            home_last_result="beating Orlando Pirates 2-0 at home",
            away_last_result="drawing with SuperSport United 1-1",
            h2h_summary="8 meetings: 4W 2D 2L",
            injuries_home=[],
            injuries_away=["Khama Billiat (knee)"],
            outcome="home",
            outcome_label="Sundowns win",
            bookmaker="Hollywoodbets",
            odds=1.65,
            ev_pct=4.8,
            fair_prob_pct=62.0,
            composite_score=68.0,
            support_level=3,
            evidence_class=evidence_class,
            tone_band=tone_band,
            risk_factors=["Standard match variance applies."],
            risk_severity="low",
            verdict_action=verdict_action,
            verdict_sizing=verdict_sizing,
            stale_minutes=30,
            movement_direction="neutral",
            tipster_against=0,
        )

    def test_baseline_has_four_section_headers(self):
        spec = self._full_spec()
        baseline = _render_baseline(spec)
        assert "📋" in baseline
        assert "🎯" in baseline
        assert "⚠️" in baseline
        assert "🏆" in baseline
        assert "<b>The Setup</b>" in baseline
        assert "<b>The Edge</b>" in baseline
        assert "<b>The Risk</b>" in baseline
        assert "<b>Verdict</b>" in baseline

    def test_baseline_sections_in_correct_order(self):
        spec = self._full_spec()
        baseline = _render_baseline(spec)
        setup_pos = baseline.index("📋")
        edge_pos = baseline.index("🎯")
        risk_pos = baseline.index("⚠️")
        verdict_pos = baseline.index("🏆")
        assert setup_pos < edge_pos < risk_pos < verdict_pos

    def test_baseline_contains_team_names(self):
        spec = self._full_spec()
        baseline = _render_baseline(spec)
        assert "Sundowns" in baseline
        assert "Chiefs" in baseline

    def test_baseline_contains_h2h(self):
        spec = self._full_spec()
        baseline = _render_baseline(spec)
        assert "8 meetings" in baseline

    def test_baseline_speculative_no_back_language(self):
        """Speculative baseline must not use tone-banned phrases."""
        spec = self._full_spec(
            evidence_class="speculative", tone_band="cautious",
            verdict_action="speculative punt", verdict_sizing="tiny exposure",
        )
        baseline = _render_baseline(spec)
        for phrase in TONE_BANDS["cautious"]["banned"]:
            assert phrase.lower() not in baseline.lower(), (
                f"Banned phrase {phrase!r} in speculative baseline"
            )

    def test_baseline_conviction_no_guaranteed_language(self):
        """Conviction baseline must not use tone-banned phrases."""
        spec = self._full_spec(
            evidence_class="conviction", tone_band="strong",
            verdict_action="strong back", verdict_sizing="confident stake",
        )
        baseline = _render_baseline(spec)
        for phrase in TONE_BANDS["strong"]["banned"]:
            assert phrase.lower() not in baseline.lower(), (
                f"Banned phrase {phrase!r} in conviction baseline"
            )

    def test_baseline_injury_appears_in_setup(self):
        spec = self._full_spec()
        baseline = _render_baseline(spec)
        assert "Billiat" in baseline


# ── VERDICT-COHERENCE-FIX: Evidence clause tests ─────────────────────────────

class TestBuildEvidenceClauses:
    """_build_evidence_clauses() returns match-specific evidence for verdict."""

    def _spec(self, **overrides):
        defaults = dict(
            home_name="Arsenal", away_name="Chelsea",
            competition="Premier League", sport="soccer",
            home_story_type="neutral", away_story_type="neutral",
            evidence_class="supported", tone_band="confident",
            verdict_action="back", verdict_sizing="standard stake",
            outcome="home", outcome_label="Arsenal win",
            bookmaker="Betway", odds=2.10, ev_pct=8.3,
            fair_prob_pct=51.5, composite_score=72.0,
            bookmaker_count=5, support_level=3,
            risk_factors=["Stale price — hasn't updated in 8h, could shift before kickoff."],
            risk_severity="moderate", stale_minutes=30,
            movement_direction="for", tipster_against=0,
            tipster_agrees=True, tipster_available=True,
        )
        defaults.update(overrides)
        return NarrativeSpec(**defaults)

    def test_ev_clause_present_when_positive(self):
        """EV clause appears when ev_pct > 0."""
        spec = self._spec(ev_pct=8.3, bookmaker_count=5)
        clauses = _build_evidence_clauses(spec)
        assert "+8.3% EV across 5 bookmakers" in clauses

    def test_ev_clause_single_bookmaker(self):
        """Single bookmaker uses 'at current pricing' instead of count."""
        spec = self._spec(ev_pct=4.5, bookmaker_count=1)
        clauses = _build_evidence_clauses(spec)
        assert "+4.5% EV at current pricing" in clauses
        assert "bookmakers" not in clauses

    def test_ev_clause_absent_when_zero(self):
        """No EV clause when ev_pct is 0."""
        spec = self._spec(ev_pct=0.0)
        clauses = _build_evidence_clauses(spec)
        assert "EV" not in clauses

    def test_signal_clause_with_movement(self):
        """Movement 'for' appears in key signals."""
        spec = self._spec(movement_direction="for", tipster_available=False)
        clauses = _build_evidence_clauses(spec)
        assert "market movement confirms" in clauses

    def test_signal_clause_with_tipster(self):
        """Tipster agreement appears in key signals."""
        spec = self._spec(movement_direction="neutral",
                          tipster_available=True, tipster_agrees=True)
        clauses = _build_evidence_clauses(spec)
        assert "tipster consensus agrees" in clauses

    def test_signal_clause_both_signals(self):
        """Both movement and tipster appear together."""
        spec = self._spec(movement_direction="for",
                          tipster_available=True, tipster_agrees=True)
        clauses = _build_evidence_clauses(spec)
        assert "market movement confirms" in clauses
        assert "tipster consensus agrees" in clauses

    def test_no_signals_clause(self):
        """Zero support level + no movement/tipster → higher variance."""
        spec = self._spec(support_level=0, movement_direction="neutral",
                          tipster_available=False)
        clauses = _build_evidence_clauses(spec)
        assert "No confirming signals" in clauses

    def test_risk_clause_with_specific_risk(self):
        """Specific risk factor appears as 'Main risk:'."""
        spec = self._spec(risk_factors=["Market drifting away from this outcome — sharp money may disagree."])
        clauses = _build_evidence_clauses(spec)
        assert "Main risk:" in clauses
        assert "sharp money" in clauses

    def test_risk_clause_skipped_for_clean_risk(self):
        """Default clean-risk phrases are not included."""
        spec = self._spec(risk_factors=["Nothing obvious stands against this. The usual match-day variables apply."])
        clauses = _build_evidence_clauses(spec)
        assert "Main risk:" not in clauses

    def test_risk_clause_skipped_when_empty(self):
        """No risk clause when risk_factors is empty."""
        spec = self._spec(risk_factors=[])
        clauses = _build_evidence_clauses(spec)
        assert "Main risk:" not in clauses


class TestVerdictCoherenceIntegration:
    """_render_verdict() includes evidence clauses in output."""

    def _spec(self, **overrides):
        defaults = dict(
            home_name="Sundowns", away_name="Chiefs",
            competition="Premiership (PSL)", sport="soccer",
            home_story_type="title_push", away_story_type="inconsistent",
            evidence_class="supported", tone_band="confident",
            verdict_action="back", verdict_sizing="standard stake",
            outcome="home", outcome_label="Sundowns win",
            bookmaker="Hollywoodbets", odds=1.65, ev_pct=12.4,
            fair_prob_pct=68.0, composite_score=74.0,
            bookmaker_count=4, support_level=3,
            risk_factors=["Market drifting away from this outcome — sharp money may disagree."],
            risk_severity="moderate", stale_minutes=30,
            movement_direction="for", tipster_against=0,
            tipster_agrees=True, tipster_available=True,
        )
        defaults.update(overrides)
        return NarrativeSpec(**defaults)

    def test_back_verdict_in_length_window(self):
        """BUILD-VERDICT-FLOOR-01 + FIX-NARRATIVE-W82-VARIANT-EXPANSION-01:
        Back verdict renders within the unified [100, 260] window. Target
        soft band is [140, 200] but the new W82 pool can produce shorter
        clean verdicts when team names are short.
        """
        spec = self._spec()
        verdict = _render_verdict(spec)
        assert 100 <= len(verdict) <= 260, (
            f"Back verdict outside [100, 260] ({len(verdict)}): {verdict!r}"
        )

    def test_speculative_verdict_in_length_window(self):
        """BUILD-VERDICT-FLOOR-01: Speculative verdict renders in [140, 200] chars."""
        spec = self._spec(
            verdict_action="speculative punt", verdict_sizing="tiny exposure",
            evidence_class="speculative", tone_band="cautious",
            ev_pct=3.2, bookmaker_count=3,
        )
        verdict = _render_verdict(spec)
        assert 140 <= len(verdict) <= 200, (
            f"Speculative verdict outside [140, 200] ({len(verdict)}): {verdict!r}"
        )

    def test_monitor_verdict_no_risk_clause(self):
        """Monitor/pass verdicts don't get risk clauses — only timing content."""
        spec = self._spec(verdict_action="monitor", verdict_sizing="monitor", ev_pct=0.0)
        verdict = _render_verdict(spec)
        assert "Main risk:" not in verdict
        assert "monitor" in verdict.lower()

    def test_strong_back_verdict_in_length_window(self):
        """BUILD-VERDICT-FLOOR-01: Strong back verdict renders in [140, 200] chars."""
        spec = self._spec(
            verdict_action="strong back", verdict_sizing="confident stake",
            evidence_class="conviction", tone_band="strong",
            ev_pct=16.5, bookmaker_count=5,
        )
        verdict = _render_verdict(spec)
        assert 140 <= len(verdict) <= 200, (
            f"Strong back verdict outside [140, 200] ({len(verdict)}): {verdict!r}"
        )

    def test_verdict_excludes_risk_clause(self):
        """BUILD-VERDICT-FLOOR-01: Floor never injects 'Main risk:' — risk belongs in Risk section."""
        spec = self._spec(risk_factors=["2 tipster sources lean the other way."])
        verdict = _render_verdict(spec)
        assert "Main risk:" not in verdict
        assert len(verdict) <= 200

    def test_verdict_still_passes_banned_phrase_check(self):
        """Verdict postures don't contain banned tone-band phrases."""
        for action, sizing, tone in (
            ("speculative punt", "tiny exposure", "cautious"),
            ("lean", "small stake", "moderate"),
            ("back", "standard stake", "confident"),
            ("strong back", "confident stake", "strong"),
        ):
            spec = self._spec(verdict_action=action, verdict_sizing=sizing,
                              evidence_class="supported", tone_band=tone)
            verdict = _render_verdict(spec)
            for phrase in TONE_BANDS[tone]["banned"]:
                assert phrase.lower() not in verdict.lower(), (
                    f"Banned phrase {phrase!r} in {action} verdict"
                )


# ── TONE-BANDS-FIX: Diamond/Gold conviction language regression ────────────────


class TestTierConvictionLanguage:
    """AC-6: Diamond/Gold Verdict must never contain banned hedging phrases.
    AC-2/AC-3: Diamond/Gold must use conviction language in Verdict.
    AC-7: Barcelona vs Atletico Madrid Diamond card verification."""

    # Phrases banned from Diamond/Gold Verdict sections per brief AC-2/AC-3
    DIAMOND_BANNED = ["speculative", "small stake only", "monitor"]
    GOLD_BANNED = ["speculative", "small stake only"]

    def _diamond_spec(self):
        """Mimics a Diamond-tier card with 0 signals — the Barcelona/Atletico scenario."""
        return NarrativeSpec(
            home_name="Barcelona", away_name="Atletico Madrid",
            competition="La Liga", sport="soccer",
            home_story_type="title_push", away_story_type="crisis",
            evidence_class="supported", tone_band="confident",
            verdict_action="strong back", verdict_sizing="standard-to-heavy stake",
            edge_tier="diamond", ev_pct=9.8, odds=2.10, bookmaker="SuperSportBet",
        )

    def _gold_spec(self):
        """Gold-tier card — minimum lean posture required."""
        return NarrativeSpec(
            home_name="Mamelodi Sundowns", away_name="Orlando Pirates",
            competition="PSL", sport="soccer",
            home_story_type="momentum", away_story_type="neutral",
            evidence_class="lean", tone_band="moderate",
            verdict_action="lean", verdict_sizing="small stake",
            edge_tier="gold", ev_pct=5.2, odds=1.85, bookmaker="Hollywoodbets",
        )

    def test_diamond_verdict_no_banned_phrases(self):
        """AC-6: Diamond verdict must never contain hedging phrases."""
        spec = self._diamond_spec()
        verdict = _render_verdict(spec)
        for phrase in self.DIAMOND_BANNED:
            assert phrase.lower() not in verdict.lower(), (
                f"Banned Diamond phrase {phrase!r} found in verdict: {verdict!r}"
            )

    def test_gold_verdict_no_banned_phrases(self):
        """AC-6: Gold verdict must never contain speculative hedging phrases."""
        spec = self._gold_spec()
        verdict = _render_verdict(spec)
        for phrase in self.GOLD_BANNED:
            assert phrase.lower() not in verdict.lower(), (
                f"Banned Gold phrase {phrase!r} found in verdict: {verdict!r}"
            )

    def test_diamond_verdict_uses_conviction_language(self):
        """AC-2 + FIX-NARRATIVE-W82-VARIANT-EXPANSION-01: Diamond verdict
        uses high-conviction language. Conviction is now expressed via the
        Diamond imperative action verb ("Hammer it on") plus
        "standard-to-heavy stake" sizing, which together carry the
        Strong-band tier-floor signal.
        """
        spec = self._diamond_spec()
        verdict = _render_verdict(spec)
        conviction_phrases = [
            "hammer it on", "strong back", "with conviction", "with confidence",
            "premium play", "all point the same way", "standard-to-heavy",
        ]
        assert any(p in verdict.lower() for p in conviction_phrases), (
            f"Diamond verdict lacks conviction language: {verdict!r}"
        )

    def test_gold_verdict_uses_moderate_conviction_language(self):
        """AC-3: Gold verdict must use moderate conviction language."""
        spec = self._gold_spec()
        verdict = _render_verdict(spec)
        moderate_phrases = ["lean", "standard stake", "supported by data", "measured lean"]
        assert any(p in verdict.lower() for p in moderate_phrases), (
            f"Gold verdict lacks moderate conviction language: {verdict!r}"
        )

    def test_diamond_verdict_sizing_not_tiny_or_small(self):
        """AC-2: Diamond sizing must not be tiny exposure or small stake."""
        spec = self._diamond_spec()
        verdict = _render_verdict(spec)
        assert "tiny exposure" not in verdict.lower(), (
            f"Diamond verdict uses 'tiny exposure' sizing: {verdict!r}"
        )
        assert "small stake only" not in verdict.lower(), (
            f"Diamond verdict uses 'small stake only': {verdict!r}"
        )

    def test_barca_atletico_diamond_card_conviction(self):
        """AC-7: Barcelona vs Atletico Madrid Diamond card — 0 signals scenario.
        This is the exact failure case from QA-29 D-1 (P0).
        After TONE-BANDS-FIX, conviction language must appear even with 0 confirming signals."""
        # Simulate the worst case: Diamond tier, 0 confirming signals, no edge_v2
        # The tier floor in build_narrative_spec() fires for this case.
        spec = NarrativeSpec(
            home_name="Barcelona", away_name="Atletico Madrid",
            competition="La Liga", sport="soccer",
            home_story_type="neutral", away_story_type="neutral",
            evidence_class="supported", tone_band="confident",
            verdict_action="strong back", verdict_sizing="standard-to-heavy stake",
            support_level=0, edge_tier="diamond",
            ev_pct=9.8, odds=2.10, bookmaker="SuperSportBet",
        )
        verdict = _render_verdict(spec)
        # Must NOT contain hedging language
        for phrase in self.DIAMOND_BANNED:
            assert phrase.lower() not in verdict.lower(), (
                f"QA-29 D-1 regression: banned phrase {phrase!r} in Diamond verdict"
            )
        # Must contain conviction language. FIX-NARRATIVE-W82-VARIANT-EXPANSION-01
        # added "Hammer it on" + standard-to-heavy stake as the Diamond
        # conviction surface (the brief AC-3 imperative cluster for Diamond).
        conviction_phrases = [
            "hammer it on", "strong back", "with conviction", "with confidence",
            "premium play", "all point the same way", "standard-to-heavy",
        ]
        assert any(p in verdict.lower() for p in conviction_phrases), (
            f"QA-29 D-1 regression: Diamond verdict lacks conviction language: {verdict!r}"
        )

    def test_diamond_tone_band_allows_conviction_phrases(self):
        """AC-2: TONE_BANDS['strong'] must allow Diamond conviction phrases."""
        assert "back with confidence" in TONE_BANDS["strong"]["allowed"]
        assert "standard-to-heavy stake" in TONE_BANDS["strong"]["allowed"]
        assert "strong lean" in TONE_BANDS["strong"]["allowed"]

    def test_gold_tone_band_allows_moderate_phrases(self):
        """AC-3: TONE_BANDS['confident'/'moderate'] must allow Gold conviction phrases.
        BUILD-VERDICT-FLOOR-01: 'lean' removed from TONE_BANDS allowed lists in
        narrative_spec.py to prevent LLM-voice leakage in Sonnet-polished verdicts.
        FIX-NARRATIVE-VOICE-COMPREHENSIVE-01 (2026-04-28): "supported by data"
        moved from confident.allowed to confident.banned per brief Forbidden list
        (flat / generic / not SA Braai Voice).
        """
        assert "standard stake" in TONE_BANDS["confident"]["allowed"]
        # NOTE: "supported by data" is now BANNED (brief Forbidden list).
        assert "supported by data" not in TONE_BANDS["confident"]["allowed"]
        assert "supported by data" in TONE_BANDS["confident"]["banned"]
        assert "small-to-standard stake" in TONE_BANDS["moderate"]["allowed"]
        # "lean" intentionally removed from TONE_BANDS allowed lists in narrative_spec.py
        assert "lean" not in TONE_BANDS["confident"]["allowed"]
        assert "lean" not in TONE_BANDS["moderate"]["allowed"]

    def test_diamond_gold_banned_phrases_in_tone_bands(self):
        """AC-2/AC-3: Banned phrases must be in strong and confident tone bands."""
        assert "small stake only" in TONE_BANDS["strong"]["banned"]
        assert "monitor" in TONE_BANDS["strong"]["banned"]
        assert "small stake only" in TONE_BANDS["confident"]["banned"]
        assert "monitor" in TONE_BANDS["confident"]["banned"]
        assert "small stake only" in TONE_BANDS["moderate"]["banned"]


# ── BASELINE-VERDICT-FIX: Verdict/Risk deduplication regression ───────────────


class TestBaselineNoEdgeVerdictRiskDistinct:
    """BASELINE-VERDICT-FIX (QA-29 D-3): Verdict must differ from Risk on
    baseline_no_edge cards.

    Root cause: _build_risk_factors added _zero_confirm text ("no signals
    backing a pricing gap") even when ev <= 0, where there IS no pricing gap.
    Both sections ended up saying "no edge here" in different words.

    Fix:
    - _build_risk_factors: skip _zero_confirm when ev <= 0 (fall to _default_factors).
    - _render_verdict for monitor: include outcome/odds/bookmaker so Verdict is
      a match-specific assessment rather than a generic disclaimer.
    """

    def _no_edge_edge_data(self, match_key="richards_bay_vs_stellenbosch_2026-04-10",
                           outcome="home", ev=-0.8):
        return {
            "match_key": match_key,
            "outcome": outcome,
            "edge_pct": ev,
            "confirming_signals": 0,
            "stale_minutes": 0,
            "movement_direction": "neutral",
            "tipster_against": 0,
        }

    def test_risk_factors_skip_zero_confirm_when_ev_negative(self):
        """_build_risk_factors with ev <= 0 must NOT add _zero_confirm text.

        _zero_confirm says "model identifies a pricing discrepancy" or "no signals
        backing a pricing gap" — wrong when ev <= 0 and there IS no gap.
        """
        factors = _build_risk_factors(self._no_edge_edge_data(), None, "soccer")
        text = " ".join(factors)
        assert "pricing discrepancy" not in text
        assert "price gap itself" not in text
        assert "typical baseline for this fixture type" not in text

    def test_risk_factors_skip_zero_confirm_when_ev_zero(self):
        """Boundary: ev == 0 must also skip _zero_confirm."""
        edge_data = self._no_edge_edge_data(ev=0.0)
        factors = _build_risk_factors(edge_data, None, "soccer")
        text = " ".join(factors)
        assert "pricing discrepancy" not in text
        assert "price gap itself" not in text

    def test_risk_factors_still_add_zero_confirm_for_positive_ev(self):
        """_zero_confirm must still appear when confirming==0 AND ev > 0 (original behaviour)."""
        edge_data = self._no_edge_edge_data(ev=3.5)
        factors = _build_risk_factors(edge_data, None, "soccer")
        text = " ".join(factors)
        # One of the three _zero_confirm variants must be present
        assert any(p in text for p in (
            "pricing discrepancy",
            "price gap itself",
            "typical baseline for this fixture type",
        )), f"_zero_confirm missing for positive-EV + zero-signal edge: {text!r}"

    def test_verdict_differs_from_risk_richards_bay(self):
        """AC-4: Verdict content must differ from Risk content — Richards Bay case."""
        edge_data = self._no_edge_edge_data()
        risk_factors = _build_risk_factors(edge_data, None, "soccer")
        spec = NarrativeSpec(
            home_name="Richards Bay", away_name="Stellenbosch",
            competition="Premiership (PSL)", sport="soccer",
            home_story_type="neutral", away_story_type="neutral",
            evidence_class="speculative", tone_band="cautious",
            verdict_action="monitor", verdict_sizing="monitor",
            outcome="home", outcome_label="Richards Bay win",
            bookmaker="Hollywoodbets", odds=2.30,
            ev_pct=-0.8, fair_prob_pct=42.0, composite_score=48.0,
            bookmaker_count=2, support_level=0,
            risk_factors=risk_factors, risk_severity="moderate",
            stale_minutes=0, movement_direction="neutral", tipster_against=0,
        )
        risk_text = _render_risk(spec)
        verdict_text = _render_verdict(spec)

        assert risk_text != verdict_text, (
            f"Verdict copies Risk verbatim on baseline_no_edge card:\n"
            f"Risk:    {risk_text!r}\nVerdict: {verdict_text!r}"
        )
        # Risk must NOT contain Verdict-style assessment language
        assert "no confirmed edge" not in risk_text.lower()
        assert "monitor for line movement" not in risk_text.lower()
        assert "no positive expected value" not in risk_text.lower()

    def test_verdict_differs_from_risk_southampton_arsenal(self):
        """AC-5: Southampton vs Arsenal baseline_no_edge — Verdict ≠ Risk."""
        edge_data = self._no_edge_edge_data(
            match_key="southampton_vs_arsenal_2026-04-09",
            outcome="away", ev=-1.2,
        )
        risk_factors = _build_risk_factors(edge_data, None, "soccer")
        spec = NarrativeSpec(
            home_name="Southampton", away_name="Arsenal",
            competition="Premier League", sport="soccer",
            home_story_type="neutral", away_story_type="neutral",
            evidence_class="speculative", tone_band="cautious",
            verdict_action="monitor", verdict_sizing="monitor",
            outcome="away", outcome_label="Arsenal win",
            bookmaker="Betway", odds=1.55,
            ev_pct=-1.2, fair_prob_pct=62.0, composite_score=50.0,
            bookmaker_count=3, support_level=0,
            risk_factors=risk_factors, risk_severity="moderate",
            stale_minutes=0, movement_direction="neutral", tipster_against=0,
        )
        risk_text = _render_risk(spec)
        verdict_text = _render_verdict(spec)

        assert risk_text != verdict_text
        # Verdict must include match-specific details (outcome/bookmaker/odds)
        assert any(s in verdict_text for s in ("Arsenal win", "1.55", "Betway")), (
            f"Verdict lacks match-specific detail: {verdict_text!r}"
        )
        assert "monitor for line movement" not in risk_text.lower()

    def test_verdict_monitor_includes_bookmaker_and_odds(self):
        """Verdict for monitor action must reference bookmaker + odds when known."""
        spec = NarrativeSpec(
            home_name="Richards Bay", away_name="Stellenbosch",
            competition="Premiership (PSL)", sport="soccer",
            home_story_type="neutral", away_story_type="neutral",
            verdict_action="monitor", verdict_sizing="monitor",
            outcome="home", outcome_label="Richards Bay win",
            bookmaker="Hollywoodbets", odds=2.30,
            ev_pct=-0.8,
        )
        verdict = _render_verdict(spec)
        assert "Hollywoodbets" in verdict
        assert "2.30" in verdict
