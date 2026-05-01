"""FIX-W82-RISK-TAIL-CLEAN-PLACEHOLDER-01 — AC-3 contract tests.

Eight tests verifying that the W82 risk-tail clause is dropped when risk
reads clean/neutral and preserved when a specific risk factor is present.

Background: the 6 default "clean profile" risk factors from _build_risk_factors()
mean "nothing to flag". Injecting extracted words from them into the tail
template produced "even with the clean concern", "factor in the clean note",
"wary of the clean factor" — contradictory prose that shipped on every card
whose risk reads clean. FIX-W82-RISK-TAIL-CLEAN-PLACEHOLDER-01 drops the
tail entirely for clean/neutral risk factors so the verdict ends naturally
at the action sentence.
"""
from __future__ import annotations

import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from narrative_spec import (
    NarrativeSpec,
    _NEUTRAL_RISK_INDICATORS,
    _VERDICT_RISK_STOPWORDS,
    _build_risk_factors,
    _render_verdict_w82_pool,
    _verdict_risk_clause,
)


# ── helpers ───────────────────────────────────────────────────────────────────

_CLEAN_LEAK_PHRASES = ("clean concern", "clean note", "clean factor")


def _make_spec(
    home: str = "Arsenal",
    away: str = "Fulham",
    *,
    tier: str = "gold",
    action: str = "back",
    odds: float = 1.72,
    bookmaker: str = "Hollywoodbets",
    risk_factors: list[str] | None = None,
    risk_severity: str = "low",
) -> NarrativeSpec:
    return NarrativeSpec(
        home_name=home,
        away_name=away,
        competition="Premier League",
        sport="soccer",
        home_story_type="momentum",
        away_story_type="neutral",
        edge_tier=tier,
        verdict_action=action,
        odds=odds,
        bookmaker=bookmaker,
        outcome_label=f"{home} win",
        risk_factors=risk_factors or [],
        risk_severity=risk_severity,
        evidence_class="supported",
        tone_band="confident",
        support_level=2,
    )


def _get_all_default_risk_variants() -> list[str]:
    """Return all 6 default clean-risk variants from _build_risk_factors().

    We set confirming_signals=2 so the zero_confirm branch is skipped, and
    use a home outcome so the away-disadvantage branch is also skipped.
    With no stale/movement/tipster flags, _build_risk_factors() hits the
    'if not factors:' block and returns one of the 6 clean-profile defaults.
    """
    seen: set[str] = set()
    for i in range(300):
        edge_data = {
            "match_key": f"team_a_vs_team_b_match_{i}",
            "outcome": "home",
            "edge_pct": 5.0,
            "confirming_signals": 2,   # avoid zero_confirm branch
            "stale_minutes": 0,        # avoid stale branch
            "movement_direction": "stable",
            "tipster_against": 0,
        }
        factors = _build_risk_factors(edge_data, None, "soccer")
        if factors:
            seen.add(factors[0])
        if len(seen) >= 6:
            break
    return list(seen)


# ── Test 1: clean risk → tail dropped ────────────────────────────────────────

def test_clean_risk_drops_tail():
    """When any of the 6 default clean-risk variants is the only risk factor,
    the verdict must NOT contain 'clean concern', 'clean note', or 'clean factor'."""
    for default_factor in _get_all_default_risk_variants():
        spec = _make_spec(risk_factors=[default_factor])
        verdict = _render_verdict_w82_pool(spec)
        for leak in _CLEAN_LEAK_PHRASES:
            assert leak not in verdict.lower(), (
                f"Clean leak '{leak}' found for risk_factor='{default_factor[:60]}'\n"
                f"Verdict: {verdict}"
            )


# ── Test 2: specific risk 'injury' → tail kept ───────────────────────────────

def test_specific_risk_keeps_tail_injury():
    """A real injury risk factor keeps the tail template.

    The factor starts with 'Injury' so _verdict_risk_clause extracts that word
    first (4-char minimum, not in stopwords) → produces 'injury concern/note/factor'.
    """
    risk = "Injury worry — first-choice striker and fullback both doubtful."
    spec = _make_spec(risk_factors=[risk])
    clause = _verdict_risk_clause(spec)
    assert clause != "", "Expected non-empty risk clause for injury risk factor"
    assert "injury" in clause, f"Expected 'injury' in risk clause, got: '{clause}'"


# ── Test 3: specific risk 'rotation' → tail kept ─────────────────────────────

def test_specific_risk_keeps_tail_rotation():
    """A rotation risk factor keeps the tail template.

    Factor starts with 'Rotation' so that word is extracted first.
    """
    risk = "Rotation risk — manager hinted at changes after midweek exertion."
    spec = _make_spec(risk_factors=[risk])
    clause = _verdict_risk_clause(spec)
    assert clause != "", "Expected non-empty risk clause for rotation risk factor"
    assert "rotation" in clause, f"Expected 'rotation' in risk clause, got: '{clause}'"


# ── Test 4: specific risk 'swing' (real, not from default variant 4) ─────────

def test_specific_risk_keeps_tail_swing():
    """A real swing risk factor (not from default variant 4) keeps the tail.

    Factor starts with 'Swing' so that word is extracted first.
    """
    risk = "Swing danger — both teams capable of turning results in this competition."
    spec = _make_spec(home="Fijian Drua", away="Hurricanes", risk_factors=[risk])
    clause = _verdict_risk_clause(spec)
    assert clause != "", "Expected non-empty risk clause for real swing risk factor"
    assert "swing" in clause, f"Expected 'swing' in risk clause, got: '{clause}'"


# ── Test 5: 30+ synthetic verdicts — zero clean leak ─────────────────────────

def test_no_clean_appears_in_any_risk_tail_position():
    """Generate verdicts across all variant patterns and tier bands. None
    may contain 'clean concern', 'clean note', or 'clean factor'."""
    teams = [
        ("Arsenal", "Fulham"), ("Brighton", "Wolves"),
        ("Liverpool", "Chelsea"), ("Man City", "Brentford"),
        ("Tottenham", "Everton"), ("Aston Villa", "Newcastle"),
        ("West Ham", "Brentford"), ("Nottm Forest", "Bournemouth"),
        ("Leicester", "Ipswich"), ("Southampton", "Crystal Palace"),
    ]
    tiers_actions = [
        ("silver", "lean"), ("gold", "back"), ("diamond", "strong back"),
    ]
    count = 0
    default_variants = _get_all_default_risk_variants()
    for home, away in teams:
        for tier, action in tiers_actions:
            for default_factor in default_variants:
                spec = _make_spec(
                    home=home, away=away, tier=tier, action=action,
                    risk_factors=[default_factor],
                )
                verdict = _render_verdict_w82_pool(spec)
                for leak in _CLEAN_LEAK_PHRASES:
                    assert leak not in verdict.lower(), (
                        f"Clean leak '{leak}' in {home} vs {away} "
                        f"({tier}/{action}): {verdict}"
                    )
                count += 1
    assert count >= 30, f"Expected ≥30 verdicts checked, got {count}"


# ── Test 6: the 4 reported premium cards produce no clean leak ────────────────

def test_existing_4_premium_cards_post_fix_clean_risk_drops_tail():
    """The 4 cards that surfaced this issue must produce zero clean leaks."""
    cards = [
        ("Arsenal", "Fulham", "gold"),
        ("Brighton", "Wolves", "gold"),
        ("Liverpool", "Chelsea", "gold"),
        ("Man City", "Brentford", "gold"),
    ]
    default_variants = _get_all_default_risk_variants()
    for home, away, tier in cards:
        for default_factor in default_variants:
            spec = _make_spec(home=home, away=away, tier=tier, risk_factors=[default_factor])
            verdict = _render_verdict_w82_pool(spec)
            for leak in _CLEAN_LEAK_PHRASES:
                assert leak not in verdict.lower(), (
                    f"{home} vs {away}: clean leak '{leak}' in verdict: {verdict}"
                )


# ── Test 7: action-sentence-only close produces a non-empty verdict ───────────

def test_action_sentence_alone_is_valid_close():
    """When the tail is dropped, the verdict must still be non-empty and contain
    the odds figure (confirming the action sentence is present)."""
    default_variants = _get_all_default_risk_variants()
    for default_factor in default_variants:
        spec = _make_spec(
            home="Liverpool", away="Man City",
            tier="gold", action="back",
            odds=2.10, bookmaker="Betway",
            risk_factors=[default_factor],
        )
        verdict = _render_verdict_w82_pool(spec)
        assert verdict.strip(), "Verdict must be non-empty when tail is dropped"
        assert "2.10" in verdict, (
            f"Odds '2.10' not found in verdict — action sentence may be missing. "
            f"Verdict: '{verdict}'"
        )


# ── Test 8: all 6 default variants are covered by the guard ──────────────────

def test_natural_fallback_used_when_action_close_too_abrupt():
    """All 6 default clean-risk variants must trigger the guard in
    _verdict_risk_clause() — either via _NEUTRAL_RISK_INDICATORS phrase match
    or via the belt-and-suspenders snippet=='clean' check.

    We chose Option A (drop the tail / end on the action sentence) as the
    fix. This test verifies coverage is complete so no variant leaks through.
    """
    default_variants = _get_all_default_risk_variants()
    assert len(default_variants) >= 6, (
        f"Only {len(default_variants)} default variants found — expected 6. "
        "Widen seed range in _get_all_default_risk_variants()."
    )
    for factor in default_variants:
        factor_lower = factor.lower()
        # Primary: phrase-level indicator list
        phrase_matched = any(indicator in factor_lower for indicator in _NEUTRAL_RISK_INDICATORS)
        # Belt-and-suspenders: snippet == "clean"
        words = [w for w in re.findall(r"[A-Za-z]{4,}", factor)
                 if w.lower() not in _VERDICT_RISK_STOPWORDS]
        snippet_is_clean = bool(words) and words[0].lower() == "clean"
        is_covered = phrase_matched or snippet_is_clean
        assert is_covered, (
            f"Default risk factor not covered by either guard:\n  '{factor}'\n"
            f"  phrase_matched={phrase_matched}, snippet_is_clean={snippet_is_clean}"
        )
        # Also verify _verdict_risk_clause() returns "" for this factor
        spec = _make_spec(risk_factors=[factor])
        clause = _verdict_risk_clause(spec)
        assert clause == "", (
            f"_verdict_risk_clause() returned '{clause}' for clean factor:\n  '{factor}'"
        )
