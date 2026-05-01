"""FIX-VERDICT-CLOSURE-RULE-LOOSEN-AND-GERUND-ACCEPT-01 — AC-2 contract tests.

Broadens _VERDICT_ACTION_RE to accept imperatives + gerunds + declaratives +
action prepositions.  Reverses the strict imperative-only tightening from
FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01 which produced 100% premium
polish refusals and blocked 6 Bronze speculative rows.

14 tests:
  1  test_imperative_back_passes
  2  test_gerund_taking_passes
  3  test_gerund_backing_passes
  4  test_gerund_getting_on_passes
  5  test_declarative_is_the_pick_passes
  6  test_declarative_is_the_lean_passes
  7  test_action_preposition_worth_passes
  8  test_setup_style_observation_still_fails
  9  test_telemetry_observation_still_fails
 10  test_sizing_tail_alone_still_fails
 11  test_4_blocked_premium_cards_now_pass
 12  test_6_blocked_bronze_speculative_now_pass
 13  test_existing_passing_tests_still_pass
 14  test_existing_failure_tests_still_fail
"""
from __future__ import annotations

from narrative_validator import (
    _check_verdict_closure_rule,
    _verdict_closure_components,
)


# ── 1. Imperative baseline (unchanged) ───────────────────────────────────────


def test_imperative_back_passes():
    """Imperative 'back' with all 3 components → PASS for Diamond."""
    verdict = "Back Liverpool at 1.97 with Supabets."
    sev, reason = _check_verdict_closure_rule(
        verdict, "diamond", {"home_team": "Liverpool", "away_team": "Chelsea"},
    )
    assert sev is None, f"imperative back should pass: {reason}"


# ── 2. Gerunds ────────────────────────────────────────────────────────────────


def test_gerund_taking_passes():
    """Gerund 'worth taking' in a full Gold verdict → PASS."""
    verdict = "Worth taking Arsenal at 1.50 with Supabets as a small-stake call."
    sev, reason = _check_verdict_closure_rule(
        verdict, "gold", {"home_team": "Arsenal", "away_team": "Fulham"},
    )
    assert sev is None, f"gerund 'worth taking' should pass: {reason}"


def test_gerund_backing_passes():
    """Gerund 'backing' with team + odds → PASS for Silver."""
    verdict = "Backing Spurs at 3.30 here."
    sev, reason = _check_verdict_closure_rule(
        verdict, "silver", {"home_team": "Spurs", "away_team": "Arsenal"},
    )
    assert sev is None, f"gerund 'backing' should pass: {reason}"


def test_gerund_getting_on_passes():
    """Gerund 'getting on' with team + decimal odds → PASS for Diamond."""
    verdict = "Getting on Liverpool at 1.97 with Supabets."
    sev, reason = _check_verdict_closure_rule(
        verdict, "diamond", {"home_team": "Liverpool", "away_team": "Chelsea"},
    )
    assert sev is None, f"gerund 'getting on' should pass: {reason}"


# ── 3. Declaratives ───────────────────────────────────────────────────────────


def test_declarative_is_the_pick_passes():
    """Declarative 'is the pick' with team + odds → PASS for Diamond."""
    verdict = "Manchester City at 1.36 is the pick."
    sev, reason = _check_verdict_closure_rule(
        verdict, "diamond",
        {"home_team": "Manchester City", "away_team": "Brentford"},
    )
    assert sev is None, f"declarative 'is the pick' should pass: {reason}"


def test_declarative_is_the_lean_passes():
    """Declarative 'is the lean' with team + odds → PASS for Gold."""
    verdict = "Brighton at 1.37 is the lean here — WSB has the best price."
    sev, reason = _check_verdict_closure_rule(
        verdict, "gold",
        {"home_team": "Brighton", "away_team": "Wolves"},
    )
    assert sev is None, f"declarative 'is the lean' should pass: {reason}"


# ── 4. Action prepositions ────────────────────────────────────────────────────


def test_action_preposition_worth_passes():
    """Action preposition 'worth a small play on' → PASS for Silver."""
    verdict = "Worth a small play on Spurs at 3.30 with Sportingbet."
    sev, reason = _check_verdict_closure_rule(
        verdict, "silver",
        {"home_team": "Arsenal", "away_team": "Spurs"},
    )
    assert sev is None, f"action preposition 'worth a play' should pass: {reason}"


# ── 5. Genuine failures still caught ─────────────────────────────────────────


def test_setup_style_observation_still_fails():
    """Setup-style closing sentence with no action verb → CRITICAL for Gold."""
    verdict = "That's where the analysis starts."
    sev, reason = _check_verdict_closure_rule(
        verdict, "gold",
        {"home_team": "Liverpool", "away_team": "Chelsea"},
    )
    assert sev == "CRITICAL", f"setup-style observation should fail, got sev={sev}: {reason}"


def test_telemetry_observation_still_fails():
    """Telemetry observation with no action verb → CRITICAL for Diamond."""
    verdict = "The data has a cleaner read on Royal Challengers Bengaluru."
    sev, reason = _check_verdict_closure_rule(
        verdict, "diamond",
        {"home_team": "Gujarat Titans", "away_team": "Royal Challengers Bengaluru"},
    )
    assert sev == "CRITICAL", f"telemetry observation should fail, got sev={sev}: {reason}"


def test_sizing_tail_alone_still_fails():
    """Sizing tail with no action verb anywhere → CRITICAL for Gold.

    'Small-to-standard stake on this one at the current number.' has no imperative,
    no gerund, no declarative — just a sizing description. Must still fail.
    """
    verdict = "Small-to-standard stake on this one at the current number."
    sev, reason = _check_verdict_closure_rule(
        verdict, "gold",
        {"home_team": "Arsenal", "away_team": "Fulham"},
    )
    assert sev == "CRITICAL", f"sizing tail alone should fail, got sev={sev}: {reason}"


# ── 6. The 4 blocked premium cards now pass ──────────────────────────────────


def test_4_blocked_premium_cards_now_pass():
    """The 4 Premium cards that were blocked by strict imperative-only validator.

    Verdict shapes use gerunds and declaratives — patterns that were rejected
    by FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01.
    After this loosening, all 4 must pass Gate 10.
    """
    cases = [
        # Arsenal vs Fulham (Diamond, EPL)
        {
            "verdict": "Taking Arsenal at 1.48 with Supabets — form holds, Arteta's side have the platform.",
            "tier": "diamond",
            "pack": {"home_team": "Arsenal", "away_team": "Fulham"},
            "label": "arsenal_vs_fulham_2026-05-02",
        },
        # Manchester City vs Brentford (Diamond, EPL)
        {
            "verdict": "Manchester City is the play at 1.36 with Supabets — Guardiola's side have the depth.",
            "tier": "diamond",
            "pack": {"home_team": "Manchester City", "away_team": "Brentford"},
            "label": "manchester_city_vs_brentford_2026-05-09",
        },
        # Liverpool vs Chelsea (Diamond, EPL)
        {
            "verdict": "Backing Liverpool at 1.97 with Supabets — Slot's Reds have Chelsea's number.",
            "tier": "diamond",
            "pack": {"home_team": "Liverpool", "away_team": "Chelsea"},
            "label": "liverpool_vs_chelsea_2026-05-09",
        },
        # Brighton vs Wolves (Gold, EPL)
        {
            "verdict": "Brighton at 1.37 is the lean — WSB has the sharpest price.",
            "tier": "gold",
            "pack": {"home_team": "Brighton", "away_team": "Wolves"},
            "label": "brighton_vs_wolves_2026-05-09",
        },
    ]
    for case in cases:
        sev, reason = _check_verdict_closure_rule(
            case["verdict"], case["tier"], case["pack"],
        )
        assert sev is None, (
            f"{case['label']}: expected pass, got sev={sev!r}: {reason}\n"
            f"  verdict={case['verdict']!r}"
        )


# ── 7. The 6 blocked Bronze speculative rows now pass ────────────────────────


def test_6_blocked_bronze_speculative_now_pass():
    """6 Bronze rows closing with 'Worth taking X at Y as a small-stake call'.

    This shape was blocked by the strict imperative-only validator because
    'worth taking' is a gerund, not an imperative. After the fix, Bronze
    only requires an action verb — 'worth taking' satisfies that.
    """
    cases = [
        "Worth taking Sunrisers Hyderabad at 1.59 with WSB as a small-stake call.",
        "Worth taking Waratahs at 1.68 with GBets as a measured play — form holds.",
        "Worth taking Manchester United at 2.37 with PlayaBets as a small-stake call.",
        "Worth taking AFC Bournemouth at 1.65 with PlayaBets as a small-stake call.",
        "Worth taking Chelsea at 1.75 with HWB as a measured play.",
        "Worth taking Orlando Pirates at 1.90 with HWB as a small-stake call.",
    ]
    for verdict in cases:
        sev, reason = _check_verdict_closure_rule(verdict, "bronze", None)
        assert sev is None, (
            f"Bronze 'worth taking' shape should pass, got sev={sev!r}: {reason}\n"
            f"  verdict={verdict!r}"
        )


# ── 8. Regression — previously passing verdicts still pass ───────────────────


def test_existing_passing_tests_still_pass():
    """Key regression check: verdicts that passed before the tightening still pass."""
    passing_cases = [
        # Clean imperative — Gold
        (
            "Get on Liverpool at 1.97 with Supabets.",
            "gold",
            {"home_team": "Liverpool", "away_team": "Chelsea"},
        ),
        # Multi-sentence with action in last sentence — Diamond
        (
            "Slot's lot are flying. Chelsea have lost five on the bounce. "
            "Get on Liverpool at 1.97 with Supabets.",
            "diamond",
            {"home_team": "Liverpool", "away_team": "Chelsea"},
        ),
        # Silver: action + team, no odds
        (
            "Lean on Liverpool here.",
            "silver",
            {"home_team": "Liverpool", "away_team": "Chelsea"},
        ),
        # Bronze: action verb only
        (
            "Lean on this one — speculative posture only.",
            "bronze",
            None,
        ),
        # Selection keyword instead of team name — Gold
        (
            "Get on the draw at 3.40 with Betway.",
            "gold",
            None,
        ),
        # HTML stripped correctly
        (
            "<b>🏆 Verdict</b>\nSlot's lot are flying. <b>Get on Liverpool at 1.97 with Supabets.</b>",
            "diamond",
            {"home_team": "Liverpool", "away_team": "Chelsea"},
        ),
    ]
    for verdict, tier, pack in passing_cases:
        sev, reason = _check_verdict_closure_rule(verdict, tier, pack)
        assert sev is None, (
            f"Previously passing verdict should still pass: sev={sev!r}, {reason}\n"
            f"  tier={tier!r} verdict={verdict[:80]!r}"
        )


# ── 9. Regression — genuine failures still caught ────────────────────────────


def test_existing_failure_tests_still_fail():
    """Key regression check: verdicts that failed before still fail after loosening."""
    failing_cases = [
        # Liverpool–Chelsea live failure case — no action verb
        (
            "What stands out: Slot's Reds have picked up two wins in their last "
            "three, while Chelsea are in terrible form with five losses from "
            "their last five.",
            "gold",
            {"home_team": "Liverpool", "away_team": "Chelsea"},
            "action_verb",
        ),
        # Gold missing odds shape
        (
            "Form is solid. Get on Liverpool at home.",
            "gold",
            {"home_team": "Liverpool", "away_team": "Chelsea"},
            "odds_shape",
        ),
        # Diamond missing team / selection
        (
            "Form is solid. Get on it at 1.97.",
            "diamond",
            {"home_team": "Liverpool", "away_team": "Chelsea"},
            "team_or_selection",
        ),
        # Silver missing action verb
        (
            "Liverpool at 1.97 looks priced fairly.",
            "silver",
            {"home_team": "Liverpool", "away_team": "Chelsea"},
            "action_verb",
        ),
        # Bronze missing action verb
        (
            "Speculative play with thin signal.",
            "bronze",
            None,
            "action_verb",
        ),
    ]
    for verdict, tier, pack, expected_fragment in failing_cases:
        sev, reason = _check_verdict_closure_rule(verdict, tier, pack)
        assert sev == "CRITICAL", (
            f"Should fail CRITICAL, got sev={sev!r}: {reason}\n"
            f"  tier={tier!r} verdict={verdict[:80]!r}"
        )
        assert expected_fragment in reason, (
            f"Reason should mention {expected_fragment!r}: {reason}"
        )
