"""FIX-VERDICT-PROMPT-ANCHORS-AND-VALIDATOR-SCOPE-01 (2026-05-01) — AC-2.

The polish path is verdict-only (no Setup/Edge/Risk sections written). The
validator stack drops the long-form gates that targeted narrative_html and
keeps the verdict-only gates. A later closure-rule loosening accepts
imperatives, gerunds, declaratives, and action prepositions when the close also
has the selection/team and odds.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ensure_scrapers_importable

ensure_scrapers_importable()


# 9-imperative cluster from AC-1 verdict-spec.
_NINE_IMPERATIVES_VERBS = (
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

# Declarative shapes accepted after FIX-VERDICT-CLOSURE-RULE-LOOSEN-AND-GERUND-ACCEPT-01.
_DECLARATIVE_ACCEPTS = (
    "is the pick",
    "is the play",
    "is the call",
    "is the lean",
    "is the bet",
    "is the value",
)


def _baseline_pack():
    return {
        "home_team": "Liverpool",
        "away_team": "Chelsea",
        "match_id": "liverpool_vs_chelsea_2026-05-04",
        "venue": "Anfield",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — Dropped gates do not fire when narrative_html is empty.
# ─────────────────────────────────────────────────────────────────────────────


def test_dropped_gates_no_op_on_empty_narrative_html():
    """Empty narrative_html → no failures attributed to Gates 1/2a/2b/3 (long-
    form)/4/11. Verdict-only gates may still fire on verdict_html."""
    from narrative_validator import _validate_narrative_for_persistence

    res = _validate_narrative_for_persistence(
        content={
            "narrative_html": "",
            "verdict_html": "Get on Liverpool at 1.97 with Supabets.",
            "match_id": "liverpool_vs_chelsea_2026-05-04",
            "narrative_source": "w84",
        },
        evidence_pack=_baseline_pack(),
        edge_tier="gold",
        source_label="w84",
    )
    dropped_gates = {
        "venue_leak",  # narrative_html scope (we only check below for verdict surface)
        "setup_pricing",
        "setup_pricing_semantic",
        "claim_h2h_fabricated",
        "claim_evidence_mismatch",
    }
    fired_drop_gates = {
        f.gate
        for f in res.failures
        if f.gate in dropped_gates and f.section == "all"
    }
    assert fired_drop_gates == set(), (
        f"dropped long-form gates fired on empty narrative_html: {fired_drop_gates}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — Setup-pricing gate dropped (long-form scope only).
# ─────────────────────────────────────────────────────────────────────────────


def test_setup_pricing_gate_no_longer_fires():
    """Even if a (no-longer-written) narrative_html had pricing leaks in Setup,
    the validator no longer flags `setup_pricing` — the gate was removed."""
    from narrative_validator import _validate_narrative_for_persistence

    leaking_setup = (
        "📋 <b>The Setup</b>\nLiverpool are implied 78% to win at Hollywoodbets 1.45. "
        "Strong favourites at this fair value, expected value gap.\n"
        "🎯 <b>The Edge</b>\nx\n⚠️ <b>The Risk</b>\nx\n🏆 <b>Verdict</b>\nx"
    )
    res = _validate_narrative_for_persistence(
        content={
            "narrative_html": leaking_setup,
            "verdict_html": "Back Liverpool at 1.97 with Supabets.",
            "match_id": "liverpool_vs_chelsea_2026-05-04",
            "narrative_source": "w84",
        },
        evidence_pack=_baseline_pack(),
        edge_tier="gold",
        source_label="w84",
    )
    fired = {f.gate for f in res.failures}
    assert "setup_pricing" not in fired
    assert "setup_pricing_semantic" not in fired


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — Vague-content gate dropped.
# ─────────────────────────────────────────────────────────────────────────────


def test_vague_content_gate_no_longer_fires():
    """The vague_content scan was scoped to long-form sections; dropped here."""
    from narrative_validator import _validate_narrative_for_persistence

    vague_narrative = (
        "📋 <b>The Setup</b>\nLooks like the sort of fixture that takes shape "
        "once one side settles into its preferred tempo.\n"
        "🎯 <b>The Edge</b>\nThe play is live without being loud.\n"
        "⚠️ <b>The Risk</b>\nReads clean here. The model and standard match "
        "volatility are the only live variables.\n"
        "🏆 <b>Verdict</b>\nStandard play."
    )
    res = _validate_narrative_for_persistence(
        content={
            "narrative_html": vague_narrative,
            "verdict_html": "Get on Liverpool at 1.97 with Supabets.",
            "match_id": "liverpool_vs_chelsea_2026-05-04",
            "narrative_source": "w84",
        },
        evidence_pack=_baseline_pack(),
        edge_tier="gold",
        source_label="w84",
    )
    fired = {f.gate for f in res.failures}
    assert "vague_content" not in fired


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — Verdict venue gate fires on verdict_html (kept).
# ─────────────────────────────────────────────────────────────────────────────


def test_verdict_venue_gate_fires_on_unverified_venue():
    """Cross-fixture venue invention in verdict_html is CRITICAL."""
    from narrative_validator import _validate_narrative_for_persistence

    # pack.venue = Anfield. Verdict cites Stamford Bridge — leak.
    res = _validate_narrative_for_persistence(
        content={
            "narrative_html": "",
            "verdict_html": (
                "Slot's Reds at Stamford Bridge with Salah on form — "
                "Get on Liverpool at 1.97 with Supabets."
            ),
            "match_id": "liverpool_vs_chelsea_2026-05-04",
            "narrative_source": "w84",
        },
        evidence_pack=_baseline_pack(),
        edge_tier="gold",
        source_label="w84",
    )
    fired = {f.gate for f in res.failures}
    assert "venue_leak" in fired, (
        f"venue_leak should fire on verdict cross-fixture venue invention; "
        f"got failures={[(f.gate, f.section) for f in res.failures]}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — Closure rule ACCEPTS declarative phrases on Diamond/Gold.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("declarative", _DECLARATIVE_ACCEPTS)
def test_verdict_closure_rule_accepts_declarative_on_premium(declarative: str):
    """`is the pick`, `is the play`, etc. satisfy on Diamond/Gold."""
    from narrative_validator import _check_verdict_closure_rule

    text = (
        f"Slot's Reds at home in front of Anfield against a Chelsea side leaking on the road. "
        f"Liverpool {declarative} at 1.97 with Supabets."
    )
    severity, _reason = _check_verdict_closure_rule(text, "gold", _baseline_pack())
    assert severity is None, (
        f"declarative '{declarative}' should pass on Gold — got {severity!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — Closure rule ACCEPTS all 9 imperatives on Diamond/Gold.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("imperative", _NINE_IMPERATIVES_VERBS)
def test_verdict_closure_rule_accepts_all_9_imperatives(imperative: str):
    """All 9 brief imperatives MUST satisfy the action-verb gate on Gold."""
    from narrative_validator import _check_verdict_closure_rule

    text = (
        f"Slot's Reds at home in front of Anfield, "
        f"Chelsea bringing nothing on the road — "
        f"{imperative} Liverpool at 1.97 with Supabets."
    )
    severity, reason = _check_verdict_closure_rule(text, "gold", _baseline_pack())
    assert severity is None, (
        f"imperative '{imperative}' should pass on Gold — "
        f"got severity={severity!r} reason={reason!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 7 — _VERDICT_ACTION_RE pattern includes accepted closure shapes.
# ─────────────────────────────────────────────────────────────────────────────


def test_verdict_action_re_accepts_current_closure_shapes():
    """The regex source carries imperatives, gerunds, and declaratives."""
    from narrative_validator import _VERDICT_ACTION_RE

    pattern_text = _VERDICT_ACTION_RE.pattern
    # Imperatives present.
    for verb in (
        "back",
        "bet\\s+on",
        "put\\s+your\\s+money\\s+on",
        "get\\s+(?:on|behind)",
        "take",
        "lean\\s+on",
        "ride",
        "hammer\\s+it\\s+on",
        "smash",
    ):
        assert verb in pattern_text, f"imperative '{verb}' missing from regex"
    assert "backing" in pattern_text
    assert "worth\\s+taking" in pattern_text
    assert "is\\s+the" in pattern_text
    assert "worth\\s+(?:a\\s+)?" in pattern_text


# ─────────────────────────────────────────────────────────────────────────────
# Test 8 — Verdict-only telemetry-vocab gate fires; narrative_html scope dropped.
# ─────────────────────────────────────────────────────────────────────────────


def test_verdict_telemetry_gate_fires_only_on_verdict_html():
    """Rule 17 telemetry leak in verdict_html → CRITICAL on Gold.
    Same leak in narrative_html does NOT add a duplicate failure entry
    (narrative_html scope was dropped)."""
    from narrative_validator import _validate_narrative_for_persistence

    leaky_verdict = (
        "Slot's Reds at home — the supporting signals back the read. "
        "Get on Liverpool at 1.97 with Supabets."
    )
    leaky_narrative = (
        "📋 <b>The Setup</b>\nthe supporting signals back the read.\n"
        "🎯 <b>The Edge</b>\nx\n⚠️ <b>The Risk</b>\nx\n🏆 <b>Verdict</b>\nx"
    )
    res = _validate_narrative_for_persistence(
        content={
            "narrative_html": leaky_narrative,
            "verdict_html": leaky_verdict,
            "match_id": "liverpool_vs_chelsea_2026-05-04",
            "narrative_source": "w84",
        },
        evidence_pack=_baseline_pack(),
        edge_tier="gold",
        source_label="w84",
    )
    telemetry_failures = [
        f for f in res.failures if f.gate == "telemetry_vocabulary"
    ]
    # Verdict_html scope fires; narrative_html scope no longer in the gate stack.
    sections = {f.section for f in telemetry_failures}
    assert "verdict_html" in sections, (
        "telemetry_vocabulary on verdict_html should fire; "
        f"failures={[(f.gate, f.section) for f in res.failures]}"
    )
    assert "narrative_html" not in sections, (
        "narrative_html scope was dropped; should not produce a separate "
        f"telemetry_vocabulary failure entry: {sections}"
    )
