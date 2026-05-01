from __future__ import annotations

import pytest
pytest.skip(
    "FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: Sonnet/Haiku polish ripped out. "
    "This test asserts polish-chain behaviour that no longer exists.",
    allow_module_level=True,
)

"""FIX-NARRATIVE-TIER-BAND-TONE-LOCK-01 — AC-2 contract tests.

Superseded by FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01 (2026-05-01)
AC-1: the polish prompt now produces verdict-only output and the legacy
multi-section TONE LOCK block was stripped along with the Setup/Edge/Risk
instructions. Strong-band tone enforcement moved to validator Gate 9 on
verdict_html only — see tests/contracts/test_strong_band_tone_lock.py.

Brief: FIX-NARRATIVE-TIER-BAND-TONE-LOCK-01 (29 April 2026)
"""

import pytest

pytestmark = pytest.mark.skip(
    reason=(
        "FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01 (2026-05-01) — AC-1: "
        "polish prompt is verdict-only; legacy TONE LOCK section block stripped. "
        "Strong-band scan stays in validator Gate 9 (verdict_html only) — "
        "see test_strong_band_tone_lock.py for the live coverage."
    )
)

from evidence_pack import EvidencePack, format_evidence_prompt
from narrative_spec import NarrativeSpec


@pytest.fixture
def _pack() -> EvidencePack:
    return EvidencePack(
        match_key="manchester_city_vs_brentford_2026-04-29",
        sport="soccer",
        league="EPL",
        built_at="2026-04-29T16:00:00+00:00",
        sources_total=10,
        sources_available=8,
        richness_score="HIGH",
    )


def _gold_spec() -> NarrativeSpec:
    return NarrativeSpec(
        sport="soccer",
        competition="EPL",
        home_name="Manchester City",
        away_name="Brentford",
        home_story_type="momentum",
        away_story_type="setback",
        home_form="WWWWL",
        away_form="LLLLW",
        outcome="home",
        outcome_label="Manchester City",
        odds=1.36,
        bookmaker="Supabets",
        ev_pct=4.5,
        fair_prob_pct=78.0,
        support_level=2,
        contradicting_signals=0,
        evidence_class="lean",
        tone_band="moderate",
        verdict_action="back",
        verdict_sizing="standard stake",
        edge_tier="gold",
    )


def test_tone_lock_block_present_match_preview_branch(_pack):
    """Brief AC-2.1: TONE LOCK block injects into match_preview branch."""
    spec = _gold_spec()
    prompt = format_evidence_prompt(_pack, spec, match_preview=True)
    assert isinstance(prompt, str)
    # Brief AC-2 block opener.
    assert "⚠️ STRONG-BAND TIER (Diamond / Gold) — TONE LOCK" in prompt
    # Brief AC-2 reframe instruction (verbatim — locked phrase).
    assert (
        "IF the underlying signal is MILD, reframe it as MEASURED "
        "confidence — NOT cautious withdrawal" in prompt
    )


def test_tone_lock_block_present_edge_branch(_pack):
    """Brief AC-2.2: TONE LOCK block injects into edge branch."""
    spec = _gold_spec()
    prompt = format_evidence_prompt(_pack, spec, match_preview=False)
    assert isinstance(prompt, str)
    assert "⚠️ STRONG-BAND TIER (Diamond / Gold) — TONE LOCK" in prompt
    assert (
        "IF the underlying signal is MILD, reframe it as MEASURED "
        "confidence — NOT cautious withdrawal" in prompt
    )


def test_tone_lock_sits_above_evidence_pack_split(_pack):
    """Rule 22 invariant: TONE LOCK marker must sit in the STATIC (cached) prefix.

    `format_evidence_prompt(return_split=True)` returns ``(static, dynamic)``
    where the cache_control directive applies only to the static block. The
    TONE LOCK block must sit in static — otherwise the prompt-cache hit
    rate degrades and the marker no longer appears in cached prefixes.
    """
    spec = _gold_spec()
    static_p, dynamic_p = format_evidence_prompt(
        _pack, spec, match_preview=True, return_split=True
    )
    assert "⚠️ STRONG-BAND TIER (Diamond / Gold) — TONE LOCK" in static_p
    assert "⚠️ STRONG-BAND TIER (Diamond / Gold) — TONE LOCK" not in dynamic_p
    static_e, dynamic_e = format_evidence_prompt(
        _pack, spec, match_preview=False, return_split=True
    )
    assert "⚠️ STRONG-BAND TIER (Diamond / Gold) — TONE LOCK" in static_e
    assert "⚠️ STRONG-BAND TIER (Diamond / Gold) — TONE LOCK" not in dynamic_e


def test_banned_list_complete(_pack):
    """Brief AC-2: BANNED list lives in the prompt verbatim — every Strong-band
    cautious-band trigger word appears so Sonnet sees the explicit reject set."""
    spec = _gold_spec()
    prompt = format_evidence_prompt(_pack, spec, match_preview=False)
    # Cautious framing
    assert '"cautious"' in prompt
    assert '"cautious lean"' in prompt
    assert '"cautious play"' in prompt
    # Limited edge
    assert '"limited edge"' in prompt
    assert '"thin edge"' in prompt
    assert '"no edge to work with"' in prompt
    # Evidence-poor hedging
    assert '"form picture is unclear"' in prompt
    assert '"data is thin"' in prompt
    assert '"without recent form"' in prompt
    # Hedging closer
    assert '"rather than a confident call"' in prompt
    # Bronze-only register
    assert '"speculative punt" (Bronze-only)' in prompt
    # Hedging conjunction openers
    assert "hedging openers" in prompt
    assert "\"but\"" in prompt
    assert "\"however\"" in prompt
    assert "\"though\"" in prompt


def test_good_and_bad_examples_present_verbatim(_pack):
    """Brief AC-2: GOOD/BAD examples present in the prompt verbatim.

    Sonnet calibrates from the examples, not the rule statement — the GOOD
    and BAD blocks are essential prompt structure per the brief.
    """
    spec = _gold_spec()
    prompt = format_evidence_prompt(_pack, spec, match_preview=False)
    # GOOD example — Strong-band MILD-confidence reframe
    assert "GOOD Strong-band MILD-confidence example:" in prompt
    assert "Back City at 1.36 with Supabets — form solid, line slightly soft" in prompt
    assert "Measured stake at this number, no need to push" in prompt
    # BAD example — verbatim reproduction of Paul's live failure case
    assert "BAD Strong-band example (cautious-band collapse):" in prompt
    assert "City are the pick at 1.36, but the form picture is unclear" in prompt
    assert "cautious lean rather than a confident call" in prompt
    # ALLOWED reframes — at least 3 of the 5 listed must be present verbatim
    allowed_phrases = [
        "Measured back at this number",
        "Worth a measured stake",
        "Solid lean",
        "Disciplined back",
        "Worth getting in early",
    ]
    present = [p for p in allowed_phrases if p in prompt]
    assert len(present) >= 4, (
        f"Expected ≥4/5 ALLOWED reframes verbatim; found {present!r}"
    )
