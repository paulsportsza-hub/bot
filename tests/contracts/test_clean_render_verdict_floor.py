"""BUILD-NARRATIVE-WATERTIGHT-01 D.2 — CLEAN-RENDER verdict quality floor.

Every one of the 12 variants produced by ``edge_detail_renderer._section_verdict``
must satisfy ``narrative_spec.min_verdict_quality`` on its extracted verdict
text across all 4 edge tiers (diamond/gold/silver/bronze) with representative
signal-count and EV combinations.

The three legs of the gate that historically failed this path are:
1. Character floor per tier (bronze 100, silver 120, gold 140, diamond 160) —
   pre-W84-WATERTIGHT output was 42–65 chars on the speculative path.
2. Terminal punctuation — every variant must end in . ! ? or …
3. Banned trivial templates — must not match any entry in
   ``BANNED_TRIVIAL_VERDICT_TEMPLATES``.

This test forces every branch of _section_verdict at least once by varying
``confirming_signals`` and ``predicted_ev``, and verifies the extracted
verdict passes ``min_verdict_quality`` at the tier that would be served.
"""
from __future__ import annotations

import pytest


def _make_edge_data(confirming_signals: int, predicted_ev: float, tier: str):
    """Build a minimal EdgeDetailData fixture using real field names."""
    from edge_detail_renderer import EdgeDetailData

    fair = (1.0 + predicted_ev / 100.0) / 2.10 * 100.0
    return EdgeDetailData(
        match_key=(
            f"home_team_vs_away_team_2026-04-24_"
            f"{confirming_signals}_{predicted_ev}_{tier}"
        ),
        home="Home Team",
        away="Away Team",
        sport="soccer",
        league="epl",
        league_display="Premier League",
        edge_tier=tier,
        composite_score=55.0,
        outcome="home",
        outcome_display="Home Team",
        recommended_odds=2.10,
        bookmaker="Betway",
        bookmaker_key="betway",
        predicted_ev=predicted_ev,
        confirming_signals=confirming_signals,
        fair_prob_pct=fair,
        model_only=(confirming_signals == 0),
        context=None,
        mep_met=False,
        match_date="2026-04-24",
        user_tier="diamond",
        access_level="full",
    )


@pytest.mark.parametrize(
    "confirming_signals,predicted_ev",
    [
        (0, 2.0),   # speculative path, low EV
        (0, 6.5),   # speculative path, mid EV
        (1, 4.0),   # lean path
        (1, 7.0),   # lean path, higher EV
        (2, 5.5),   # supported/confident fallback
        (2, 9.0),   # supported/confident, higher EV
        (3, 8.5),   # conviction path, minimum 3-signal ≥8%
        (4, 12.0),  # conviction path, clear
    ],
)
@pytest.mark.parametrize("tier", ["bronze", "silver", "gold", "diamond"])
def test_section_verdict_passes_min_verdict_quality(confirming_signals, predicted_ev, tier):
    from edge_detail_renderer import _section_verdict
    from narrative_spec import _extract_verdict_text, min_verdict_quality

    data = _make_edge_data(confirming_signals, predicted_ev, tier)
    rendered = _section_verdict(data)
    extracted = _extract_verdict_text(rendered)
    assert extracted, (
        f"_section_verdict produced no extractable verdict text "
        f"(tier={tier}, sigs={confirming_signals}, ev={predicted_ev}): {rendered!r}"
    )
    assert min_verdict_quality(extracted, tier=tier, evidence_pack=None), (
        f"BUILD-NARRATIVE-WATERTIGHT-01 D.2: _section_verdict failed min_verdict_quality "
        f"(tier={tier}, signals={confirming_signals}, ev={predicted_ev}, "
        f"len={len(extracted)}): {extracted!r}"
    )
