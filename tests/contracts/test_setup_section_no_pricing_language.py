"""FIX-PREMIUM-POSTWRITE-PROTECTION-01 — AC-1.

The Setup-section prompt MUST tighten the pricing-language ban so Sonnet polish
output does not get DELETEd by the cache-read absolute-ban detector
(_find_stale_setup_patterns at bot.py:16405) on the next read.

Predecessor brief (FIX-W84-PREMIUM-MANDATORY-COVERAGE-01) shipped premium-tier
horizon bypass + Sonnet→Haiku→defer chain — but a downstream gate (the cache-read
detector) was deleting valid w84 polish output AFTER it landed. Liverpool–Chelsea
12:14 commit → 12:27 cache miss is the canonical evidence.

Root cause: the Setup-section prompt invited the LLM to pivot to pricing
vocabulary in low-evidence fixtures by burying the STRICT BAN line under a list
of positive instructions ("pivot to: ratings / tipster / news / injury"). Sonnet
pattern-completed by adding "implied X% probability at HWB Y.YY" — exactly what
the detector then deleted.

This test asserts the prompt has been tightened to:
- Lead with the prohibition (⛔ SETUP IS A PRICE-FREE ZONE)
- State explicitly: no integer probabilities, no decimal probabilities
- Anchor with a BAD example and a GOOD example
- Apply to BOTH branches (edge polish + match_preview)

Live verification (post-deploy): pregen sweep targeting current orphans
(Liverpool–Chelsea + others) for 30 minutes; expect zero ACCURACY-01:
setup_validated=0 events for premium tier, zero _find_stale_setup_patterns
matches, zero post-commit DELETEs.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ensure_scrapers_importable

ensure_scrapers_importable()

# FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01 (2026-05-01) — AC-1
# strips the Setup/Edge/Risk section instructions entirely. The polish path
# is verdict-only; the Setup-section pricing-language ban tests below now
# target dropped behaviour. Setup-pricing leakage is no longer a possible
# failure mode of this prompt.
pytestmark = pytest.mark.skip(
    reason=(
        "FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01 (2026-05-01) — AC-1: "
        "polish prompt is verdict-only; Setup section instructions stripped "
        "and the matching validator gate dropped (AC-2). Section-pricing "
        "leakage is no longer reachable by this prompt path."
    )
)


def _minimal_pack(sport: str = "soccer", league: str = "Premier League"):
    """Build a minimal EvidencePack for prompt-rendering."""
    from evidence_pack import EvidencePack

    return EvidencePack(
        match_key="liverpool_vs_chelsea_2026-05-09",
        sport=sport,
        league=league,
        built_at="2026-04-29T10:00:00Z",
    )


def _minimal_spec(home: str = "Liverpool", away: str = "Chelsea"):
    """Build a minimal NarrativeSpec — just what format_evidence_prompt reads."""
    from narrative_spec import NarrativeSpec

    return NarrativeSpec(
        home_name=home,
        away_name=away,
        competition="Premier League",
        sport="soccer",
        home_story_type="momentum",
        away_story_type="anonymous",
        outcome="home",
        outcome_label=f"{home} home win",
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


def _setup_block(prompt) -> str:
    """Extract just the Setup-section instruction span from the prompt.

    `format_evidence_prompt` returns either a str or (static, dynamic) tuple
    depending on `return_split`. This helper accepts both shapes — when given a
    tuple, it scans the static prefix (where the Setup-section instructions
    live per Rule 22).
    """
    if isinstance(prompt, tuple):
        prompt = prompt[0]
    assert isinstance(prompt, str), f"Expected str, got {type(prompt).__name__}"
    setup_idx = prompt.find("📋 <b>The Setup</b>")
    edge_idx = prompt.find("🎯 <b>The Edge</b>")
    assert setup_idx != -1 and edge_idx != -1, "Setup/Edge section markers missing"
    return prompt[setup_idx:edge_idx]


# ─────────────────────────────────────────────────────────────────────────────
# AC-1 — Tightened Setup-section prompt structure (BOTH branches)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("match_preview", [False, True], ids=["edge", "match_preview"])
def test_setup_leads_with_price_free_zone_marker(match_preview: bool):
    """The Setup section MUST lead the prohibition with a clear marker —
    burying it after positive instructions is what let Sonnet leak pricing
    language into the cache (predecessor brief residual)."""
    from evidence_pack import format_evidence_prompt

    prompt = format_evidence_prompt(
        _minimal_pack(), _minimal_spec(), match_preview=match_preview
    )
    setup_block = _setup_block(prompt)

    assert "⛔ SETUP IS A PRICE-FREE ZONE" in setup_block, (
        "Setup-section prompt must lead with the ⛔ SETUP IS A PRICE-FREE ZONE "
        "marker so the prohibition reads BEFORE the positive instructions, "
        "not after them. (FIX-PREMIUM-POSTWRITE-PROTECTION-01 AC-1)"
    )


@pytest.mark.parametrize("match_preview", [False, True], ids=["edge", "match_preview"])
def test_setup_explicitly_bans_integer_probabilities(match_preview: bool):
    """Explicit ban on integer probability cites — the leak shape that bypassed
    the cache-read decimal+price-context check (the FIX-02 gap)."""
    from evidence_pack import format_evidence_prompt

    prompt = format_evidence_prompt(
        _minimal_pack(), _minimal_spec(), match_preview=match_preview
    )
    setup_block = _setup_block(prompt)

    assert "No integer probability cites" in setup_block, (
        "Setup-section prompt must explicitly ban integer probability cites "
        "(e.g. '30% probability') — the leak shape that bypassed the cache-read "
        "decimal+price-context detector pre-FIX-02."
    )


@pytest.mark.parametrize("match_preview", [False, True], ids=["edge", "match_preview"])
def test_setup_explicitly_bans_decimal_probabilities(match_preview: bool):
    """Explicit ban on decimal probability cites — anchors the prohibition
    against the specific shape '0.85' that the detector flags as decimal+price."""
    from evidence_pack import format_evidence_prompt

    prompt = format_evidence_prompt(
        _minimal_pack(), _minimal_spec(), match_preview=match_preview
    )
    setup_block = _setup_block(prompt)

    assert "No decimal probability cites" in setup_block, (
        "Setup-section prompt must explicitly ban decimal probability cites "
        "(e.g. '0.85') — the most common detector trigger."
    )


@pytest.mark.parametrize("match_preview", [False, True], ids=["edge", "match_preview"])
def test_setup_carries_bad_example(match_preview: bool):
    """A concrete BAD example anchors the prohibition — without it the LLM
    may interpret abstract bans more loosely. The BAD example uses the
    Hollywoodbets/integer-probability/odds combination that triggers the gate."""
    from evidence_pack import format_evidence_prompt

    prompt = format_evidence_prompt(
        _minimal_pack(), _minimal_spec(), match_preview=match_preview
    )
    setup_block = _setup_block(prompt)

    assert "BAD:" in setup_block, "Setup-section must include a BAD example"
    assert "implied 78%" in setup_block, (
        "BAD example must demonstrate integer-probability leak (the FIX-02 gap)"
    )
    assert "Hollywoodbets" in setup_block, (
        "BAD example must demonstrate bookmaker-name leak"
    )
    assert "REJECTED" in setup_block, (
        "BAD example must label the violation as REJECTED so the model "
        "absorbs the consequence"
    )


@pytest.mark.parametrize("match_preview", [False, True], ids=["edge", "match_preview"])
def test_setup_carries_good_example(match_preview: bool):
    """A GOOD example anchors the positive shape — form + standings only,
    zero pricing/probability vocabulary."""
    from evidence_pack import format_evidence_prompt

    prompt = format_evidence_prompt(
        _minimal_pack(), _minimal_spec(), match_preview=match_preview
    )
    setup_block = _setup_block(prompt)

    assert "GOOD:" in setup_block, "Setup-section must include a GOOD example"
    assert "five-match winning run" in setup_block, (
        "GOOD example must demonstrate form-based prose"
    )
    assert "70 points" in setup_block, (
        "GOOD example must demonstrate standings-based prose (raw points cite "
        "is allowed because it has no price-cue context word)"
    )


@pytest.mark.parametrize("match_preview", [False, True], ids=["edge", "match_preview"])
def test_setup_keeps_strict_ban_token_list(match_preview: bool):
    """The 11 banned tokens locked in Rule 8 / FIX-PREGEN-SETUP-PRICING-LEAK-01
    must remain enumerated in the prompt — do NOT loosen detector intent."""
    from evidence_pack import format_evidence_prompt

    prompt = format_evidence_prompt(
        _minimal_pack(), _minimal_spec(), match_preview=match_preview
    )
    setup_block = _setup_block(prompt)

    for token in (
        "bookmaker", "odds", "price", "priced", "implied",
        "implied probability", "implied chance", "fair probability",
        "fair value", "expected value", "model reads",
    ):
        assert token in setup_block, (
            f"banned token '{token}' missing from Setup-section prompt — "
            f"do NOT loosen the locked Rule 8 ban list"
        )


@pytest.mark.parametrize("match_preview", [False, True], ids=["edge", "match_preview"])
def test_setup_pivot_clause_routes_pricing_to_edge(match_preview: bool):
    """The 'Do NOT pivot to odds structure' clause must explicitly route
    pricing/odds/line-movement language to The Edge — closes the rationalisation
    path the LLM uses when ESPN data is thin."""
    from evidence_pack import format_evidence_prompt

    prompt = format_evidence_prompt(
        _minimal_pack(), _minimal_spec(), match_preview=match_preview
    )
    setup_block = _setup_block(prompt)

    assert "Do NOT pivot to odds structure or line movements in The Setup" in setup_block, (
        "Pivot-to-odds clause must remain present"
    )
    assert "that is The Edge's job" in setup_block, (
        "Pivot clause must route pricing-language to The Edge — don't just "
        "ban it from Setup, redirect it"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC-1 — Detector intent preservation (regression guard for Rule 8)
# ─────────────────────────────────────────────────────────────────────────────


def test_cache_read_detector_intact():
    """Rule 8 says do NOT loosen `_find_stale_setup_patterns` — confirm the
    detector is still wired and the absolute-ban regex still fires on the
    canonical FIX-02 leak shape (the predecessor brief's reproduction case)."""
    import bot

    # Canonical leak shape Sonnet emits when ESPN data is thin and the
    # Setup-section prompt's prohibition didn't bite (the failure mode the
    # AC-1 prompt-tightening closes).
    polished = (
        "📋 <b>The Setup</b>\n"
        "Liverpool sit second on 70 points after a five-match winning run. "
        "Chelsea are mid-table and have struggled away from home. The Elo-implied "
        "home win probability is 78% and the bookmaker has Liverpool at 1.45.\n\n"
        "🎯 <b>The Edge</b>\n"
        "E.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "R.\n\n"
        "🏆 <b>Verdict</b>\n"
        "V."
    )
    reasons = bot._find_stale_setup_patterns(polished)
    assert reasons, (
        "Rule 8 detector must still fire on the canonical leak shape — "
        "if this assertion fails, the absolute-ban regex was loosened"
    )
    assert any("setup" in r for r in reasons), (
        f"Detector reasons must include a Setup-section flag; got {reasons!r}"
    )


def test_polish_time_strict_ban_enforcer_intact():
    """The polish-time strict-ban enforcer (gate 8a) must still reject the
    canonical leak shape — defence-in-depth alongside the cache-read detector."""
    import bot

    polished = (
        "📋 <b>The Setup</b>\n"
        "Liverpool sit second on 70 points after a five-match winning run. "
        "Chelsea are mid-table and have struggled away from home. The Elo-implied "
        "home win probability is 78% and the bookmaker has Liverpool at 1.45.\n\n"
        "🎯 <b>The Edge</b>\n"
        "E.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "R.\n\n"
        "🏆 <b>Verdict</b>\n"
        "V."
    )
    reasons = bot._find_setup_strict_ban_violations(polished)
    assert reasons, (
        "Rule 8 polish-time strict-ban enforcer must still fire on the canonical "
        "leak shape — if this fails, the helper was loosened"
    )
    # Specifically: integer-probability + banned-token + decimal-probability
    # all three branches should fire on this fixture.
    reason_kinds = {r.split(":", 1)[0] for r in reasons}
    assert "integer_probability" in reason_kinds, (
        f"integer_probability branch missing from {reasons!r}"
    )
    assert "banned_token" in reason_kinds, (
        f"banned_token branch missing from {reasons!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC-1 — Token-budget guardrail (Rule 22 — locked cache prefix threshold)
# ─────────────────────────────────────────────────────────────────────────────


def test_setup_tightening_keeps_static_prefix_above_sonnet_minimum():
    """The Setup-section tightening adds ~12 lines of prompt content above the
    EVIDENCE PACK split sentinel. Rule 22 (FIX-PREGEN-STATIC-PREFIX-PURE-01)
    locked the static prefix at >= 1024 tokens (Sonnet model minimum). The
    tightening MUST still clear that floor — adding content moves us away from
    the floor in the right direction.

    Structural test (no API call): assert the new prohibition block lives in
    the static prefix (above EVIDENCE PACK), not in the per-match dynamic block.
    """
    from evidence_pack import format_evidence_prompt

    prompt = format_evidence_prompt(
        _minimal_pack(), _minimal_spec(), match_preview=False, return_split=True,
    )
    # When return_split=True, format_evidence_prompt returns (static, dynamic).
    assert isinstance(prompt, tuple) and len(prompt) == 2, (
        f"return_split=True must return (static, dynamic); got {type(prompt).__name__}"
    )
    static_prefix, dynamic_suffix = prompt

    assert "⛔ SETUP IS A PRICE-FREE ZONE" in static_prefix, (
        "AC-1 tightening must live in the STATIC prefix (above EVIDENCE PACK "
        "split) so it benefits from cache_control. If it lands in dynamic, "
        "every match call writes a fresh cache entry — Rule 22 violation."
    )
    assert "⛔ SETUP IS A PRICE-FREE ZONE" not in dynamic_suffix, (
        "AC-1 tightening must NOT appear in the DYNAMIC suffix — the "
        "prohibition is per-prompt static content, not per-match interpolation."
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
