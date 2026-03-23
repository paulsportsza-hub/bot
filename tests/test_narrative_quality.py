"""W82-TESTS: Golden-Card Narrative Regression Suite.

Fixture-based tests asserting narrative quality PROPERTIES across 50 representative
match states. All tests run on the deterministic baseline — no LLM, no DB, fast, CI-ready.

Categories:
  - TestEvidenceVerdictCoherence (15): rendered output never contradicts evidence class
  - TestSetupQuality (10): Setup section always complete, always names both teams
  - TestRiskIntegrity (10): Risk section always present, honest, includes sizing
  - TestEdgeSection (8): Edge section names bookmaker, odds, EV, uses right vocabulary
  - TestToneBandCompliance (7): banned phrases never appear in their tier's output
"""
from __future__ import annotations

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.expanduser("~"), "bot"))

from narrative_spec import (
    NarrativeSpec,
    TONE_BANDS,
    _classify_evidence,
    _build_risk_factors,
    _assess_risk_severity,
    _enforce_coherence,
    _render_baseline,
    _render_setup,
    _render_edge,
    _render_risk,
    _render_verdict,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

_SECTION_HEADERS = ["📋", "🎯", "⚠️", "🏆"]


def _extract_section(baseline: str, emoji: str) -> str:
    """Extract text between one section header and the next."""
    start_idx = baseline.find(emoji)
    if start_idx == -1:
        return ""
    try:
        pos_in_headers = _SECTION_HEADERS.index(emoji)
    except ValueError:
        return baseline[start_idx:]
    if pos_in_headers < len(_SECTION_HEADERS) - 1:
        next_emoji = _SECTION_HEADERS[pos_in_headers + 1]
        end_idx = baseline.find(next_emoji, start_idx + 1)
        end_idx = end_idx if end_idx != -1 else len(baseline)
    else:
        end_idx = len(baseline)
    return baseline[start_idx:end_idx].strip()


def _make_spec(**overrides) -> NarrativeSpec:
    """Create a NarrativeSpec with sensible defaults. Override any field.

    Pass confirming_signals, stale_minutes, movement_direction, tipster_against,
    composite_score, ev_pct to control evidence classification.
    Pass home_story_type, away_story_type, home_coach, away_coach etc. to control
    Setup rendering. Pass risk_severity to override the computed severity.
    """
    defaults: dict = {
        # Identity
        "home_name": "Arsenal", "away_name": "Everton",
        "competition": "Premier League", "sport": "soccer",
        # Setup context
        "home_story_type": "momentum", "away_story_type": "crisis",
        "home_coach": "Mikel Arteta", "away_coach": "Sean Dyche",
        "home_position": 2, "away_position": 17,
        "home_points": 65, "away_points": 20,
        "home_form": "WWWDL", "away_form": "LLLWD",
        "home_record": "W9 D3 L2", "away_record": "W1 D2 L11",
        "home_gpg": 2.3, "away_gpg": 0.9,
        "home_last_result": "beating Chelsea 2-0 at home",
        "away_last_result": "losing to Brighton 0-3 away",
        "h2h_summary": "5 meetings: Arsenal 3W 1D 1L",
        "injuries_home": [], "injuries_away": [],
        # Edge thesis
        "outcome": "home", "outcome_label": "the Arsenal win",
        "bookmaker": "Betway", "odds": 2.10, "ev_pct": 5.2,
        "fair_prob_pct": 52.0, "composite_score": 55.0,
        # Classification inputs (NOT dataclass fields — used to compute class)
        "confirming_signals": 3, "stale_minutes": 0,
        "movement_direction": "neutral", "tipster_against": 0,
    }
    defaults.update(overrides)

    # Build edge_data for classification
    edge_data = {
        "confirming_signals": defaults.pop("confirming_signals"),
        "edge_pct": defaults["ev_pct"],
        "composite_score": defaults["composite_score"],
        "stale_minutes": defaults.get("stale_minutes", 0),
        "movement_direction": defaults.get("movement_direction", "neutral"),
        "tipster_against": defaults.get("tipster_against", 0),
        "outcome": defaults.get("outcome", "home"),
    }

    ev_class, tone, verdict_action, verdict_sizing = _classify_evidence(edge_data)

    # Build risk factors / severity unless caller overrides them
    risk_factors = defaults.pop("risk_factors", None) or _build_risk_factors(
        edge_data, None, defaults.get("sport", "soccer")
    )
    risk_severity = defaults.pop("risk_severity", None) or _assess_risk_severity(
        risk_factors, edge_data
    )

    # Extract only NarrativeSpec field names from defaults.
    # Exclude fields already passed explicitly below to avoid duplicate keyword errors.
    _explicit = {
        "evidence_class", "tone_band", "verdict_action", "verdict_sizing",
        "risk_factors", "risk_severity", "stale_minutes", "movement_direction",
        "tipster_against", "support_level",
    }
    spec_fields = set(NarrativeSpec.__dataclass_fields__)
    spec_kwargs = {
        k: v for k, v in defaults.items()
        if k in spec_fields and k not in _explicit
    }

    spec = NarrativeSpec(
        evidence_class=ev_class,
        tone_band=tone,
        verdict_action=verdict_action,
        verdict_sizing=verdict_sizing,
        risk_factors=risk_factors,
        risk_severity=risk_severity,
        stale_minutes=edge_data["stale_minutes"],
        movement_direction=edge_data["movement_direction"],
        tipster_against=edge_data["tipster_against"],
        support_level=edge_data["confirming_signals"],
        **spec_kwargs,
    )
    return _enforce_coherence(spec)


# ══════════════════════════════════════════════════════════════════════════════
# Category 1: Evidence-Verdict Coherence (15 tests)
# Assert that evidence class and verdict language are NEVER contradictory.
# ══════════════════════════════════════════════════════════════════════════════

class TestEvidenceVerdictCoherence:

    def test_speculative_never_says_strong_back(self):
        """0 signals → rendered output must NOT contain 'strong back'."""
        spec = _make_spec(confirming_signals=0, ev_pct=3.0)
        baseline = _render_baseline(spec)
        assert "strong back" not in baseline.lower()

    def test_speculative_never_says_confident(self):
        """0 signals → rendered output must NOT contain 'confident' as assertion."""
        spec = _make_spec(confirming_signals=0, ev_pct=3.0)
        baseline = _render_baseline(spec)
        assert "confident" not in baseline.lower()

    def test_speculative_never_says_clear_edge(self):
        """0 signals → rendered output must NOT contain 'clear edge'."""
        spec = _make_spec(confirming_signals=0, ev_pct=3.0)
        baseline = _render_baseline(spec)
        assert "clear edge" not in baseline.lower()

    def test_speculative_verdict_contains_sizing_guidance(self):
        """W84-Q15: 0 signals → verdict contains sizing/posture language (disciplined variants)."""
        spec = _make_spec(confirming_signals=0, ev_pct=3.0)
        verdict = _extract_section(_render_baseline(spec), "🏆")
        # New posture words (W84-Q15): monitor, exposure, pass — alongside old: small, speculative
        assert (
            "punt" in verdict.lower()
            or "small" in verdict.lower()
            or "speculative" in verdict.lower()
            or "exposure" in verdict.lower()
            or "monitor" in verdict.lower()
            or "pass" in verdict.lower()
        )

    def test_speculative_sizing_is_tiny_exposure(self):
        """0 signals → verdict contains 'tiny exposure' or 'pass'."""
        spec = _make_spec(confirming_signals=0, ev_pct=3.0)
        verdict = _extract_section(_render_baseline(spec), "🏆")
        assert "tiny exposure" in verdict.lower() or "pass" in verdict.lower()

    def test_lean_never_says_slam_dunk(self):
        """1 signal → output must NOT contain 'slam dunk'."""
        spec = _make_spec(confirming_signals=1, ev_pct=4.0)
        baseline = _render_baseline(spec)
        assert "slam dunk" not in baseline.lower()

    def test_lean_never_says_lock(self):
        """1 signal → output must NOT contain ' lock ' as affirmation."""
        spec = _make_spec(confirming_signals=1, ev_pct=4.0)
        verdict = _extract_section(_render_baseline(spec), "🏆")
        # 'lock' as a standalone affirmation phrase — check it's not a verdict claim
        assert "lock it in" not in verdict.lower()
        assert "lock." not in verdict.lower()

    def test_lean_never_says_no_brainer(self):
        """1 signal → output must NOT contain 'no-brainer'."""
        spec = _make_spec(confirming_signals=1, ev_pct=4.0)
        baseline = _render_baseline(spec)
        assert "no-brainer" not in baseline.lower()

    def test_supported_verdict_says_back(self):
        """3 signals → verdict contains 'back'."""
        spec = _make_spec(confirming_signals=3, ev_pct=5.0, composite_score=55)
        verdict = _extract_section(_render_baseline(spec), "🏆")
        assert "back" in verdict.lower()

    def test_supported_verdict_back_language(self):
        """W84-Q3: 3 signals → verdict uses 'back' or 'green light'."""
        spec = _make_spec(confirming_signals=3, ev_pct=5.0, composite_score=55)
        verdict = _extract_section(_render_baseline(spec), "🏆")
        assert "back" in verdict.lower() or "green light" in verdict.lower()

    def test_supported_verdict_drops_generic_multiple_data_points_line(self):
        spec = _make_spec(confirming_signals=3, contradicting_signals=1, ev_pct=5.0, composite_score=55)
        verdict = _extract_section(_render_baseline(spec), "🏆").lower()
        assert "multiple data points confirm the direction" not in verdict
        assert "3 supporting indicators" in verdict or "3 supporting indicators sit behind it" in verdict

    def test_conviction_strong_language(self):
        """W84-Q3: 5 signals + composite 65 + EV 6% → strong conviction language in verdict."""
        spec = _make_spec(
            confirming_signals=5, ev_pct=6.0, composite_score=65,
            movement_direction="neutral", tipster_against=0,
        )
        verdict = _extract_section(_render_baseline(spec), "🏆")
        assert "strong" in verdict.lower() or "premium" in verdict.lower() or "conviction" in verdict.lower()

    def test_stale_6h_two_signals_becomes_lean(self):
        """2 signals - 1 stale penalty (480 min >= 360 min) = 1 effective → lean/speculative."""
        spec = _make_spec(confirming_signals=2, stale_minutes=480, ev_pct=5.0)
        assert spec.evidence_class in ("lean", "speculative")

    def test_movement_against_downgrades(self):
        """2 signals + movement against = 1 effective → lean."""
        spec = _make_spec(confirming_signals=2, movement_direction="against", ev_pct=4.0)
        assert spec.evidence_class in ("lean", "speculative")

    def test_high_ev_zero_signals_is_speculative(self):
        """15% EV but 0 signals → still speculative (evidence governs, not EV alone)."""
        spec = _make_spec(confirming_signals=0, ev_pct=15.0)
        assert spec.evidence_class == "speculative"
        assert spec.tone_band == "cautious"

    def test_tipster_against_2_prevents_strong_tone(self):
        """5 signals but 2 tipsters against → tone_band must not be strong."""
        spec = _make_spec(
            confirming_signals=5, ev_pct=6.0, composite_score=65, tipster_against=2,
        )
        assert spec.tone_band != "strong"

    def test_all_evidence_classes_render_nonempty_verdict(self):
        """Every evidence class must render a Verdict section with content."""
        for confirming in [0, 1, 3, 5]:
            spec = _make_spec(confirming_signals=confirming)
            verdict = _extract_section(_render_baseline(spec), "🏆")
            assert len(verdict) > 25, f"Verdict too short for {confirming} confirming signals"


# ══════════════════════════════════════════════════════════════════════════════
# Category 2: Setup Quality (10 tests)
# ══════════════════════════════════════════════════════════════════════════════

class TestSetupQuality:

    def test_setup_never_empty(self):
        """Setup must have at least 50 characters for common story types."""
        for story in ["title_push", "crisis", "momentum", "neutral", "fortress"]:
            spec = _make_spec(home_story_type=story)
            setup = _extract_section(_render_baseline(spec), "📋")
            assert len(setup) >= 50, f"Setup too short for {story}: {len(setup)} chars"

    def test_setup_names_home_team(self):
        """Home team name must appear in the Setup section."""
        spec = _make_spec(home_name="Mamelodi Sundowns", away_name="Kaizer Chiefs")
        setup = _extract_section(_render_baseline(spec), "📋")
        assert "Sundowns" in setup or "Mamelodi" in setup

    def test_setup_names_away_team(self):
        """Away team name must appear in the Setup section."""
        spec = _make_spec(home_name="Arsenal", away_name="Everton")
        setup = _extract_section(_render_baseline(spec), "📋")
        assert "Everton" in setup

    def test_no_home_away_placeholder(self):
        """Generic 'Home take on Away' must never appear in output."""
        spec = _make_spec(home_name="Arsenal", away_name="Everton")
        baseline = _render_baseline(spec)
        assert "Home take on Away" not in baseline
        assert "Home vs Away" not in baseline

    def test_coach_appears_in_setup(self):
        """Coach's last name should appear in Setup when coach is provided."""
        spec = _make_spec(home_coach="Mikel Arteta", away_coach="Sean Dyche")
        setup = _extract_section(_render_baseline(spec), "📋")
        # Coach possessive form ("Arteta's") must appear for home team
        assert "Arteta" in setup or "arteta" in setup.lower()

    def test_all_10_story_types_render_nonempty(self):
        """Every story type produces non-empty Setup prose (> 20 chars)."""
        for story in [
            "title_push", "fortress", "crisis", "recovery", "momentum",
            "inconsistent", "draw_merchants", "setback", "anonymous", "neutral",
        ]:
            spec = _make_spec(home_story_type=story)
            setup = _extract_section(_render_baseline(spec), "📋")
            assert len(setup) > 20, f"Empty or very short setup for story_type={story!r}"

    def test_all_10_story_types_produce_distinct_output(self):
        """At least 8 of 10 story types produce different opening prose."""
        outputs = set()
        for story in [
            "title_push", "fortress", "crisis", "recovery", "momentum",
            "inconsistent", "draw_merchants", "setback", "anonymous", "neutral",
        ]:
            spec = _make_spec(
                home_story_type=story,
                home_name="TestTeam",
                home_coach="Bob Smith",
            )
            setup = _extract_section(_render_baseline(spec), "📋")
            outputs.add(setup[:60])  # First 60 chars should differ across story types
        assert len(outputs) >= 8, "Too many story types producing identical opening text"

    def test_h2h_appears_in_setup(self):
        """H2H summary must appear in the Setup section when provided."""
        spec = _make_spec(h2h_summary="6 meetings: Arsenal 4W 1D 1L")
        setup = _extract_section(_render_baseline(spec), "📋")
        assert "6 meetings" in setup

    def test_injury_appears_in_setup(self):
        """Injury player name must appear in Setup when injuries_home is provided."""
        spec = _make_spec(injuries_home=["Saliba (hamstring)"])
        setup = _extract_section(_render_baseline(spec), "📋")
        assert "Saliba" in setup

    def test_form_string_present_in_setup(self):
        """Form data must be reflected in Setup (as dash-separated format W-W-D-L-W)."""
        spec = _make_spec(home_form="WWWLL", home_story_type="momentum")
        setup = _extract_section(_render_baseline(spec), "📋")
        # _form_br() converts "WWWLL" to "W-W-W-L-L"
        assert "W-W-W-L-L" in setup or "WWWLL" in setup


# ══════════════════════════════════════════════════════════════════════════════
# Category 3: Risk Integrity (10 tests)
# ══════════════════════════════════════════════════════════════════════════════

class TestRiskIntegrity:

    def test_risk_never_empty(self):
        """Risk section must always have content (>= 20 chars)."""
        for confirming in [0, 1, 3, 5]:
            spec = _make_spec(confirming_signals=confirming)
            risk = _extract_section(_render_baseline(spec), "⚠️")
            assert len(risk) >= 20, f"Risk too short for {confirming} confirming signals"

    def test_stale_risk_mentions_hours(self):
        """8h stale pricing → risk must mention the hours or 'hour'."""
        spec = _make_spec(stale_minutes=480)
        risk = _extract_section(_render_baseline(spec), "⚠️")
        assert "8" in risk or "hour" in risk.lower()

    def test_zero_signals_risk_mentions_model_only(self):
        """W84-Q3: 0 signals → risk references model-only or no signals."""
        spec = _make_spec(confirming_signals=0)
        risk = _extract_section(_render_baseline(spec), "⚠️")
        assert "model" in risk.lower() or "signal" in risk.lower() or "confirm" in risk.lower()

    def test_risk_includes_sizing_guidance(self):
        """Full output must include at least one sizing guidance word."""
        for confirming in [0, 1, 3]:
            spec = _make_spec(confirming_signals=confirming)
            baseline = _render_baseline(spec)
            assert any(
                word in baseline.lower()
                for word in ["tiny exposure", "small stake", "standard stake",
                             "confident stake", "pass", "size down"]
            ), f"No sizing guidance found for {confirming} confirming signals"

    def test_risk_removes_core_argument_filler(self):
        spec = _make_spec(risk_severity="moderate")
        risk = _extract_section(_render_baseline(spec), "⚠️").lower()
        assert "core argument" not in risk
        assert "core math" not in risk
        assert "stake size measured" not in risk

    def test_away_pick_low_support_mentions_home_advantage(self):
        """Away picks with 1 signal must mention home advantage in Risk."""
        spec = _make_spec(
            outcome="away", outcome_label="the Everton win",
            confirming_signals=1,
        )
        risk = _extract_section(_render_baseline(spec), "⚠️")
        assert "home" in risk.lower() or "away" in risk.lower()

    def test_high_risk_severity_flagged(self):
        """risk_severity=high → Risk contains 'High-risk'."""
        spec = _make_spec(
            risk_factors=["Stale price — hasn't updated in 12h, could shift before kickoff."],
            risk_severity="high",
        )
        risk = _extract_section(_render_baseline(spec), "⚠️")
        assert "High-risk" in risk or "high" in risk.lower()

    def test_low_risk_severity_says_clean(self):
        """risk_severity=low → Risk contains 'clean' or 'appropriate'."""
        spec = _make_spec(
            confirming_signals=4,
            risk_factors=["Standard match variance applies."],
            risk_severity="low",
        )
        risk = _extract_section(_render_baseline(spec), "⚠️")
        assert "manageable" in risk.lower() or "clean" in risk.lower()

    def test_movement_against_risk_mentions_drift(self):
        """movement_direction=against → risk must mention 'drifting' or 'disagree'."""
        spec = _make_spec(movement_direction="against", confirming_signals=2)
        risk = _extract_section(_render_baseline(spec), "⚠️")
        assert "drifting" in risk.lower() or "disagree" in risk.lower()

    def test_tipster_against_risk_mentioned(self):
        """tipster_against=2 → risk section must mention 'tipster'."""
        spec = _make_spec(tipster_against=2, confirming_signals=3)
        risk = _extract_section(_render_baseline(spec), "⚠️")
        assert "tipster" in risk.lower()

    def test_standard_variance_when_no_risk_signals(self):
        """Clean edge (fresh, no movement, no tipster against) → human default risk copy."""
        spec = _make_spec(
            confirming_signals=3, stale_minutes=30,
            movement_direction="neutral", tipster_against=0,
        )
        risk = _extract_section(_render_baseline(spec), "⚠️")
        # W84-Q9: "Standard match variance applies." replaced with 3 MD5-deterministic variants.
        # Any of: "clean risk profile" / "match-day variables" / "Typical match uncertainty"
        assert len(risk) > 10, "Risk section should have substantive content"
        assert "Standard match variance" not in risk, "Legacy clinical phrase should be gone"


# ══════════════════════════════════════════════════════════════════════════════
# Category 4: Edge Section (8 tests)
# ══════════════════════════════════════════════════════════════════════════════

class TestEdgeSection:

    def test_edge_names_bookmaker(self):
        """Edge section must name the bookmaker."""
        spec = _make_spec(bookmaker="SuperSportBet", confirming_signals=3)
        edge = _extract_section(_render_baseline(spec), "🎯")
        assert "SuperSportBet" in edge

    def test_edge_includes_odds(self):
        """Edge section must include the odds value."""
        spec = _make_spec(odds=4.35, confirming_signals=3)
        edge = _extract_section(_render_baseline(spec), "🎯")
        assert "4.35" in edge

    def test_edge_includes_ev_percentage(self):
        """Edge section must include the EV percentage."""
        spec = _make_spec(ev_pct=7.05, confirming_signals=3)
        edge = _extract_section(_render_baseline(spec), "🎯")
        assert "+7.0" in edge or "+7.05" in edge or "7.0%" in edge

    def test_speculative_edge_mentions_expected_value(self):
        """W84-Q3: Speculative edge must reference EV or fair probability."""
        spec = _make_spec(confirming_signals=0, ev_pct=5.5)
        edge = _extract_section(_render_baseline(spec), "🎯")
        assert "expected value" in edge.lower() or "fair probability" in edge.lower() or "edge" in edge.lower()

    def test_speculative_edge_no_banned_phrases(self):
        """W84-Q3: Speculative edge must not contain any legacy banned phrases."""
        spec = _make_spec(confirming_signals=0, ev_pct=5.5)
        edge = _extract_section(_render_baseline(spec), "🎯")
        banned = [
            "numbers-only play", "price is interesting", "thin on supporting signals",
            "tread carefully", "signals are absent", "supporting evidence is thin",
            "pure pricing call",
        ]
        for phrase in banned:
            assert phrase not in edge.lower(), f"Banned phrase found in speculative edge: '{phrase}'"

    def test_lean_edge_mentions_value(self):
        """W84-Q3: Lean evidence class → edge references value or confirming indicator."""
        spec = _make_spec(confirming_signals=1, ev_pct=4.0)
        edge = _extract_section(_render_baseline(spec), "🎯")
        assert "value" in edge.lower() or "confirming" in edge.lower() or "signal" in edge.lower()

    def test_supported_edge_mentions_indicators(self):
        """W84-Q3: Supported evidence class → edge references indicators or support."""
        spec = _make_spec(confirming_signals=3, ev_pct=5.0)
        edge = _extract_section(_render_baseline(spec), "🎯")
        assert "indicator" in edge.lower() or "support" in edge.lower() or "confirm" in edge.lower()

    def test_edge_uses_exact_support_balance_for_mixed_signal_case(self):
        spec = _make_spec(
            confirming_signals=2,
            contradicting_signals=1,
            tipster_available=False,
        )
        edge = _extract_section(_render_baseline(spec), "🎯").lower()
        assert "2 supporting indicators back it, with 1 pushing the other way" in edge
        assert "multiple indicators agree" not in edge
        assert "stand above a pure price guess" not in edge

    def test_edge_does_not_claim_tipster_consensus_when_against(self):
        spec = _make_spec(
            confirming_signals=3,
            contradicting_signals=1,
            tipster_available=True,
            tipster_agrees=False,
        )
        edge = _extract_section(_render_baseline(spec), "🎯").lower()
        assert "tipster consensus leans the same way" not in edge
        assert "tipster consensus all point the same direction" not in edge
        assert "tipster consensus is not on the same side" in edge

    def test_supported_edge_drops_repeated_better_supported_shell(self):
        spec = _make_spec(confirming_signals=3, contradicting_signals=1, ev_pct=5.0)
        edge = _extract_section(_render_baseline(spec), "🎯").lower()
        assert "one of the better-supported plays on the card" not in edge

    def test_conviction_edge_strong_language(self):
        """W84-Q3: Conviction evidence class → edge uses strong confident language."""
        spec = _make_spec(
            confirming_signals=5, ev_pct=6.0, composite_score=65,
            tipster_against=0, movement_direction="neutral",
        )
        edge = _extract_section(_render_baseline(spec), "🎯")
        assert "strong" in edge.lower() or "conviction" in edge.lower() or "everything lines up" in edge.lower() or "mispriced" in edge.lower()


# ══════════════════════════════════════════════════════════════════════════════
# Category 5: Tone Band Compliance (7 tests)
# ══════════════════════════════════════════════════════════════════════════════

class TestToneBandCompliance:

    def test_speculative_baseline_no_banned_cautious_phrases(self):
        """Speculative / cautious tone → no banned cautious phrases in full output."""
        spec = _make_spec(confirming_signals=0, ev_pct=3.0)
        baseline = _render_baseline(spec)
        assert spec.tone_band == "cautious"
        for phrase in TONE_BANDS["cautious"]["banned"]:
            assert phrase.lower() not in baseline.lower(), (
                f"Banned cautious phrase {phrase!r} found in speculative baseline"
            )

    def test_lean_baseline_no_banned_moderate_phrases(self):
        """Lean / moderate tone → no banned moderate phrases in full output."""
        spec = _make_spec(confirming_signals=1, ev_pct=4.0)
        baseline = _render_baseline(spec)
        assert spec.tone_band == "moderate"
        for phrase in TONE_BANDS["moderate"]["banned"]:
            assert phrase.lower() not in baseline.lower(), (
                f"Banned moderate phrase {phrase!r} found in lean baseline"
            )

    def test_supported_baseline_no_banned_confident_phrases(self):
        """Supported / confident tone → no banned confident phrases in full output."""
        spec = _make_spec(confirming_signals=3, ev_pct=5.0)
        baseline = _render_baseline(spec)
        assert spec.tone_band == "confident"
        for phrase in TONE_BANDS["confident"]["banned"]:
            assert phrase.lower() not in baseline.lower(), (
                f"Banned confident phrase {phrase!r} found in supported baseline"
            )

    def test_conviction_baseline_no_banned_strong_phrases(self):
        """Conviction / strong tone → no banned strong phrases in full output."""
        spec = _make_spec(
            confirming_signals=5, ev_pct=6.0, composite_score=65,
            tipster_against=0, movement_direction="neutral",
        )
        baseline = _render_baseline(spec)
        assert spec.tone_band == "strong"
        for phrase in TONE_BANDS["strong"]["banned"]:
            assert phrase.lower() not in baseline.lower(), (
                f"Banned strong phrase {phrase!r} found in conviction baseline"
            )

    def test_guaranteed_never_in_any_output(self):
        """'guaranteed' must never appear regardless of tier."""
        for confirming in [0, 1, 3, 5]:
            spec = _make_spec(
                confirming_signals=confirming,
                composite_score=65 if confirming == 5 else 55,
                ev_pct=6.0 if confirming == 5 else 5.0,
                tipster_against=0, movement_direction="neutral",
            )
            baseline = _render_baseline(spec)
            assert "guaranteed" not in baseline.lower(), (
                f"'guaranteed' found in baseline for confirming_signals={confirming}"
            )

    def test_lock_it_in_never_in_any_output(self):
        """'lock it in' must never appear in any rendered baseline."""
        for confirming in [0, 1, 3]:
            spec = _make_spec(confirming_signals=confirming, ev_pct=5.0)
            baseline = _render_baseline(spec)
            assert "lock it in" not in baseline.lower(), (
                f"'lock it in' found in baseline for confirming_signals={confirming}"
            )

    def test_no_brainer_never_in_any_output(self):
        """'no-brainer' must never appear in any rendered baseline."""
        for confirming in [0, 1, 3, 5]:
            spec = _make_spec(
                confirming_signals=confirming,
                composite_score=65 if confirming == 5 else 55,
                ev_pct=6.0 if confirming == 5 else 5.0,
                tipster_against=0, movement_direction="neutral",
            )
            baseline = _render_baseline(spec)
            assert "no-brainer" not in baseline.lower(), (
                f"'no-brainer' found in baseline for confirming_signals={confirming}"
            )
