"""FIX-D1-VERDICT-BLACKLIST-01 + FIX-NARRATIVE-META-MARKERS-01 — Serve-time verdict cache gate contract.

Verifies that all _LLM_META_MARKERS from narrative_spec are present in
_VERDICT_BLACKLIST in bot.py and that the serve-time cache gate rejects stale
rendered verdicts containing those markers (case-insensitive).

16 rejection cases (one per meta-marker) + 2 pass-through cases.
Original 10 markers: tier-validation error replies.
6 new markers (FIX-NARRATIVE-META-MARKERS-01): LLM refusals + data-absence meta-commentary.

Regression guard: if any test fails, a meta-marker has been dropped from
_VERDICT_BLACKLIST or the gate logic has been changed.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from narrative_spec import _LLM_META_MARKERS
from bot import _VERDICT_BLACKLIST


def _gate_rejects(text: str) -> bool:
    """Mirror of the bot.py:8496 serve-time cache gate check."""
    return bool(_VERDICT_BLACKLIST and any(p in text.lower() for p in _VERDICT_BLACKLIST))


# ── Rejection tests: one per meta-marker ──────────────────────────────────────

def test_marker_i_notice_rejected():
    assert _gate_rejects("I notice that the confidence tier is unusual.")


def test_marker_i_understand_rejected():
    assert _gate_rejects("I understand this is not one of the valid tiers.")


def test_marker_confidence_tier_rejected():
    assert _gate_rejects("The confidence_tier supplied is SELECTIVE.")


def test_marker_selective_rejected():
    assert _gate_rejects("SELECTIVE is not a valid tier in the system.")


def test_marker_not_one_of_rejected():
    assert _gate_rejects("That value is not one of the accepted options.")


def test_marker_isnt_one_of_rejected():
    assert _gate_rejects("SELECTIVE isn't one of the four valid tiers.")


def test_marker_valid_tiers_rejected():
    assert _gate_rejects("The valid tiers are MILD, SOLID, STRONG, MAX.")


def test_marker_four_valid_rejected():
    assert _gate_rejects("There are four valid tiers available.")


def test_marker_valid_options_rejected():
    assert _gate_rejects("Please choose from the valid options listed.")


def test_marker_i_apologize_rejected():
    assert _gate_rejects("I apologize, but SELECTIVE is not a valid tier.")


# ── FIX-NARRATIVE-META-MARKERS-01: 6 new markers ─────────────────────────────

def test_marker_i_cannot_rejected():
    assert _gate_rejects("I cannot produce a valid verdict for this match because the tier is missing.")


def test_marker_i_cant_produce_rejected():
    assert _gate_rejects("I can't produce a verdict for this match — the confidence tier is invalid.")


def test_marker_no_form_h2h_rejected():
    assert _gate_rejects("Also, no form, H2H, manager, or signals data was provided, so this is speculative.")


def test_marker_no_form_data_h2h_rejected():
    assert _gate_rejects("Also, no form data, H2H summary, manager names, or signals were provided.")


def test_marker_no_manager_names_rejected():
    assert _gate_rejects("Note: No manager names, form data, or H2H summary were provided for this match.")


def test_marker_also_noting_rejected():
    assert _gate_rejects("Also noting: no manager names, no form data, no H2H summary were included.")


# ── Pass-through tests: clean verdicts must not be rejected ───────────────────

def test_clean_verdict_passes_through():
    assert not _gate_rejects(
        "Back Mamelodi Sundowns — strong signal, size normally."
    )


def test_clean_verdict_with_odds_passes_through():
    assert not _gate_rejects(
        "Lean Arsenal. The price gap between Betway (2.10) and our model (58%) justifies a measured stake."
    )


# ── Structural: all markers are in _VERDICT_BLACKLIST ────────────────────────

def test_all_llm_meta_markers_in_blacklist():
    """Every entry in _LLM_META_MARKERS must appear in _VERDICT_BLACKLIST."""
    missing = [m for m in _LLM_META_MARKERS if m not in _VERDICT_BLACKLIST]
    assert not missing, f"Meta-markers missing from _VERDICT_BLACKLIST: {missing}"


def test_blacklist_marker_count():
    """_VERDICT_BLACKLIST must contain all _LLM_META_MARKERS (currently 16)."""
    present = [m for m in _LLM_META_MARKERS if m in _VERDICT_BLACKLIST]
    assert len(present) == len(_LLM_META_MARKERS), (
        f"Expected {len(_LLM_META_MARKERS)} markers, found {len(present)}"
    )
