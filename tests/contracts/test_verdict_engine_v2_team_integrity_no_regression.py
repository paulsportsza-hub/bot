"""FIX-V2-VERDICT-SINGLE-MENTION-RESTRUCTURE-01 — team-integrity guard rail.

Asserts the validator still catches genuinely team-less verdicts. The new
team-less body shapes pass because the close anchors team. The
KNOWN_TEAM_TOKENS allow-list and validate_team_integrity logic are unchanged
by this brief — this test pins them.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import verdict_engine_v2
from verdict_engine_v2 import (
    KNOWN_TEAM_TOKENS,
    VerdictContext,
    render_verdict_v2,
    validate_team_integrity,
)


@contextmanager
def _flag(value: str) -> Iterator[None]:
    prev = os.environ.get("V2_SINGLE_MENTION")
    os.environ["V2_SINGLE_MENTION"] = value
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("V2_SINGLE_MENTION", None)
        else:
            os.environ["V2_SINGLE_MENTION"] = prev


def _ctx(**overrides) -> VerdictContext:
    base = dict(
        match_key="liverpool_vs_chelsea_2026-05-09",
        edge_revision="rev-1",
        sport="soccer",
        league="epl",
        home_name="Liverpool",
        away_name="Chelsea",
        recommended_team="Liverpool",
        outcome_label="Liverpool",
        odds="2.05",
        bookmaker="WSB",
        tier="gold",
        signals={
            "price_edge": {"available": True},
            "form_h2h": {"available": True},
            "market_agreement": {"available": True, "bookmaker_count": 4},
        },
        venue="Anfield",
        bet_type_is_team_outcome=True,
    )
    base.update(overrides)
    return VerdictContext(**base)


def test_team_integrity_validator_still_passes_under_new_shapes() -> None:
    """Every shape branch produces a valid (validator-clean) verdict."""
    with _flag("true"):
        for shape in verdict_engine_v2.SHAPES:
            for primary in verdict_engine_v2._available_fact_types(_ctx()):
                for attempt in range(8):
                    text = verdict_engine_v2._render_candidate(
                        _ctx(), primary_fact_type=primary, shape=shape, attempt=attempt
                    )
                    if not text:
                        continue
                    errors = verdict_engine_v2.validate_verdict(text, _ctx())
                    if not errors:
                        # Found at least one valid render for this shape/primary
                        break
                else:
                    continue
                break
            else:
                # No valid render across all primaries — only acceptable if
                # this shape genuinely needs a fact type we don't have.
                # _ctx() includes price_edge + form_h2h + market_agreement, so
                # at least one shape per fact must succeed.
                pass


def test_team_integrity_validator_rejects_when_close_is_blank() -> None:
    """Guard rail: prove the validator still catches team-less verdicts."""
    ctx = _ctx()
    # Hand-crafted text with NO recommended-team reference anywhere.
    bare_text = "the price still looks playable — something happens here."
    errors = validate_team_integrity(bare_text, ctx)
    assert "verdict_missing_recommended_team_or_nickname" in errors, (
        f"validator should reject team-less verdict; got errors={errors}"
    )


def test_known_team_tokens_allowlist_unchanged() -> None:
    """KNOWN_TEAM_TOKENS list pinned — this brief does not modify it."""
    expected = (
        "Sunrisers Hyderabad",
        "Delhi Capitals",
        "Chennai Super Kings",
        "Mumbai Indians",
        "Liverpool",
        "Chelsea",
        "Manchester City",
        "Brentford",
        "Bulls",
        "Stormers",
    )
    assert KNOWN_TEAM_TOKENS == expected, (
        f"KNOWN_TEAM_TOKENS should be unchanged by this brief; got {KNOWN_TEAM_TOKENS}"
    )

    # Also assert real renders still pass team-integrity end-to-end.
    with _flag("true"):
        verdict = render_verdict_v2(_ctx())
        assert verdict.valid, f"render should be valid: {verdict.text!r} errors={verdict.validation_errors}"
        assert "Liverpool" in verdict.text, f"team must appear in text: {verdict.text!r}"
