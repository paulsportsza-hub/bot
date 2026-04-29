"""FIX-VERDICT-CLOSURE-AND-BREAKDOWN-VISIBILITY-01 — AC-3 contract tests.

Breakdown visibility gate. Paul's directive (verbatim): "rather don't show AI
breakdown unless there's something worth a monthly subscription behind it
because breaking our image-only rule and showing this vague, generic crap is
honestly worse than the alternative."

Show "🤖 Full AI Breakdown" button ONLY WHEN ALL 5 conditions hold:
  1. narrative_source IN ('w84','w84-haiku-fallback')
  2. status IS NULL OR status NOT IN ('quarantined','deferred')
  3. Setup ≥ 200 chars + ≥ 3 named entities
  4. Edge ≥ 100 chars + ≥ 1 bookmaker name + ≥ 1 odds shape
  5. Risk ≥ 100 chars + ≥ 1 specific risk noun

Test surface: ≥12 tests covering visible scenarios + each invisible scenario
+ image-only-rule respected on hidden cases.
"""
from __future__ import annotations

from card_data import (
    compute_breakdown_visibility,
    compute_breakdown_visibility_reasons,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _quality_setup_html() -> str:
    """≥ 200 chars + ≥ 3 named entities (Liverpool, Chelsea, manager,
    + numeric '8 wins / 22 goals')."""
    return (
        "📋 <b>The Setup</b>\n\n"
        "Liverpool sit 2nd in the EPL with 8 wins from 12 matches at home "
        "this season. Slot's lot have scored 22 goals at Anfield. Chelsea "
        "have lost 5 on the bounce, taking only 1 win from their last 8 "
        "away. The form gap is real and the bookmaker pricing reflects it."
    )


def _quality_edge_html() -> str:
    """≥ 100 chars + bookmaker name + odds shape."""
    return (
        "🎯 <b>The Edge</b>\n\n"
        "Supabets has Liverpool at 1.97 vs our fair price 2.10 — a sharp 7% "
        "expected value gap that mirrors how the market has priced similar "
        "form differentials this season."
    )


def _quality_risk_html() -> str:
    """≥ 100 chars + specific risk noun ('rotation' / 'injury')."""
    return (
        "⚠️ <b>The Risk</b>\n\n"
        "Slot may rotate his starting eleven with the midweek cup tie three "
        "days after this fixture. Salah came off late last weekend with a "
        "minor knock — fitness flag is the meaningful injury risk to track."
    )


def _quality_verdict_html() -> str:
    return (
        "🏆 <b>Verdict</b>\n\n"
        "Slot's lot are flying. Get on Liverpool at 1.97 with Supabets."
    )


def _full_quality_narrative() -> str:
    return "\n".join(
        [
            _quality_setup_html(),
            _quality_edge_html(),
            _quality_risk_html(),
            _quality_verdict_html(),
        ]
    )


def _evidence_pack() -> dict:
    return {
        "home_team": "Liverpool",
        "away_team": "Chelsea",
        "coaches": ("Slot", "Maresca"),
    }


# ── 1. Visible (all conditions met) ──────────────────────────────────────────


def test_visible_full_polish_clean_quality_met():
    """w84 source + non-quarantined + all section quality → True."""
    row = {
        "narrative_html": _full_quality_narrative(),
        "narrative_source": "w84",
        "status": None,
    }
    assert compute_breakdown_visibility(row, _evidence_pack()) is True


def test_visible_haiku_fallback_clean_quality_met():
    """w84-haiku-fallback source counts as polish-quality."""
    row = {
        "narrative_html": _full_quality_narrative(),
        "narrative_source": "w84-haiku-fallback",
        "status": None,
    }
    assert compute_breakdown_visibility(row, _evidence_pack()) is True


def test_visible_status_empty_string_treated_as_null():
    """status = '' (empty string from COALESCE) is treated as null → no
    disqualification."""
    row = {
        "narrative_html": _full_quality_narrative(),
        "narrative_source": "w84",
        "status": "",
    }
    assert compute_breakdown_visibility(row, _evidence_pack()) is True


# ── 2. Invisible — narrative_source ──────────────────────────────────────────


def test_invisible_w82_baseline_hidden():
    """W82 baseline rows fail condition 1 → button hidden."""
    row = {
        "narrative_html": _full_quality_narrative(),
        "narrative_source": "w82",
        "status": None,
    }
    assert compute_breakdown_visibility(row, _evidence_pack()) is False
    reasons = compute_breakdown_visibility_reasons(row, _evidence_pack())
    assert any("not_polish" in r for r in reasons)


def test_invisible_baseline_no_edge_hidden():
    """baseline_no_edge source fails polish gate → button hidden."""
    row = {
        "narrative_html": _full_quality_narrative(),
        "narrative_source": "baseline_no_edge",
        "status": None,
    }
    assert compute_breakdown_visibility(row, _evidence_pack()) is False


# ── 3. Invisible — status ────────────────────────────────────────────────────


def test_invisible_quarantined_hidden():
    """status='quarantined' fails condition 2 → button hidden."""
    row = {
        "narrative_html": _full_quality_narrative(),
        "narrative_source": "w84",
        "status": "quarantined",
    }
    assert compute_breakdown_visibility(row, _evidence_pack()) is False


def test_invisible_deferred_hidden():
    """status='deferred' fails condition 2 → button hidden."""
    row = {
        "narrative_html": _full_quality_narrative(),
        "narrative_source": "w84",
        "status": "deferred",
    }
    assert compute_breakdown_visibility(row, _evidence_pack()) is False


# ── 4. Invisible — Setup quality ─────────────────────────────────────────────


def test_invisible_setup_too_short_hidden():
    """Setup < 200 chars fails condition 3 → button hidden."""
    short_setup = "📋 <b>The Setup</b>\n\nLiverpool vs Chelsea — short."
    row = {
        "narrative_html": "\n".join([
            short_setup, _quality_edge_html(),
            _quality_risk_html(), _quality_verdict_html(),
        ]),
        "narrative_source": "w84",
        "status": None,
    }
    assert compute_breakdown_visibility(row, _evidence_pack()) is False
    reasons = compute_breakdown_visibility_reasons(row, _evidence_pack())
    assert any("setup_len=" in r for r in reasons)


def test_invisible_setup_insufficient_entities_hidden():
    """Setup with < 3 named entities fails condition 3 → button hidden.

    Long Setup but with no team names, no manager surnames, no numeric
    entities → entity count = 0.
    """
    setup_no_entities = (
        "📋 <b>The Setup</b>\n\n"
        + ("This is a generic-prose preview that talks about pitch conditions "
           "and analytical posture without naming any specific information. " * 3)
    )
    row = {
        "narrative_html": "\n".join([
            setup_no_entities, _quality_edge_html(),
            _quality_risk_html(), _quality_verdict_html(),
        ]),
        "narrative_source": "w84",
        "status": None,
    }
    # No evidence_pack means team match is skipped; numeric and manager
    # checks should also produce 0 entities for this body.
    assert compute_breakdown_visibility(row, evidence_pack=None) is False


# ── 5. Invisible — Edge quality ──────────────────────────────────────────────


def test_invisible_edge_missing_bookmaker_hidden():
    """Edge ≥ 100 chars but no bookmaker name fails condition 4."""
    edge_no_bk = (
        "🎯 <b>The Edge</b>\n\n"
        "Our model implies 47.5% but the market price is 50% — the gap is "
        "small but real, and worth holding lightly given the model agreement."
    )
    row = {
        "narrative_html": "\n".join([
            _quality_setup_html(), edge_no_bk,
            _quality_risk_html(), _quality_verdict_html(),
        ]),
        "narrative_source": "w84",
        "status": None,
    }
    assert compute_breakdown_visibility(row, _evidence_pack()) is False
    reasons = compute_breakdown_visibility_reasons(row, _evidence_pack())
    assert any("edge_missing_bookmaker_name" in r for r in reasons)


def test_invisible_edge_too_short_hidden():
    """Edge < 100 chars fails condition 4."""
    edge_short = "🎯 <b>The Edge</b>\n\nSupabets at 1.97."
    row = {
        "narrative_html": "\n".join([
            _quality_setup_html(), edge_short,
            _quality_risk_html(), _quality_verdict_html(),
        ]),
        "narrative_source": "w84",
        "status": None,
    }
    assert compute_breakdown_visibility(row, _evidence_pack()) is False


def test_invisible_edge_missing_odds_hidden():
    """Edge with bookmaker name but no odds shape fails condition 4."""
    edge_no_odds = (
        "🎯 <b>The Edge</b>\n\n"
        "Supabets has them as the favourites and Hollywoodbets agree — the "
        "market consensus matches our model and the value is on the side "
        "with the form differential."
    )
    row = {
        "narrative_html": "\n".join([
            _quality_setup_html(), edge_no_odds,
            _quality_risk_html(), _quality_verdict_html(),
        ]),
        "narrative_source": "w84",
        "status": None,
    }
    assert compute_breakdown_visibility(row, _evidence_pack()) is False


# ── 6. Invisible — Risk quality ──────────────────────────────────────────────


def test_invisible_risk_missing_specific_risk_noun_hidden():
    """Risk ≥ 100 chars but no specific risk noun fails condition 5."""
    risk_generic = (
        "⚠️ <b>The Risk</b>\n\n"
        "There are general considerations to weigh on this market and the "
        "factors against the play are typical for fixtures of this type, "
        "without anything specific to flag."
    )
    row = {
        "narrative_html": "\n".join([
            _quality_setup_html(), _quality_edge_html(),
            risk_generic, _quality_verdict_html(),
        ]),
        "narrative_source": "w84",
        "status": None,
    }
    assert compute_breakdown_visibility(row, _evidence_pack()) is False
    reasons = compute_breakdown_visibility_reasons(row, _evidence_pack())
    assert any("risk_missing_specific_risk_noun" in r for r in reasons)


def test_invisible_risk_too_short_hidden():
    """Risk < 100 chars fails condition 5."""
    risk_short = "⚠️ <b>The Risk</b>\n\nInjury concern only."
    row = {
        "narrative_html": "\n".join([
            _quality_setup_html(), _quality_edge_html(),
            risk_short, _quality_verdict_html(),
        ]),
        "narrative_source": "w84",
        "status": None,
    }
    assert compute_breakdown_visibility(row, _evidence_pack()) is False


# ── 7. Defensive ─────────────────────────────────────────────────────────────


def test_invisible_none_row_returns_false():
    """None row → False (defensive)."""
    assert compute_breakdown_visibility(None, _evidence_pack()) is False


def test_invisible_empty_narrative_html_hidden():
    """Empty narrative_html → False."""
    row = {
        "narrative_html": "",
        "narrative_source": "w84",
        "status": None,
    }
    assert compute_breakdown_visibility(row, _evidence_pack()) is False


def test_image_only_rule_respected_when_hidden():
    """When the gate hides the button, no markup is generated for it.

    This is a contract assertion: compute_breakdown_visibility returns False
    deterministically for invisible cases, so the bot.py keyboard builder
    will skip the breakdown button entirely. The card surface still includes
    image + verdict + Back button — never breaks the image-only rule.
    """
    invisible_cases = [
        # W82 baseline
        {"narrative_html": _full_quality_narrative(), "narrative_source": "w82", "status": None},
        # Quarantined
        {"narrative_html": _full_quality_narrative(), "narrative_source": "w84", "status": "quarantined"},
        # Empty narrative
        {"narrative_html": "", "narrative_source": "w84", "status": None},
    ]
    for row in invisible_cases:
        assert compute_breakdown_visibility(row, _evidence_pack()) is False
