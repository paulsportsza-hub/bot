"""FIX-NARRATIVE-VOICE-COMPREHENSIVE-01 AC-3 — AI Breakdown voice contract.

Validates that the prompt builder injects the per-section ⛔ BRAAI VOICE BAD/
GOOD pairings into BOTH branches of `format_evidence_prompt` for The Setup,
The Edge, and The Risk sub-prompts; AND that 20 W82 baseline breakdowns
generated through `_render_baseline` produce zero telemetry-vocabulary hits
across all 3 prose sections (Setup + Edge + Risk) PLUS the Setup section
does not open with the ``<Manager>'s <Team> sit on N points`` mould (LB-7).

Why W82 baseline rather than live polish: deterministic, zero LLM cost.
The prompt-builder structural test validates that the BRAAI VOICE marker
reaches Sonnet at runtime; the W82 corpus test validates that the
deterministic templates themselves are clean by construction (so cards
that fail polish and serve W82 still pass the voice gate).
"""
from __future__ import annotations

import re

import pytest

from narrative_spec import NarrativeSpec, _render_baseline


# ── Telemetry catalogue (mirror of AC-1) ─────────────────────────────────────
_TELEMETRY_PATTERNS: tuple[str, ...] = (
    r"\bthe\s+(?:supporting\s+)?signals?\b",
    r"\bthe\s+reads?\b",
    r"\breads?\s+flag\b",
    r"\bbookmaker\s+(?:has\s+)?slipp(?:ed|ing|s)\b",
    r"\b(?:stays?|kept|keeps?|remains?|stay)\s+in\s+view\b",
    r"\bthe\s+case\s+(?:as\s+it\s+stands|here)\b",
    r"\b(?:the\s+)?model\s+(?:estimates|implies|prices?)\b",
    r"\bindicators?\s+(?:line\s+up|align)\b",
    r"\bstructural\s+(?:signal|lean|read)\b",
    r"\bprice\s+edge\b",
    r"\bsignal[-\s]aware\b",
    r"\bedge\s+confirms?\b",
)
_TELEMETRY_RE: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in _TELEMETRY_PATTERNS
)

# LB-7 manager-led mould detector. Examples:
#   "Slot's Reds sit on 58 points..."
#   "Arteta's Arsenal sit on 70 points..."
#   "Pereira's Forest sit on 32 points..."
_LB7_MOULD_RE = re.compile(
    r"\b\w+'s\s+\w+(?:\s+\w+)?\s+sit\s+on\s+\d+\s+points?\b",
    re.IGNORECASE,
)


def _has_telemetry_leak(text: str) -> bool:
    return any(p.search(text) for p in _TELEMETRY_RE)


def _has_lb7_mould(setup_text: str) -> bool:
    """Detect the ``<Manager>'s <Team> sit on N points`` boilerplate opening.

    LB-7 fix requires Setup to vary across 6 opening shapes. A hit indicates
    the manager-led mould has dominated.
    """
    # Look only at the first ~120 chars of the setup section — the opening shape.
    head = setup_text[:120]
    return bool(_LB7_MOULD_RE.search(head))


def _setup_block(narrative_html: str) -> str:
    """Slice the Setup section out of a full _render_baseline output."""
    setup_marker = "📋 <b>The Setup</b>"
    edge_marker = "🎯"
    setup_idx = narrative_html.find(setup_marker)
    if setup_idx == -1:
        return ""
    edge_idx = narrative_html.find(edge_marker, setup_idx + len(setup_marker))
    return narrative_html[setup_idx:edge_idx].strip() if edge_idx != -1 else narrative_html[setup_idx:]


def _edge_block(narrative_html: str) -> str:
    edge_marker = "🎯 <b>The Edge</b>"
    risk_marker = "⚠️"
    edge_idx = narrative_html.find(edge_marker)
    if edge_idx == -1:
        return ""
    risk_idx = narrative_html.find(risk_marker, edge_idx + len(edge_marker))
    return narrative_html[edge_idx:risk_idx].strip() if risk_idx != -1 else narrative_html[edge_idx:]


def _risk_block(narrative_html: str) -> str:
    risk_marker = "⚠️ <b>The Risk</b>"
    verdict_marker = "🏆"
    risk_idx = narrative_html.find(risk_marker)
    if risk_idx == -1:
        return ""
    v_idx = narrative_html.find(verdict_marker, risk_idx + len(risk_marker))
    return narrative_html[risk_idx:v_idx].strip() if v_idx != -1 else narrative_html[risk_idx:]


# ── Prompt structural tests ──────────────────────────────────────────────────


@pytest.fixture
def _evidence_pack():
    from evidence_pack import EvidencePack
    return EvidencePack(
        match_key="liverpool_vs_chelsea_2026-04-30",
        sport="soccer",
        league="EPL",
        built_at="2026-04-29T16:00:00+00:00",
        sources_total=10,
        sources_available=8,
        richness_score="HIGH",
    )


def _make_spec() -> NarrativeSpec:
    return NarrativeSpec(
        sport="soccer",
        competition="EPL",
        home_name="Liverpool",
        away_name="Chelsea",
        home_story_type="momentum",
        away_story_type="setback",
        outcome="home",
        outcome_label="Liverpool",
        odds=1.97,
        bookmaker="Supabets",
        ev_pct=5.2,
        fair_prob_pct=58.0,
        support_level=2,
        evidence_class="lean",
        tone_band="moderate",
        verdict_action="back",
        verdict_sizing="standard stake",
    )


def test_prompt_setup_voice_examples_present_match_preview(_evidence_pack):
    from evidence_pack import format_evidence_prompt

    pack = _evidence_pack
    spec = _make_spec()
    prompt = format_evidence_prompt(pack, spec, match_preview=True)
    # Brief AC-3 SETUP voice examples — verbatim BAD + GOOD.
    assert "SETUP VOICE EXAMPLES" in prompt
    assert "Slot's Reds sit on 58 points" in prompt  # BAD
    assert "Liverpool come into this on the back of three straight wins" in prompt  # GOOD


def test_prompt_setup_voice_examples_present_edge_branch(_evidence_pack):
    from evidence_pack import format_evidence_prompt

    pack = _evidence_pack
    spec = _make_spec()
    prompt = format_evidence_prompt(pack, spec, match_preview=False)
    assert "SETUP VOICE EXAMPLES" in prompt
    assert "Slot's Reds sit on 58 points" in prompt
    assert "Liverpool come into this on the back of three straight wins" in prompt


def test_prompt_edge_voice_examples_present_match_preview(_evidence_pack):
    from evidence_pack import format_evidence_prompt

    pack = _evidence_pack
    spec = _make_spec()
    prompt = format_evidence_prompt(pack, spec, match_preview=True)
    assert "EDGE VOICE EXAMPLES" in prompt
    assert "Market: 1.97 vs model implied 1.62" in prompt  # BAD
    assert "Supabets at 1.97 is the play" in prompt  # GOOD


def test_prompt_edge_voice_examples_present_edge_branch(_evidence_pack):
    from evidence_pack import format_evidence_prompt

    pack = _evidence_pack
    spec = _make_spec()
    prompt = format_evidence_prompt(pack, spec, match_preview=False)
    assert "EDGE VOICE EXAMPLES" in prompt
    assert "Supabets at 1.97 is the play" in prompt


def test_prompt_risk_voice_examples_present_match_preview(_evidence_pack):
    from evidence_pack import format_evidence_prompt

    pack = _evidence_pack
    spec = _make_spec()
    prompt = format_evidence_prompt(pack, spec, match_preview=True)
    assert "RISK VOICE EXAMPLES" in prompt
    # BAD: QA-01 LB-D1/D2 phrasing.
    assert "Price and signals are aligned" in prompt
    # GOOD: SA voice with specific risk type.
    assert "Big game energy is unpredictable" in prompt


def test_prompt_risk_voice_examples_present_edge_branch(_evidence_pack):
    from evidence_pack import format_evidence_prompt

    pack = _evidence_pack
    spec = _make_spec()
    prompt = format_evidence_prompt(pack, spec, match_preview=False)
    assert "RISK VOICE EXAMPLES" in prompt
    assert "Big game energy is unpredictable" in prompt


def test_voice_examples_sit_in_static_cache_prefix(_evidence_pack):
    """Rule 22 invariant: per-section voice examples must be in the cached
    static prefix (above the EVIDENCE PACK split sentinel)."""
    from evidence_pack import format_evidence_prompt

    pack = _evidence_pack
    spec = _make_spec()
    static, dynamic = format_evidence_prompt(
        pack, spec, match_preview=False, return_split=True
    )
    for marker in (
        "SETUP VOICE EXAMPLES",
        "EDGE VOICE EXAMPLES",
        "RISK VOICE EXAMPLES",
    ):
        assert marker in static, f"{marker} missing from static prefix"
        assert marker not in dynamic, f"{marker} leaked into dynamic block"


# ── W82 baseline corpus test (20 breakdowns) ─────────────────────────────────


def _generate_20_breakdowns() -> list[str]:
    """Generate 20 distinct W82 baseline breakdowns spanning all tier × sport
    combinations."""
    fixtures = [
        # Soccer
        ("liverpool", "chelsea", "EPL", "soccer", "diamond", "strong", "back",
         "premium stake", "Supabets", 1.97, 7.8, 4),
        ("manchester_city", "arsenal", "EPL", "soccer", "diamond", "strong",
         "strong back", "premium stake", "Hollywoodbets", 1.65, 12.0, 5),
        ("liverpool", "manchester_united", "EPL", "soccer", "gold", "confident",
         "back", "standard stake", "Supabets", 1.85, 5.8, 3),
        ("brighton", "wolves", "EPL", "soccer", "gold", "confident", "back",
         "standard stake", "Betway", 1.38, 6.1, 3),
        ("arsenal", "fulham", "EPL", "soccer", "gold", "confident", "back",
         "standard stake", "Hollywoodbets", 1.55, 5.5, 3),
        ("nottingham_forest", "newcastle", "EPL", "soccer", "gold", "confident",
         "back", "standard stake", "Supabets", 2.52, 4.8, 3),
        ("aston_villa", "everton", "EPL", "soccer", "silver", "moderate",
         "lean", "small-to-standard stake", "Betway", 1.78, 3.2, 2),
        ("crystal_palace", "fulham", "EPL", "soccer", "silver", "moderate",
         "lean", "small-to-standard stake", "Hollywoodbets", 2.50, 3.0, 2),
        ("kaizer_chiefs", "orlando_pirates", "PSL", "soccer", "diamond",
         "strong", "back with confidence", "premium stake", "Hollywoodbets",
         1.90, 9.1, 4),
        ("mamelodi_sundowns", "supersport_united", "PSL", "soccer", "gold",
         "confident", "back", "standard stake", "Hollywoodbets", 1.55, 5.5, 3),
        ("bournemouth", "sheffield_united", "EPL", "soccer", "bronze",
         "cautious", "monitor", "small-stake speculative", "Hollywoodbets",
         3.20, 1.5, 0),
        ("leicester", "leeds", "EPL", "soccer", "bronze", "cautious", "monitor",
         "small-stake speculative", "Betway", 2.95, 1.2, 0),
        # Rugby
        ("leinster", "munster", "URC", "rugby", "gold", "confident", "back",
         "standard stake", "Betway", 1.72, 4.5, 3),
        ("bulls", "stormers", "URC", "rugby", "gold", "confident", "back",
         "standard stake", "Hollywoodbets", 2.05, 5.1, 3),
        ("sharks", "lions", "URC", "rugby", "silver", "moderate", "lean",
         "small-to-standard stake", "Supabets", 1.85, 2.7, 2),
        ("wales", "italy", "Six Nations", "rugby", "bronze", "cautious",
         "monitor", "small-stake speculative", "Supabets", 3.50, 1.4, 0),
        # Cricket
        ("mumbai_indians", "chennai_super_kings", "IPL", "cricket", "gold",
         "confident", "back", "standard stake", "Supabets", 1.95, 5.0, 3),
        ("rajasthan_royals", "delhi_capitals", "IPL", "cricket", "silver",
         "moderate", "lean", "small-to-standard stake", "Hollywoodbets", 1.88,
         3.3, 2),
        ("punjab_kings", "kolkata_knight_riders", "IPL", "cricket", "bronze",
         "cautious", "monitor", "small-stake speculative", "Betway", 2.85, 1.5, 0),
        ("gujarat_titans", "lucknow_supergiants", "IPL", "cricket", "silver",
         "moderate", "lean", "small-to-standard stake", "Supabets", 2.05, 2.6, 2),
    ]
    breakdowns: list[str] = []
    for (
        home,
        away,
        comp,
        sport,
        tier,
        tone_band,
        verdict_action,
        verdict_sizing,
        bookmaker,
        odds,
        ev,
        confirming,
    ) in fixtures:
        spec = NarrativeSpec(
            sport=sport,
            competition=comp,
            home_name=home.replace("_", " ").title(),
            away_name=away.replace("_", " ").title(),
            home_story_type="momentum",
            away_story_type="setback",
            home_form="WWWLW",
            away_form="LLWLW",
            outcome="home",
            outcome_label=home.replace("_", " ").title(),
            odds=odds,
            bookmaker=bookmaker,
            ev_pct=ev,
            fair_prob_pct=55.0,
            support_level=confirming,
            contradicting_signals=0,
            evidence_class=(
                "conviction" if tier == "diamond"
                else "supported" if tier == "gold"
                else "lean" if tier == "silver"
                else "speculative"
            ),
            tone_band=tone_band,
            verdict_action=verdict_action,
            verdict_sizing=verdict_sizing,
            edge_tier=tier,
        )
        breakdowns.append(_render_baseline(spec))
    assert len(breakdowns) == 20
    return breakdowns


def test_breakdown_setup_section_zero_telemetry_leaks():
    """0/20 W82 Setup sections hit telemetry vocabulary regex."""
    breakdowns = _generate_20_breakdowns()
    leaks = []
    for i, b in enumerate(breakdowns):
        setup = _setup_block(b)
        if _has_telemetry_leak(setup):
            leaks.append((i, setup[:160]))
    assert leaks == [], (
        f"Telemetry leak in {len(leaks)}/20 Setup sections: {leaks[:3]}"
    )


def test_breakdown_edge_section_zero_telemetry_leaks():
    """0/20 W82 Edge sections hit telemetry vocabulary regex."""
    breakdowns = _generate_20_breakdowns()
    leaks = []
    for i, b in enumerate(breakdowns):
        edge = _edge_block(b)
        if _has_telemetry_leak(edge):
            leaks.append((i, edge[:160]))
    assert leaks == [], (
        f"Telemetry leak in {len(leaks)}/20 Edge sections: {leaks[:3]}"
    )


def test_breakdown_risk_section_zero_telemetry_leaks():
    """0/20 W82 Risk sections hit telemetry vocabulary regex."""
    breakdowns = _generate_20_breakdowns()
    leaks = []
    for i, b in enumerate(breakdowns):
        risk = _risk_block(b)
        if _has_telemetry_leak(risk):
            leaks.append((i, risk[:160]))
    assert leaks == [], (
        f"Telemetry leak in {len(leaks)}/20 Risk sections: {leaks[:3]}"
    )


def test_breakdown_setup_does_not_use_lb7_manager_mould():
    """0/20 W82 Setup sections open with <Manager>'s <Team> sit on N points (LB-7)."""
    breakdowns = _generate_20_breakdowns()
    moulds = []
    for i, b in enumerate(breakdowns):
        setup = _setup_block(b)
        if _has_lb7_mould(setup):
            moulds.append((i, setup[:160]))
    assert moulds == [], (
        f"LB-7 manager mould detected in {len(moulds)}/20 Setup openings: "
        f"{moulds[:3]}"
    )


def test_breakdown_full_corpus_zero_leaks_combined():
    """Belt-and-suspenders: scan the FULL breakdown body (Setup+Edge+Risk+
    Verdict) for telemetry leaks. 0/20 must hit any pattern."""
    breakdowns = _generate_20_breakdowns()
    leaks = [(i, b[:160]) for i, b in enumerate(breakdowns) if _has_telemetry_leak(b)]
    assert leaks == [], (
        f"Telemetry leak in {len(leaks)}/20 full breakdowns: {leaks[:3]}"
    )
