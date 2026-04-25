"""FIX-NARRATIVE-RISK-RESOLUTION-01 — Verdict prose must reference Risk.

Covers:
  AC-2: Unit tests for _find_risk_resolution_violations and _tokenise_meaningful.
  AC-3: _validate_polish gate 8c rejects Verdict that ignores fixture-specific Risk.
  AC-5: evidence_pack.py prompt carries the VERDICT-CITES-RISK instruction.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ensure_scrapers_importable

ensure_scrapers_importable()


# ── Shared narrative fixtures ─────────────────────────────────────────────────

_RISK_INJURY = (
    "⚠️ <b>The Risk</b>\n"
    "The Saka injury is a real concern — Arsenal creative output drops noticeably "
    "when their Brazilian magician is absent from the left flank."
)
_VERDICT_RESOLVES = (
    "🏆 <b>Verdict</b>\n"
    "Discount the Saka injury concern — Arsenal have depth in the wide channels, "
    "and the 1.85 with Hollywoodbets still represents genuine expected value at lean stake."
)
_VERDICT_GENERIC = (
    "🏆 <b>Verdict</b>\n"
    "Back at 1.85 with Hollywoodbets — small stake, the lean is with the home side."
)

_CLEAN_NARRATIVE = (
    "📋 <b>The Setup</b>\nArsenal sit third, seven wins from nine. Fulham solid mid-table.\n\n"
    "🎯 <b>The Edge</b>\nHollywoodbets price Arsenal at 1.85 — EV 4.5%, genuine lean value.\n\n"
    f"{_RISK_INJURY}\n\n"
    f"{_VERDICT_RESOLVES}"
)

_DIRTY_NARRATIVE = (
    "📋 <b>The Setup</b>\nArsenal sit third, seven wins from nine. Fulham solid mid-table.\n\n"
    "🎯 <b>The Edge</b>\nHollywoodbets price Arsenal at 1.85 — EV 4.5%, genuine lean value.\n\n"
    f"{_RISK_INJURY}\n\n"
    f"{_VERDICT_GENERIC}"
)

_NARRATIVE_NO_RISK = (
    "📋 <b>The Setup</b>\nContext here.\n\n"
    "🎯 <b>The Edge</b>\nEdge at 1.85.\n\n"
    "🏆 <b>Verdict</b>\nBack Arsenal at lean stake."
)


# ── AC-2a: missing overlap fires verdict_ignores_risk ─────────────────────────

def test_verdict_ignores_risk_fires():
    """Fixture-specific Risk with generic Verdict triggers verdict_ignores_risk."""
    from bot import _find_risk_resolution_violations

    reasons = _find_risk_resolution_violations(_DIRTY_NARRATIVE)
    assert any("verdict_ignores_risk" in r for r in reasons), (
        f"Expected verdict_ignores_risk in reasons; got {reasons}"
    )


# ── AC-2b: boilerplate Risk fires risk_boilerplate ───────────────────────────

def test_risk_boilerplate_fires_on_thin_generic_risk():
    """Generic boilerplate phrase + < 6 meaningful tokens fires risk_boilerplate."""
    from bot import _find_risk_resolution_violations

    narrative = (
        "📋 <b>The Setup</b>\nContext.\n\n"
        "🎯 <b>The Edge</b>\nEdge.\n\n"
        "⚠️ <b>The Risk</b>\nAll things considered, usual variance applies.\n\n"
        "🏆 <b>Verdict</b>\nBack at lean stake with standard approach."
    )
    reasons = _find_risk_resolution_violations(narrative)
    assert "risk_boilerplate" in reasons, f"Expected risk_boilerplate in {reasons}"


# ── AC-2c: clean narrative (Verdict resolves Risk) passes ────────────────────

def test_clean_narrative_with_risk_resolution_passes():
    """Verdict that explicitly resolves an injury concern passes the gate."""
    from bot import _find_risk_resolution_violations

    reasons = _find_risk_resolution_violations(_CLEAN_NARRATIVE)
    assert reasons == [], f"Expected [], got {reasons}"


# ── AC-2d: missing Risk section returns [] ───────────────────────────────────

def test_missing_risk_section_returns_empty_list():
    """When Risk section is absent, gate returns [] — not our responsibility."""
    from bot import _find_risk_resolution_violations

    reasons = _find_risk_resolution_violations(_NARRATIVE_NO_RISK)
    assert reasons == [], f"Expected [] for missing Risk section; got {reasons}"


# ── AC-2e: boilerplate phrase + specific anchor does not fire boilerplate ─────

def test_boilerplate_with_specific_anchor_does_not_fire():
    """Boilerplate phrase + ≥6 meaningful tokens: risk_boilerplate must NOT fire."""
    from bot import _find_risk_resolution_violations

    narrative = (
        "📋 <b>The Setup</b>\nContext.\n\n"
        "🎯 <b>The Edge</b>\nEdge.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "All things considered, Salah is doubtful and Liverpool front three lacks "
        "their usual creativity and drive without him on right flank.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Salah doubt already priced in — Liverpool have the depth to cover "
        "at 1.85 on Hollywoodbets, lean stake makes sense."
    )
    reasons = _find_risk_resolution_violations(narrative)
    assert "risk_boilerplate" not in reasons, (
        f"risk_boilerplate should not fire when Risk has specific fixture tokens; got {reasons}"
    )


# ── AC-2f: threshold constant is exactly 0.10 ────────────────────────────────

def test_threshold_constant_value():
    """_RISK_RESOLUTION_MIN_JACCARD must be exactly 0.10 (calibration starting point)."""
    from bot import _RISK_RESOLUTION_MIN_JACCARD

    assert _RISK_RESOLUTION_MIN_JACCARD == 0.10


# ── AC-2g: tokeniser drops stop words and HTML ───────────────────────────────

def test_tokenise_meaningful_drops_stop_words_and_html():
    """_tokenise_meaningful strips HTML and stop words, returns meaningful tokens."""
    from bot import _tokenise_meaningful

    tokens = _tokenise_meaningful("<b>injury</b> to <i>Saka</i> is a real concern")
    assert "injury" in tokens
    assert "concern" in tokens
    assert "real" in tokens
    assert "the" not in tokens
    assert "<b>" not in str(tokens)


# ── AC-3: _validate_polish gate 8c rejects generic Verdict vs specific Risk ──

def test_validate_polish_rejects_when_verdict_ignores_risk():
    """gate 8c: _validate_polish returns False when Verdict shares no tokens with Risk."""
    import bot
    from narrative_spec import NarrativeSpec

    spec = NarrativeSpec(
        home_name="Arsenal",
        away_name="Fulham",
        competition="Premier League",
        sport="soccer",
        home_story_type="momentum",
        away_story_type="anonymous",
        outcome="home",
        outcome_label="Arsenal home win",
        bookmaker="Hollywoodbets",
        odds=1.85,
        ev_pct=4.5,
        fair_prob_pct=58.0,
        composite_score=62.0,
        evidence_class="lean",
        tone_band="moderate",
        verdict_action="lean",
        verdict_sizing="small stake",
        edge_tier="gold",
    )

    # Verdict is generic — zero overlap with fixture-specific Risk
    polished = (
        "📋 <b>The Setup</b>\n"
        "Arsenal sit third in the Premier League, seven wins from their last nine "
        "fixtures. Fulham are solid in midtable, though inconsistent away from home.\n\n"
        "🎯 <b>The Edge</b>\n"
        "Hollywoodbets price Arsenal home at 1.85, with fair probability at 58%. "
        "That represents a genuine lean-tier expected value gap of 4.5%.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "The Saka injury is a real concern — Arsenal creative output drops noticeably "
        "when their Brazilian magician is absent from the left flank.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Lean with Hollywoodbets at 1.85 — small stake, numbers point toward "
        "the home side given current league position."
    )
    baseline = polished  # gate 9/11 need sizing/action in both or neither

    result = bot._validate_polish(polished, baseline, spec)
    assert result is False, (
        "_validate_polish should reject Verdict that shares no tokens with Risk"
    )


# ── AC-5: prompt contains VERDICT-CITES-RISK instruction ────────────────────

def test_edge_prompt_contains_verdict_cites_risk_instruction():
    """format_evidence_prompt() edge branch must contain VERDICT-CITES-RISK block."""
    from evidence_pack import EvidencePack, format_evidence_prompt
    from narrative_spec import NarrativeSpec

    pack = EvidencePack(
        match_key="arsenal_vs_fulham_2026-05-02",
        sport="soccer",
        league="Premier League",
        built_at="2026-04-25T10:00:00Z",
    )
    spec = NarrativeSpec(
        home_name="Arsenal",
        away_name="Fulham",
        competition="Premier League",
        sport="soccer",
        home_story_type="momentum",
        away_story_type="anonymous",
        bookmaker="Hollywoodbets",
        odds=1.85,
        tone_band="moderate",
        evidence_class="lean",
        verdict_action="lean",
        verdict_sizing="small stake",
    )

    prompt = format_evidence_prompt(pack, spec, match_preview=False)
    assert "VERDICT-CITES-RISK" in prompt, (
        "Edge prompt missing VERDICT-CITES-RISK instruction"
    )
    assert "discount the injury concern" in prompt.lower() or "resolving it" in prompt.lower(), (
        "VERDICT-CITES-RISK instruction missing resolve/hedge/price examples"
    )


def test_match_preview_prompt_contains_verdict_cites_risk_instruction():
    """format_evidence_prompt() match_preview branch must contain VERDICT-CITES-RISK block."""
    from evidence_pack import EvidencePack, format_evidence_prompt
    from narrative_spec import NarrativeSpec

    pack = EvidencePack(
        match_key="arsenal_vs_fulham_2026-05-02",
        sport="soccer",
        league="Premier League",
        built_at="2026-04-25T10:00:00Z",
    )
    spec = NarrativeSpec(
        home_name="Arsenal",
        away_name="Fulham",
        competition="Premier League",
        sport="soccer",
        home_story_type="momentum",
        away_story_type="anonymous",
        tone_band="moderate",
        evidence_class="lean",
    )

    prompt = format_evidence_prompt(pack, spec, match_preview=True)
    assert "VERDICT-CITES-RISK" in prompt, (
        "Match-preview prompt missing VERDICT-CITES-RISK instruction"
    )
