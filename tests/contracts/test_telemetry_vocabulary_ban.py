"""FIX-NARRATIVE-VOICE-COMPREHENSIVE-01 AC-1 — Rule 17 telemetry vocabulary ban.

Scope
-----
Validates that `narrative_validator._check_telemetry_vocabulary` fires on each
banned regex pattern from QA-01 §6.3 + §6.4, passes clean text, applies the
tier-aware enforcement matrix (Bronze allowed `speculative punt`, Gold/Diamond
banned), and integrates with `validate_narrative_for_persistence` such that
premium-tier hits are CRITICAL and non-premium hits are MAJOR.

False-positive risk
-------------------
Some patterns have surrounding-context narrowing (e.g. `\\bin\\s+view\\b` is
gated to `stays|kept|keeps|remains|stay` to avoid hits on "in view of the
squad rotation"). The FP fixtures below document those carve-outs explicitly.
"""
from __future__ import annotations

from narrative_validator import (
    TELEMETRY_VOCABULARY_PATTERNS,
    _check_telemetry_vocabulary,
    validate_narrative_for_persistence,
)


# ── 1. Each banned pattern fires correctly on synthetic violation ────────────


def test_pattern_the_signals_fires():
    text = "Take Liverpool — the supporting signals back the read."
    assert "the signals" in _check_telemetry_vocabulary(text, "gold", "verdict")


def test_pattern_the_signals_no_supporting_fires():
    text = "Verdict: the signals are aligned."
    assert "the signals" in _check_telemetry_vocabulary(text, "gold", "verdict")


def test_pattern_the_reads_fires():
    text = "the reads are clear here."
    assert "the reads" in _check_telemetry_vocabulary(text, "gold", "verdict")


def test_pattern_reads_flag_fires():
    text = "Standard stake — the reads flag stays in view."
    hits = _check_telemetry_vocabulary(text, "gold", "verdict")
    # Both `reads flag` AND `stays in view` should fire.
    assert "reads flag" in hits
    assert "stays in view" in hits


def test_pattern_bookmaker_slipped_fires():
    text = "the bookmaker has slipped at this number."
    assert "bookmaker slipped" in _check_telemetry_vocabulary(text, "gold", "verdict")


def test_pattern_bookmaker_slipped_no_has_fires():
    text = "the bookmaker slipped on this line."
    assert "bookmaker slipped" in _check_telemetry_vocabulary(text, "gold", "verdict")


def test_pattern_in_view_with_stay_verb_fires():
    # The tight regex requires a verb of persistence to match.
    cases = [
        "the reads flag stays in view",
        "the angle remains in view here",
        "kept in view through kickoff",
        "keeps in view across the slate",
    ]
    for c in cases:
        assert "stays in view" in _check_telemetry_vocabulary(c, "gold", "verdict"), c


def test_pattern_in_view_in_legitimate_prose_does_NOT_fire():
    # Documented FP: "in view of the squad rotation, ..." is fine because the
    # quant-speak idiom anchors on a verb of persistence (stays/keeps/remains).
    text = "In view of the squad rotation, factor in their second-string options."
    hits = _check_telemetry_vocabulary(text, "gold", "verdict")
    assert "stays in view" not in hits


def test_pattern_the_case_as_it_stands_fires():
    text = "Standard stake on the case as it stands at this number."
    assert "the case as it stands" in _check_telemetry_vocabulary(text, "gold", "verdict")


def test_pattern_the_case_here_fires():
    text = "the case here is for a single-unit play."
    assert "the case as it stands" in _check_telemetry_vocabulary(text, "gold", "verdict")


def test_pattern_model_estimates_fires():
    text = "The model estimates a true price of 1.62."
    assert "the model estimates" in _check_telemetry_vocabulary(text, "gold", "edge")


def test_pattern_model_implies_fires():
    text = "model implies a 62% chance for the home side."
    assert "the model estimates" in _check_telemetry_vocabulary(text, "gold", "edge")


def test_pattern_model_prices_fires():
    text = "The model prices Brighton at 1.55."
    assert "the model estimates" in _check_telemetry_vocabulary(text, "gold", "edge")


def test_pattern_indicators_line_up_fires():
    text = "2 indicators line up with the call."
    assert "indicators line up" in _check_telemetry_vocabulary(text, "gold", "verdict")


def test_pattern_indicators_align_fires():
    text = "The indicators align around the away pick."
    assert "indicators line up" in _check_telemetry_vocabulary(text, "gold", "verdict")


def test_pattern_structural_signal_fires():
    text = "Structural signal favours the home side."
    assert "structural signal" in _check_telemetry_vocabulary(text, "gold", "edge")


def test_pattern_structural_lean_fires():
    text = "There is a structural lean to the under here."
    assert "structural signal" in _check_telemetry_vocabulary(text, "gold", "edge")


def test_pattern_structural_read_fires():
    text = "The structural read is for a low-scoring affair."
    assert "structural signal" in _check_telemetry_vocabulary(text, "gold", "edge")


def test_pattern_price_edge_fires():
    text = "The price edge here is +5.2%."
    assert "price edge" in _check_telemetry_vocabulary(text, "gold", "edge")


def test_pattern_signal_aware_fires_with_hyphen():
    text = "A signal-aware play at this number."
    assert "signal-aware" in _check_telemetry_vocabulary(text, "gold", "edge")


def test_pattern_signal_aware_fires_with_space():
    text = "A signal aware view of the slate."
    assert "signal-aware" in _check_telemetry_vocabulary(text, "gold", "edge")


def test_pattern_edge_confirms_fires():
    text = "The edge confirms what the form already showed."
    assert "edge confirms" in _check_telemetry_vocabulary(text, "gold", "edge")


# ── 2. Clean text passes (zero hits) ─────────────────────────────────────────


def test_clean_text_braai_voice_passes():
    """Paul's reference braai-voice example — must produce zero hits."""
    text = (
        "Liverpool at 1.97 is too good — Slot's lot are flying, Chelsea have "
        "lost five on the bounce. Get on it before Supabets wakes up."
    )
    assert _check_telemetry_vocabulary(text, "gold", "verdict") == []


def test_clean_text_brighton_example_passes():
    text = (
        "Brighton at 1.38 against a Wolves side that's only won twice in 12 "
        "— easy money, just be ready for the late equaliser."
    )
    assert _check_telemetry_vocabulary(text, "gold", "verdict") == []


def test_clean_text_pereira_forest_example_passes():
    text = (
        "Back Pereira's Forest at 2.52. Solid at home, Newcastle are leaking "
        "late goals. Standard stake."
    )
    assert _check_telemetry_vocabulary(text, "silver", "verdict") == []


def test_clean_text_setup_passes():
    text = (
        "Liverpool come into this on the back of three straight wins, with "
        "Salah back from injury and Chelsea visiting after a brutal week."
    )
    assert _check_telemetry_vocabulary(text, "gold", "setup") == []


def test_empty_text_passes():
    assert _check_telemetry_vocabulary("", "gold", "verdict") == []
    assert _check_telemetry_vocabulary("", "bronze", "narrative_html") == []


# ── 3. Tier-aware enforcement matrix ─────────────────────────────────────────


def test_speculative_punt_fires_on_diamond():
    text = "Verdict: a speculative punt on the under."
    assert "speculative punt" in _check_telemetry_vocabulary(text, "diamond", "verdict")


def test_speculative_punt_fires_on_gold():
    text = "Verdict: speculative punt territory."
    assert "speculative punt" in _check_telemetry_vocabulary(text, "gold", "verdict")


def test_speculative_punt_does_not_fire_on_bronze():
    """Bronze tier is genuinely speculative — `speculative punt` is allowed."""
    text = "Verdict: a speculative punt at long odds."
    assert _check_telemetry_vocabulary(text, "bronze", "verdict") == []


def test_speculative_punt_does_not_fire_on_silver():
    text = "Verdict: speculative punt only."
    assert _check_telemetry_vocabulary(text, "silver", "verdict") == []


def test_other_patterns_fire_on_all_tiers():
    """Non-premium-only patterns fire regardless of tier."""
    text = "the supporting signals back the read."
    for tier in ("diamond", "gold", "silver", "bronze"):
        hits = _check_telemetry_vocabulary(text, tier, "verdict")
        assert "the signals" in hits, f"tier={tier} did not fire"


# ── 4. Integration with validate_narrative_for_persistence ──────────────────


_GOLD_NARRATIVE_WITH_TELEMETRY = (
    "📋 <b>The Setup</b>\n"
    "Liverpool host Chelsea at home in a Premier League fixture.\n"
    "🎯 <b>The Edge</b>\n"
    "The price edge here is +5.2%.\n"
    "⚠️ <b>The Risk</b>\n"
    "Late equaliser is the main risk factor.\n"
    "🏆 <b>Verdict</b>\n"
    "Take Liverpool win at 1.97 with Supabets — the supporting signals back the read."
)
_CLEAN_GOLD_NARRATIVE = (
    "📋 <b>The Setup</b>\n"
    "Liverpool host Chelsea at home, on a three-game winning run.\n"
    "🎯 <b>The Edge</b>\n"
    "Supabets at 1.97 is the play — most books have moved to 1.85 already.\n"
    "⚠️ <b>The Risk</b>\n"
    "Big-game energy is unpredictable — Chelsea could turn up.\n"
    "🏆 <b>Verdict</b>\n"
    "Liverpool at 1.97 is too good. Get on it before Supabets wakes up."
)


def test_premium_telemetry_in_verdict_html_is_critical():
    """Gold/Diamond tier with telemetry vocabulary in verdict_html → CRITICAL.

    FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01 (2026-05-01) — AC-2:
    the narrative_html scope of Gate 8 was dropped (no long-form sections
    written). The verdict_html scan stays in force.
    """
    content = {
        "narrative_html": "",
        "verdict_html": (
            "Slot's Reds at home — the supporting signals back the read. "
            "Take Liverpool at 1.97."
        ),
        "match_id": "liverpool_vs_chelsea_2026-04-30",
        "narrative_source": "w84",
    }
    result = validate_narrative_for_persistence(
        content, evidence_pack=None, edge_tier="gold", source_label="w84"
    )
    assert not result.passed
    tele_failures = [f for f in result.failures if f.gate == "telemetry_vocabulary"]
    assert len(tele_failures) >= 1
    assert all(f.severity == "CRITICAL" for f in tele_failures)


def test_non_premium_telemetry_is_major():
    """Silver/Bronze tier with telemetry vocabulary in verdict_html → MAJOR.

    FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01 (2026-05-01) — AC-2:
    narrative_html scope dropped; the test now feeds telemetry through
    verdict_html directly so the verdict-only Gate 8 fires.
    """
    content = {
        "narrative_html": "",
        "verdict_html": (
            "Slot's Reds at home — the supporting signals back the read. "
            "Take Liverpool at 2.50 with Supabets."
        ),
        "match_id": "team_a_vs_team_b_2026-04-30",
        "narrative_source": "w82",
    }
    result = validate_narrative_for_persistence(
        content, evidence_pack=None, edge_tier="silver", source_label="w82"
    )
    tele_failures = [f for f in result.failures if f.gate == "telemetry_vocabulary"]
    assert len(tele_failures) >= 1
    assert all(f.severity == "MAJOR" for f in tele_failures)


def test_clean_premium_narrative_passes_telemetry_gate():
    content = {
        "narrative_html": _CLEAN_GOLD_NARRATIVE,
        "verdict_html": "Liverpool at 1.97 is too good. Get on it.",
        "match_id": "liverpool_vs_chelsea_2026-04-30",
        "narrative_source": "w84",
    }
    result = validate_narrative_for_persistence(
        content, evidence_pack=None, edge_tier="gold", source_label="w84"
    )
    tele_failures = [f for f in result.failures if f.gate == "telemetry_vocabulary"]
    assert tele_failures == []


def test_telemetry_in_verdict_html_only_fires():
    """Telemetry leak inside verdict_html alone (no narrative_html) is detected."""
    content = {
        "narrative_html": "",
        "verdict_html": "the bookmaker has slipped at 1.97 — standard stake.",
        "match_id": "liverpool_vs_chelsea_2026-04-30",
        "narrative_source": "verdict-cache",
    }
    result = validate_narrative_for_persistence(
        content, evidence_pack=None, edge_tier="diamond", source_label="verdict-cache"
    )
    tele_failures = [f for f in result.failures if f.gate == "telemetry_vocabulary"]
    assert len(tele_failures) == 1
    assert tele_failures[0].severity == "CRITICAL"
    assert "verdict_html" in tele_failures[0].section


def test_speculative_punt_on_bronze_does_not_fail_validator():
    """Bronze tier is genuinely speculative — `speculative punt` is permitted."""
    narrative = (
        "📋 <b>The Setup</b>\n"
        "Underdog at long odds.\n"
        "🎯 <b>The Edge</b>\n"
        "Numbers suggest the line is wide.\n"
        "⚠️ <b>The Risk</b>\n"
        "Bronze cards are inherently low-conviction.\n"
        "🏆 <b>Verdict</b>\n"
        "A speculative punt at this price."
    )
    content = {
        "narrative_html": narrative,
        "verdict_html": "A speculative punt at this price.",
        "match_id": "team_a_vs_team_b_2026-04-30",
        "narrative_source": "w82",
    }
    result = validate_narrative_for_persistence(
        content, evidence_pack=None, edge_tier="bronze", source_label="w82"
    )
    tele_failures = [f for f in result.failures if f.gate == "telemetry_vocabulary"]
    # No telemetry-vocabulary hit because Bronze is the only tier where
    # `speculative punt` is allowed.
    assert tele_failures == []


def test_pattern_catalogue_count_matches_brief():
    """The brief specifies 13 patterns. Lock the count to prevent drift."""
    assert len(TELEMETRY_VOCABULARY_PATTERNS) == 13


def test_validator_idempotent_under_telemetry_gate():
    """Calling the validator twice with the same input produces identical results."""
    content = {
        "narrative_html": _GOLD_NARRATIVE_WITH_TELEMETRY,
        "verdict_html": "Take Liverpool — the bookmaker has slipped.",
        "match_id": "liverpool_vs_chelsea_2026-04-30",
        "narrative_source": "w84",
    }
    r1 = validate_narrative_for_persistence(
        content, evidence_pack=None, edge_tier="gold", source_label="w84"
    )
    r2 = validate_narrative_for_persistence(
        content, evidence_pack=None, edge_tier="gold", source_label="w84"
    )
    assert r1.passed == r2.passed
    assert r1.severity == r2.severity
    # Same gate firings, same details, same ordering.
    assert [(f.gate, f.severity, f.section, f.detail) for f in r1.failures] == [
        (f.gate, f.severity, f.section, f.detail) for f in r2.failures
    ]
