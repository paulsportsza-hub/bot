from __future__ import annotations

import pytest
pytest.skip(
    "FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: Sonnet/Haiku polish ripped out. "
    "This test asserts polish-chain behaviour that no longer exists.",
    allow_module_level=True,
)

"""FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01 (2026-05-01) — AC-1.

The verdict polish prompt MUST carry the 4 mandatory anchors (HOME NICKNAME,
AWAY NICKNAME, VENUE, HOME/AWAY COACH) + the 9-imperative action close + 3
GOOD examples + 3 BAD examples in the STATIC cache prefix (above the
EVIDENCE PACK split sentinel) so Rule 22 prompt-cache discipline holds.

Both branches (edge + match-preview) carry the same block.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ensure_scrapers_importable

ensure_scrapers_importable()


_GOOD_EXAMPLE_1 = "Slot's Reds at home in front of Anfield"
_GOOD_EXAMPLE_2 = "Guardiola's Sky Blues at the Etihad against a Brentford side"
_GOOD_EXAMPLE_3 = "Pereira's Forest at the City Ground"

_BAD_EXAMPLE_1 = "The data has a cleaner read on X"
_BAD_EXAMPLE_2 = "X at Y with Z is the lean"
_BAD_EXAMPLE_3 = "Standard stake on X. Back X."

_NINE_IMPERATIVES = (
    "Back",
    "Bet on",
    "Put your money on",
    "Get on",
    "Take",
    "Lean on",
    "Ride",
    "Hammer it on",
    "Smash",
)

_SPLIT_SENTINEL = "───────────── EVIDENCE PACK ─────────────"


def _minimal_pack(sport: str = "soccer", league: str = "Premier League"):
    from evidence_pack import EvidencePack
    return EvidencePack(
        match_key="liverpool_vs_chelsea_2026-05-04",
        sport=sport,
        league=league,
        built_at="2026-05-01T10:00:00Z",
    )


def _minimal_spec(home: str = "Liverpool", away: str = "Chelsea"):
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
        bookmaker="supabets",
        odds=1.97,
        ev_pct=4.5,
        fair_prob_pct=58.0,
        composite_score=72.0,
        evidence_class="supported",
        tone_band="confident",
        verdict_action="back",
        verdict_sizing="standard stake",
        edge_tier="gold",
    )


def _render(match_preview: bool):
    from evidence_pack import format_evidence_prompt
    static, dynamic = format_evidence_prompt(
        _minimal_pack(), _minimal_spec(), match_preview=match_preview, return_split=True
    )
    return static, dynamic


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — Braai voice header opens the static block.
# ─────────────────────────────────────────────────────────────────────────────


def test_static_block_contains_braai_voice_header():
    static_edge, _ = _render(match_preview=False)
    static_preview, _ = _render(match_preview=True)
    assert "⛔ BRAAI VOICE — NOT QUANT VOICE." in static_edge
    assert "⛔ BRAAI VOICE — NOT QUANT VOICE." in static_preview


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — All 4 mandatory anchor labels present in static prefix.
# ─────────────────────────────────────────────────────────────────────────────


def test_static_block_contains_4_anchor_labels():
    static_edge, _ = _render(match_preview=False)
    for label in (
        "HOME NICKNAME",
        "AWAY NICKNAME",
        "VENUE",
        "HOME COACH",
        "AWAY COACH",
        "ODDS",
    ):
        assert label in static_edge, (
            f"static block missing anchor label '{label}' (edge branch)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — All 9 imperative action verbs listed in the action-close cluster.
# ─────────────────────────────────────────────────────────────────────────────


def test_static_block_contains_9_imperatives():
    static_edge, _ = _render(match_preview=False)
    for imperative in _NINE_IMPERATIVES:
        assert imperative in static_edge, (
            f"static block missing imperative '{imperative}'"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Test 4-6 — 3 GOOD examples present verbatim.
# ─────────────────────────────────────────────────────────────────────────────


def test_static_block_contains_good_example_1_verbatim():
    static_edge, _ = _render(match_preview=False)
    assert _GOOD_EXAMPLE_1 in static_edge, (
        "static block missing GOOD example 1 (Slot/Anfield)"
    )


def test_static_block_contains_good_example_2_verbatim():
    static_edge, _ = _render(match_preview=False)
    assert _GOOD_EXAMPLE_2 in static_edge, (
        "static block missing GOOD example 2 (Guardiola/Etihad)"
    )


def test_static_block_contains_good_example_3_verbatim():
    static_edge, _ = _render(match_preview=False)
    assert _GOOD_EXAMPLE_3 in static_edge, (
        "static block missing GOOD example 3 (Pereira/Forest)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 7-9 — 3 BAD examples present verbatim.
# ─────────────────────────────────────────────────────────────────────────────


def test_static_block_contains_bad_example_1_verbatim():
    static_edge, _ = _render(match_preview=False)
    assert _BAD_EXAMPLE_1 in static_edge, (
        "static block missing BAD example 1 (data has a cleaner read)"
    )


def test_static_block_contains_bad_example_2_verbatim():
    static_edge, _ = _render(match_preview=False)
    assert _BAD_EXAMPLE_2 in static_edge, (
        "static block missing BAD example 2 (is the lean)"
    )


def test_static_block_contains_bad_example_3_verbatim():
    static_edge, _ = _render(match_preview=False)
    assert _BAD_EXAMPLE_3 in static_edge, (
        "static block missing BAD example 3 (Standard stake)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 10 — Anchor block sits ABOVE the EVIDENCE PACK split sentinel
#           (cache invariant per Rule 22).
# ─────────────────────────────────────────────────────────────────────────────


def test_anchor_block_sits_above_split_sentinel():
    """Verify the anchor block lives in the cached static prefix, not below."""
    from evidence_pack import format_evidence_prompt
    full_prompt = format_evidence_prompt(
        _minimal_pack(), _minimal_spec(), match_preview=False
    )
    assert isinstance(full_prompt, str)
    # Anchor instructions in static prefix.
    anchor_idx = full_prompt.find("MANDATORY ANCHORS")
    split_idx = full_prompt.find(_SPLIT_SENTINEL)
    assert anchor_idx != -1, "MANDATORY ANCHORS block not present in prompt"
    assert split_idx != -1, "EVIDENCE PACK split sentinel not present in prompt"
    assert anchor_idx < split_idx, (
        f"Anchor block (idx={anchor_idx}) must sit ABOVE EVIDENCE PACK split "
        f"(idx={split_idx}) per Rule 22 cache discipline"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 11 — Edge branch (match_preview=False) carries the anchor block.
# ─────────────────────────────────────────────────────────────────────────────


def test_edge_branch_carries_anchor_block():
    static_edge, _ = _render(match_preview=False)
    assert "MANDATORY ANCHORS" in static_edge
    assert "CLOSE WITH ACTION" in static_edge
    assert "HOME NICKNAME" in static_edge
    assert _GOOD_EXAMPLE_1 in static_edge


# ─────────────────────────────────────────────────────────────────────────────
# Test 12 — Match-preview branch (match_preview=True) carries the anchor block.
# ─────────────────────────────────────────────────────────────────────────────


def test_match_preview_branch_carries_anchor_block():
    static_preview, _ = _render(match_preview=True)
    assert "MANDATORY ANCHORS" in static_preview
    assert "CLOSE WITH ACTION" in static_preview
    assert "HOME NICKNAME" in static_preview
    assert _GOOD_EXAMPLE_1 in static_preview


# ─────────────────────────────────────────────────────────────────────────────
# Bonus — Dynamic block carries per-match HOME / AWAY NICKNAME values.
# (Not part of the brief 12 tests but sanity-checks the AC-1 wiring.)
# ─────────────────────────────────────────────────────────────────────────────


def test_dynamic_block_carries_home_nickname_value():
    """Liverpool → 'the Reds' from data/team_nicknames.json."""
    _, dynamic_edge = _render(match_preview=False)
    assert "HOME NICKNAME: the Reds" in dynamic_edge


def test_dynamic_block_carries_away_nickname_value():
    """Chelsea → 'the Blues' from data/team_nicknames.json."""
    _, dynamic_edge = _render(match_preview=False)
    assert "AWAY NICKNAME: the Blues" in dynamic_edge


def test_dynamic_block_falls_back_to_unknown_for_missing_nickname():
    """Unknown team → '(unknown)' sentinel matching static-block instruction."""
    from evidence_pack import EvidencePack, format_evidence_prompt
    from narrative_spec import NarrativeSpec
    pack = EvidencePack(
        match_key="random_team_a_vs_random_team_b_2026-05-04",
        sport="soccer",
        league="Whatever League",
        built_at="2026-05-01T10:00:00Z",
    )
    spec = NarrativeSpec(
        home_name="Random Team A",
        away_name="Random Team B",
        competition="Whatever League",
        sport="soccer",
        home_story_type="neutral",
        away_story_type="neutral",
        outcome="home",
        outcome_label="Random Team A",
        bookmaker="supabets",
        odds=1.97,
        ev_pct=4.5,
        fair_prob_pct=58.0,
        composite_score=62.0,
        evidence_class="lean",
        tone_band="moderate",
        verdict_action="lean",
        verdict_sizing="small stake",
        edge_tier="silver",
    )
    _, dynamic = format_evidence_prompt(pack, spec, return_split=True)
    assert "HOME NICKNAME: (unknown)" in dynamic
    assert "AWAY NICKNAME: (unknown)" in dynamic
