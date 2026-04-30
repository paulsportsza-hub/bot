"""FIX-VERDICT-CLOSURE-AND-BREAKDOWN-VISIBILITY-01 — AC-1 contract tests.

Verdict closure rule: the LAST sentence of verdict_html MUST close with an
ACTUAL verdict. Live failure case (Liverpool vs Chelsea Gold 1.97 Supabets,
29 Apr 2026 ~20:25 SAST) closed on form data without ever telling the user
to back anyone — passed all existing gates because tier-band tone is fine,
no telemetry vocab, no banned phrases. Paul's directive (verbatim): "Every
verdict must end with an ACTUAL verdict. 'Back X', 'Bet on Y', 'Put your
money on Z'."

Tier-aware enforcement matrix:
  - Diamond + Gold (Strong-band): all 3 components required → PASS.
    Missing ANY → CRITICAL.
  - Silver: action verb required; team OR odds optional but at least one.
    Missing both → CRITICAL.
  - Bronze: action verb required. Missing → CRITICAL.

Test surface: ≥20 tests covering:
  - Each tier's enforcement
  - Multi-sentence verdicts
  - Single-sentence verdicts (action+team+odds in one sentence → pass)
  - Edge cases (selection names like "BTTS", odds shapes for all 3 systems)
  - Closing-sentence tokenisation
  - End-to-end through _validate_narrative_for_persistence
"""
from __future__ import annotations

from narrative_validator import (
    _check_verdict_closure_rule,
    _last_sentence,
    _verdict_closure_components,
    _validate_narrative_for_persistence,
)


# ── 1. Closing-sentence tokenisation (AC-1.5) ────────────────────────────────


def test_last_sentence_strips_html_tags():
    """HTML tags are stripped before tokenising."""
    assert _last_sentence("<b>Setup.</b> Get on Liverpool at 1.97.") == \
        "Get on Liverpool at 1.97"


def test_last_sentence_handles_multi_sentence():
    """Multi-sentence input → returns the LAST non-empty segment."""
    text = (
        "Slot's lot are flying. Chelsea have lost five on the bounce. "
        "Get on Liverpool at 1.97 with Supabets."
    )
    last = _last_sentence(text)
    assert last == "Get on Liverpool at 1.97 with Supabets"


def test_last_sentence_strips_trailing_punctuation():
    """Trailing punctuation . ! ? ; , are stripped from the closing sentence."""
    assert _last_sentence("Form solid. Take Man City at 1.36.") == \
        "Take Man City at 1.36"


def test_last_sentence_empty_input_returns_empty():
    """Empty / whitespace input returns empty string."""
    assert _last_sentence("") == ""
    assert _last_sentence("   ") == ""


def test_last_sentence_single_sentence_no_terminator():
    """Single sentence with no trailing terminator still returns the sentence."""
    assert _last_sentence("Get on Liverpool at 1.97 with Supabets") == \
        "Get on Liverpool at 1.97 with Supabets"


# ── 2. Component detection (AC-1.1, 1.2, 1.3) ────────────────────────────────


def test_components_action_team_odds_decimal():
    """All three components present with decimal odds → all True."""
    text = "Get on Liverpool at 1.97 with Supabets."
    has_action, has_team, has_odds = _verdict_closure_components(
        text, "Liverpool", "Chelsea",
    )
    assert has_action and has_team and has_odds


def test_components_fraction_odds():
    """Fractional odds (11/10, 100/1) detected by odds shape regex."""
    text = "Back Liverpool at 11/10 with Supabets."
    _, _, has_odds = _verdict_closure_components(text, "Liverpool", "Chelsea")
    assert has_odds


def test_components_american_odds():
    """American odds (+150, -200) detected by odds shape regex."""
    text = "Take Liverpool at -150 with Supabets."
    _, _, has_odds = _verdict_closure_components(text, "Liverpool", "Chelsea")
    assert has_odds


def test_components_selection_keyword_btts():
    """BTTS as selection keyword counts as team_or_selection."""
    text = "Back BTTS at 1.85 with Supabets."
    _, has_team_or_sel, _ = _verdict_closure_components(text, "Arsenal", "Spurs")
    assert has_team_or_sel


def test_components_selection_keyword_over():
    """'over 2.5' as selection keyword counts as team_or_selection."""
    text = "Get on over 2.5 at 1.95 with Hollywoodbets."
    _, has_team_or_sel, _ = _verdict_closure_components(text, "Arsenal", "Spurs")
    assert has_team_or_sel


def test_components_selection_keyword_draw():
    """'draw' as selection keyword counts."""
    text = "Take the draw at 3.40 with Betway."
    _, has_team_or_sel, _ = _verdict_closure_components(text, "Arsenal", "Spurs")
    assert has_team_or_sel


def test_components_action_verbs_all_clusters():
    """Each action verb in the cluster is detected."""
    for verb_text in [
        "Back Liverpool at 1.97.",
        "Take Liverpool at 1.97.",
        "Bet on Liverpool at 1.97.",
        "Get on Liverpool at 1.97.",
        "Put your money on Liverpool at 1.97.",
        "Hammer it on Liverpool at 1.97.",
        "Get behind Liverpool at 1.97.",
        "Lean on Liverpool at 1.97.",
        "Ride Liverpool at 1.97.",
        "Smash Liverpool at 1.97.",
    ]:
        has_action, _, _ = _verdict_closure_components(
            verb_text, "Liverpool", "Chelsea",
        )
        assert has_action, f"Action verb missed in: {verb_text!r}"


def test_components_no_action_verb():
    """Closing sentence with no action verb → has_action False."""
    text = (
        "What stands out: Slot's Reds have picked up two wins in their "
        "last three, while Chelsea are in terrible form."
    )
    has_action, _, _ = _verdict_closure_components(text, "Liverpool", "Chelsea")
    assert not has_action


# ── 3. Tier-aware enforcement (AC-1.6) ───────────────────────────────────────


def test_diamond_all_three_passes():
    """Diamond verdict with action + team + odds → no failure."""
    text = (
        "Slot's lot are flying. Chelsea have lost five on the bounce. "
        "Get on Liverpool at 1.97 with Supabets."
    )
    sev, _ = _check_verdict_closure_rule(
        text, "diamond", {"home_team": "Liverpool", "away_team": "Chelsea"},
    )
    assert sev is None


def test_gold_all_three_passes():
    """Gold verdict with action + team + odds → no failure."""
    text = "Form solid, line slightly soft. Take Man City at 1.36 (Supabets), measured stake."
    sev, _ = _check_verdict_closure_rule(
        text, "gold", {"home_team": "Man City", "away_team": "Brentford"},
    )
    assert sev is None


def test_gold_missing_odds_fails_critical():
    """Gold closing sentence missing odds shape → CRITICAL."""
    text = "Form is solid. Get on Liverpool at home."
    sev, reason = _check_verdict_closure_rule(
        text, "gold", {"home_team": "Liverpool", "away_team": "Chelsea"},
    )
    assert sev == "CRITICAL"
    assert "odds_shape" in reason


def test_diamond_missing_action_fails_critical():
    """Diamond closing sentence missing action verb → CRITICAL.

    Verbatim Liverpool–Chelsea live failure case from the brief.
    """
    text = (
        "What stands out: Slot's Reds have picked up two wins in their last "
        "three, while Chelsea are in terrible form with five losses from "
        "their last five."
    )
    sev, reason = _check_verdict_closure_rule(
        text, "gold", {"home_team": "Liverpool", "away_team": "Chelsea"},
    )
    assert sev == "CRITICAL"
    assert "action_verb" in reason


def test_diamond_missing_team_fails_critical():
    """Diamond closing sentence missing team / selection → CRITICAL."""
    text = "Form is solid. Get on it at 1.97."
    sev, reason = _check_verdict_closure_rule(
        text, "diamond", {"home_team": "Liverpool", "away_team": "Chelsea"},
    )
    assert sev == "CRITICAL"
    assert "team_or_selection" in reason


def test_silver_action_only_passes_with_team_or_odds():
    """Silver: action verb required + at least one of team/odds.

    Silver with action+team but no odds → PASS.
    Silver with action+odds but no team → PASS.
    """
    # action + team, no odds.
    text1 = "Lean on Liverpool here."
    sev1, _ = _check_verdict_closure_rule(
        text1, "silver", {"home_team": "Liverpool", "away_team": "Chelsea"},
    )
    assert sev1 is None
    # action + odds, no team / selection.
    text2 = "Lean on it at 1.97."
    sev2, _ = _check_verdict_closure_rule(text2, "silver", None)
    assert sev2 is None


def test_silver_missing_both_team_and_odds_fails_critical():
    """Silver closing sentence with action verb but no team and no odds → CRITICAL."""
    text = "Lean on this one."
    sev, reason = _check_verdict_closure_rule(text, "silver", None)
    assert sev == "CRITICAL"
    assert "team_or_selection" in reason or "odds_shape" in reason


def test_silver_missing_action_fails_critical():
    """Silver closing sentence missing action verb → CRITICAL."""
    text = "Liverpool at 1.97 looks priced fairly."
    sev, reason = _check_verdict_closure_rule(
        text, "silver", {"home_team": "Liverpool", "away_team": "Chelsea"},
    )
    assert sev == "CRITICAL"
    assert "action_verb" in reason


def test_bronze_action_verb_only_passes():
    """Bronze: action verb required, team / odds optional."""
    text = "Lean on this one — speculative posture only."
    sev, _ = _check_verdict_closure_rule(text, "bronze", None)
    assert sev is None


def test_bronze_missing_action_fails_critical():
    """Bronze closing sentence missing action verb → CRITICAL."""
    text = "Speculative play with thin signal."
    sev, reason = _check_verdict_closure_rule(text, "bronze", None)
    assert sev == "CRITICAL"
    assert "action_verb" in reason


# ── 4. Single-sentence verdicts (AC-1.6) ─────────────────────────────────────


def test_single_sentence_action_team_odds():
    """Single-sentence verdict with all 3 components → PASS for any tier."""
    text = "Get on Liverpool at 1.97 with Supabets."
    for tier in ("diamond", "gold", "silver", "bronze"):
        sev, _ = _check_verdict_closure_rule(
            text, tier, {"home_team": "Liverpool", "away_team": "Chelsea"},
        )
        assert sev is None, f"Single-sentence verdict failed on tier={tier}"


def test_single_sentence_no_action_fails_premium():
    """Single-sentence verdict with no action verb fails Strong-band."""
    text = "Liverpool's form is solid at home and Chelsea are leaking goals."
    sev, _ = _check_verdict_closure_rule(
        text, "gold", {"home_team": "Liverpool", "away_team": "Chelsea"},
    )
    assert sev == "CRITICAL"


# ── 5. Edge cases ────────────────────────────────────────────────────────────


def test_empty_verdict_returns_no_failure():
    """Empty verdict_html → no failure (defensive — caller may pass empty)."""
    sev, reason = _check_verdict_closure_rule("", "diamond", None)
    assert sev is None
    assert reason == ""


def test_unknown_tier_permissive():
    """Unknown tier label → permissive (no failure raised)."""
    text = "Liverpool's form is solid."
    sev, _ = _check_verdict_closure_rule(text, "platinum", None)
    assert sev is None


def test_evidence_pack_none_uses_selection_keywords():
    """When evidence_pack is None, team match is skipped but selection
    keywords (BTTS, draw, over X.5 etc.) still count."""
    text = "Get on the draw at 3.40 with Betway."
    sev, _ = _check_verdict_closure_rule(text, "gold", None)
    assert sev is None  # has_action + has_selection (draw) + has_odds = pass


def test_html_stripped_before_tokenisation():
    """HTML tags don't interfere with sentence tokenisation."""
    text = (
        "<b>🏆 Verdict</b>\n"
        "Slot's lot are flying. <b>Get on Liverpool at 1.97 with Supabets.</b>"
    )
    sev, _ = _check_verdict_closure_rule(
        text, "diamond", {"home_team": "Liverpool", "away_team": "Chelsea"},
    )
    assert sev is None


def test_trailing_period_stripped_before_match():
    """Trailing punctuation on the closing sentence does not break the match.

    The closing-sentence tokenisation strips trailing terminators; the action
    verb / team / odds detectors should still fire.
    """
    text = "Get on Liverpool at 1.97 with Supabets!"
    sev, _ = _check_verdict_closure_rule(
        text, "diamond", {"home_team": "Liverpool", "away_team": "Chelsea"},
    )
    assert sev is None


def test_closing_sentence_after_setup_observation():
    """Setup-style observation sentence followed by action sentence → passes.

    Mirrors the brief's PASS example: "Slot's lot are flying, Chelsea have
    lost five on the bounce. Get on Liverpool at 1.97 with Supabets."
    """
    text = (
        "Slot's lot are flying. Chelsea have lost five on the bounce. "
        "Get on Liverpool at 1.97 with Supabets."
    )
    sev, _ = _check_verdict_closure_rule(
        text, "gold", {"home_team": "Liverpool", "away_team": "Chelsea"},
    )
    assert sev is None


# ── 6. End-to-end wiring through _validate_narrative_for_persistence ─────────


def test_validator_e2e_diamond_clean_passes():
    """Full validator pass: clean Diamond verdict → no closure-rule failure."""
    verdict = "Slot's lot are flying. Get on Liverpool at 1.97 with Supabets."
    narrative_html = (
        "🎯 Liverpool vs Chelsea\n"
        "📋 <b>The Setup</b>\n\n"
        "Liverpool sit 2nd with 8 wins from 12. Chelsea have dropped 5 on the bounce.\n\n"
        "🎯 <b>The Edge</b>\n\n"
        "Supabets has them at 1.97 vs our fair price 2.10.\n\n"
        "⚠️ <b>The Risk</b>\n\n"
        "Squad rotation possible after midweek.\n\n"
        "🏆 <b>Verdict</b>\n\n"
        + verdict
    )
    content = {
        "narrative_html": narrative_html,
        "verdict_html": verdict,
        "match_id": "liverpool_vs_chelsea_2026-04-29",
        "narrative_source": "w84",
    }
    result = _validate_narrative_for_persistence(
        content,
        evidence_pack={"home_team": "Liverpool", "away_team": "Chelsea"},
        edge_tier="gold",
        source_label="w84",
    )
    closure_failures = [f for f in result.failures if f.gate == "verdict_closure_rule"]
    assert closure_failures == []


def test_validator_e2e_gold_no_action_fails_critical():
    """Liverpool–Chelsea live failure repro through the full validator."""
    verdict = (
        "What stands out: Slot's Reds have picked up two wins in their last "
        "three, while Chelsea are in terrible form with five losses from "
        "their last five."
    )
    content = {
        "narrative_html": f"🏆 <b>Verdict</b>\n\n{verdict}",
        "verdict_html": verdict,
        "match_id": "liverpool_vs_chelsea_2026-04-29",
        "narrative_source": "w84",
    }
    result = _validate_narrative_for_persistence(
        content,
        evidence_pack={"home_team": "Liverpool", "away_team": "Chelsea"},
        edge_tier="gold",
        source_label="w84",
    )
    assert any(f.gate == "verdict_closure_rule" for f in result.failures)
    closure_failure = next(
        f for f in result.failures if f.gate == "verdict_closure_rule"
    )
    assert closure_failure.severity == "CRITICAL"
    assert not result.passed


def test_validator_e2e_bronze_speculative_passes():
    """Bronze tier with cautious-band action verb → pass closure rule."""
    verdict = "Lean on this one — speculative posture only."
    content = {
        "narrative_html": f"🏆 <b>Verdict</b>\n\n{verdict}",
        "verdict_html": verdict,
        "match_id": "x_vs_y_2026-04-29",
        "narrative_source": "w84",
    }
    result = _validate_narrative_for_persistence(
        content,
        evidence_pack=None,
        edge_tier="bronze",
        source_label="w84",
    )
    closure_failures = [f for f in result.failures if f.gate == "verdict_closure_rule"]
    assert closure_failures == []


# ── FIX-VERDICT-CLOSURE-MINIMAL-RESTORE-01 (2026-04-30) — AC-1 broadening ─────
# Brief AC-1: "_VERDICT_ACTION_RE must accept BOTH imperative and declarative
# shapes." Added 5 tests covering "is the {pick, play, call, lean, bet}".


def test_declarative_is_the_pick_passes_action_check():
    """Declarative recommendation 'is the pick' counts as an action verb."""
    verdict = "Liverpool is the pick at Supabets 1.97."
    sev, _reason = _check_verdict_closure_rule(
        verdict, "gold",
        {"home_team": "Liverpool", "away_team": "Chelsea"},
    )
    # All 3 components present (declarative action + team + odds) → PASS.
    assert sev is None, f"expected pass, got {sev}: {_reason}"


def test_declarative_is_the_play_passes_action_check():
    """Declarative recommendation 'is the play' counts as an action verb.

    Verdict needs all 3 components in the closing sentence for Diamond — full
    team name is required (multi-word substring match).
    """
    verdict = "Manchester City is the play at 1.36 with Supabets."
    sev, _reason = _check_verdict_closure_rule(
        verdict, "diamond",
        {"home_team": "Manchester City", "away_team": "Brentford"},
    )
    assert sev is None, f"expected pass with full team name, got {sev}: {_reason}"


def test_declarative_is_the_call_passes_action_check():
    """Declarative recommendation 'is the call' counts as an action verb."""
    verdict = "Arsenal is the call at 1.85 on Hollywoodbets."
    sev, _reason = _check_verdict_closure_rule(
        verdict, "gold",
        {"home_team": "Arsenal", "away_team": "Tottenham"},
    )
    assert sev is None, f"expected pass, got {sev}: {_reason}"


def test_declarative_is_the_lean_passes_action_check():
    """Declarative recommendation 'is the lean' counts as an action verb."""
    verdict = "Liverpool at 1.97 with Supabets is the lean."
    sev, _reason = _check_verdict_closure_rule(
        verdict, "silver",
        {"home_team": "Liverpool", "away_team": "Chelsea"},
    )
    # Silver: action + (team OR odds). Both present → PASS.
    assert sev is None, f"expected pass, got {sev}: {_reason}"


def test_declarative_is_the_bet_passes_action_check():
    """Declarative recommendation 'is the bet' counts as an action verb."""
    verdict = "Sundowns is the bet at 1.45 with Hollywoodbets."
    sev, _reason = _check_verdict_closure_rule(
        verdict, "diamond",
        {"home_team": "Sundowns", "away_team": "Pirates"},
    )
    assert sev is None, f"expected pass, got {sev}: {_reason}"
