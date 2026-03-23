"""Tests for BASELINE-FIX-R3: Verdict Retry Loop + Brighton Ref + Konaté Encoding.

Verifies:
  1. Evidence pack prompt contains explicit bookmaker+price constraint
  2. Brighton accepted as standalone team reference
  3. Accented player names (Konaté) properly normalised in matching
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.expanduser("~"))  # For `from scrapers.*` imports


# ── Part A: Verdict Bookmaker Constraint in Prompt ──


def test_evidence_prompt_has_explicit_bookmaker_constraint():
    """format_evidence_prompt() must tell Claude exactly which bookmaker+price to use."""
    from evidence_pack import format_evidence_prompt, EvidencePack
    from narrative_spec import NarrativeSpec

    spec = NarrativeSpec(
        home_name="Chelsea", away_name="Manchester United",
        competition="Premier League", sport="soccer",
        home_story_type="momentum", away_story_type="crisis",
        home_coach="Enzo Maresca", away_coach="Ruben Amorim",
        home_position=4, away_position=13,
        home_points=50, away_points=35,
        home_form="WWDWL", away_form="LLDWL",
        home_record="W9 D3 L2", away_record="W5 D4 L5",
        home_gpg=1.8, away_gpg=1.2,
        home_last_result="beat Burnley 2-0",
        away_last_result="lost to Newcastle 0-1",
        h2h_summary="6 meetings: Chelsea 3W 1D 2L",
        bookmaker="World Sports Betting", odds=3.65,
        ev_pct=5.0, fair_prob_pct=30.0, composite_score=62.0,
        support_level=2, contradicting_signals=0,
        evidence_class="supported", tone_band="confident",
        risk_factors=["Standard variance applies."],
        risk_severity="moderate",
        verdict_action="back", verdict_sizing="standard stake",
        outcome="home", outcome_label="the Chelsea win",
    )
    pack = EvidencePack(
        match_key="chelsea_vs_manchester_united_2026-03-23",
        sport="soccer", league="epl",
        built_at="2026-03-23T12:00:00Z",
        richness_score="medium", sources_available=5, sources_total=7,
    )
    prompt = format_evidence_prompt(pack, spec)
    # Must contain explicit bookmaker+price instruction
    assert "World Sports Betting" in prompt
    assert "3.65" in prompt
    assert "NON-NEGOTIABLE" in prompt


def test_evidence_prompt_bookmaker_varies_by_spec():
    """The bookmaker constraint should reflect spec.bookmaker, not be hardcoded."""
    from evidence_pack import format_evidence_prompt, EvidencePack
    from narrative_spec import NarrativeSpec

    spec = NarrativeSpec(
        home_name="Arsenal", away_name="Bournemouth",
        competition="Premier League", sport="soccer",
        home_story_type="momentum", away_story_type="neutral",
        home_coach="Mikel Arteta", away_coach="Andoni Iraola",
        home_position=2, away_position=12,
        home_points=61, away_points=39,
        home_form="WWWDL", away_form="LDWLW",
        home_record="W9 D3 L2", away_record="W4 D4 L6",
        home_gpg=2.1, away_gpg=1.1,
        home_last_result="beat Newcastle 2-1",
        away_last_result="drew 1-1 with Brentford",
        h2h_summary="6 meetings: Arsenal 4W 1D 1L",
        bookmaker="Hollywoodbets", odds=1.48,
        ev_pct=3.0, fair_prob_pct=55.0, composite_score=58.0,
        support_level=2, contradicting_signals=0,
        evidence_class="supported", tone_band="confident",
        risk_factors=["Standard variance applies."],
        risk_severity="moderate",
        verdict_action="back", verdict_sizing="standard stake",
        outcome="home", outcome_label="the Arsenal win",
    )
    pack = EvidencePack(
        match_key="arsenal_vs_bournemouth_2026-03-23",
        sport="soccer", league="epl",
        built_at="2026-03-23T12:00:00Z",
        richness_score="medium", sources_available=5, sources_total=7,
    )
    prompt = format_evidence_prompt(pack, spec)
    assert "Hollywoodbets" in prompt
    assert "1.48" in prompt


# ── Part B: Brighton Accepted Reference ──


def test_brighton_standalone_accepted():
    """'Brighton' must be accepted as a team reference for Brighton & Hove Albion."""
    from evidence_pack import _team_reference_variants

    variants = _team_reference_variants("Brighton and Hove Albion")
    assert "brighton" in variants, f"'brighton' not in variants: {variants}"


def test_brighton_full_name_accepted():
    """Full name should also be in variants."""
    from evidence_pack import _team_reference_variants

    variants = _team_reference_variants("Brighton and Hove Albion")
    assert "brighton and hove albion" in variants


def test_albion_still_accepted():
    """'albion' should still be accepted as a variant."""
    from evidence_pack import _team_reference_variants

    variants = _team_reference_variants("Brighton and Hove Albion")
    assert "albion" in variants


def test_first_token_for_multi_word_names():
    """First significant token added for multi-word team names."""
    from evidence_pack import _team_reference_variants

    # Nottingham Forest → "nottingham" should be a variant
    variants = _team_reference_variants("Nottingham Forest")
    assert "nottingham" in variants

    # Crystal Palace → "crystal" should be a variant
    variants = _team_reference_variants("Crystal Palace")
    assert "crystal" in variants


def test_short_first_token_not_added():
    """First tokens shorter than 4 chars should NOT be added."""
    from evidence_pack import _team_reference_variants

    # "AC Milan" → "ac" is only 2 chars, should not be added as standalone
    variants = _team_reference_variants("AC Milan")
    assert "ac" not in variants
    # But "milan" should be (last token ≥4 chars)
    assert "milan" in variants


def test_suffix_token_not_added_as_first():
    """First tokens that are suffix words (fc, united) should not be standalone refs."""
    from evidence_pack import _team_reference_variants

    # Edge case: "FC Barcelona" → "fc" should not be standalone
    variants = _team_reference_variants("FC Barcelona")
    assert "fc" not in variants


# ── Part C: Konaté Encoding ──


def test_konate_accent_normalised():
    """'Konaté' must tokenise to ['konate'], not ['konat']."""
    from evidence_pack import _name_word_tokens

    tokens = _name_word_tokens("Konaté")
    assert tokens == ["konate"], f"Expected ['konate'], got {tokens}"


def test_accented_full_name():
    """Full accented name should normalise all accents."""
    from evidence_pack import _name_word_tokens

    tokens = _name_word_tokens("Ibrahima Konaté")
    assert tokens == ["ibrahima", "konate"]


def test_umlaut_normalised():
    """German umlauts should be normalised (ü→u, ö→o)."""
    from evidence_pack import _name_word_tokens

    tokens = _name_word_tokens("Müller")
    assert tokens == ["muller"]


def test_cedilla_normalised():
    """Cedilla should be normalised (ç→c)."""
    from evidence_pack import _name_word_tokens

    tokens = _name_word_tokens("Gonçalves")
    assert tokens == ["goncalves"]


def test_plain_ascii_unchanged():
    """Plain ASCII names should tokenise as before."""
    from evidence_pack import _name_word_tokens

    tokens = _name_word_tokens("Mohamed Salah")
    assert tokens == ["mohamed", "salah"]


def test_match_verified_name_konate():
    """_match_verified_name should match 'Konaté' against verified set containing 'konate'."""
    from evidence_pack import _match_verified_name

    verified = {"konate", "ibrahima konate"}
    assert _match_verified_name("Konaté", verified, unique_surnames={"konate"}) is True


def test_compact_name_phrase_accent():
    """_compact_name_phrase should strip accents for comparison."""
    from evidence_pack import _compact_name_phrase

    assert _compact_name_phrase("Konaté") == "konate"
    assert _compact_name_phrase("Ibrahima Konaté") == "ibrahima konate"
