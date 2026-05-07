"""FIX-V2-VERDICT-NICKNAME-COACH-BODY-AND-VENUE-DROP-01 — venue removal contract.

Asserts venue / stadium tokens never surface in V2 body output, that the
fact_type rotation no longer surfaces 'venue_reference', and that the
deprecated render branch survives as a one-line revert (kept for safe
rollback per Phase 4).
"""
from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

import verdict_engine_v2
from verdict_engine_v2 import (
    FACT_PRIORITY,
    VerdictContext,
    _available_fact_types,
    render_verdict_v2,
)


VENUE_TOKENS = (
    # Generic markers
    "Stadium",
    "Park",
    "Bowl",
    # EPL famous grounds
    "Old Trafford",
    "Etihad",
    "Anfield",
    "Stamford Bridge",
    "Emirates",
    "St James' Park",
    # Foreign clubs
    "Camp Nou",
    "Bernabéu",
    "Bernabeu",
    "Wembley",
    # SA marker (city suffix the dump pattern produced)
    "Bloemfontein",
    "Soweto",
)


@contextmanager
def _flags(*, single: str = "true", body_ref: str = "true") -> Iterator[None]:
    prev_single = os.environ.get("V2_SINGLE_MENTION")
    prev_body = os.environ.get("V2_BODY_REFERENCE")
    os.environ["V2_SINGLE_MENTION"] = single
    os.environ["V2_BODY_REFERENCE"] = body_ref
    try:
        yield
    finally:
        if prev_single is None:
            os.environ.pop("V2_SINGLE_MENTION", None)
        else:
            os.environ["V2_SINGLE_MENTION"] = prev_single
        if prev_body is None:
            os.environ.pop("V2_BODY_REFERENCE", None)
        else:
            os.environ["V2_BODY_REFERENCE"] = prev_body


def _ctx(**overrides) -> VerdictContext:
    base = dict(
        match_key="manchester_city_vs_brentford_2026-05-09",
        edge_revision="rev-1",
        sport="soccer",
        league="epl",
        home_name="Manchester City",
        away_name="Brentford",
        recommended_team="Manchester City",
        outcome_label="Manchester City",
        odds="1.39",
        bookmaker="Supabets",
        tier="gold",
        signals={
            "price_edge": {"available": True},
            "form_h2h": {"available": True},
            "lineup_injury": {"available": True},
            "market_agreement": {"available": True, "bookmaker_count": 4},
        },
        venue="Etihad Stadium",
        nickname="the Sky Blues",
        coach="Pep Guardiola",
        bet_type_is_team_outcome=True,
    )
    base.update(overrides)
    return VerdictContext(**base)


# ── Body never carries venue / stadium tokens ────────────────────────────────


@pytest.mark.parametrize(
    "fixture",
    [
        # EPL home favourites (most likely to trip venue copy pre-fix)
        dict(
            match_key="manchester_city_vs_brentford_2026-05-09",
            home_name="Manchester City",
            away_name="Brentford",
            recommended_team="Manchester City",
            outcome_label="Manchester City",
            venue="Etihad Stadium",
            tier="gold",
            sport="soccer",
            nickname="the Sky Blues",
        ),
        dict(
            match_key="manchester_united_vs_nottingham_forest_2026-05-17",
            home_name="Manchester United",
            away_name="Nottingham Forest",
            recommended_team="Manchester United",
            outcome_label="Manchester United",
            venue="Old Trafford",
            tier="gold",
            sport="soccer",
            nickname="the Red Devils",
        ),
        # PSL longtail — Marumo Gallants (worst pre-fix offender)
        dict(
            match_key="marumo_gallants_vs_richards_bay_2026-05-09",
            home_name="Marumo Gallants",
            away_name="Richards Bay",
            recommended_team="Marumo Gallants",
            outcome_label="Marumo Gallants",
            venue="Dr. Petrus Molemela Stadium",
            tier="silver",
            sport="soccer",
            nickname="Gallants",
        ),
        # Rugby URC home favourite
        dict(
            match_key="leinster_vs_lions_2026-05-09",
            home_name="Leinster",
            away_name="Lions",
            recommended_team="Leinster",
            outcome_label="Leinster",
            venue="Aviva Stadium",
            tier="silver",
            sport="rugby",
            nickname=None,
        ),
        # Cricket IPL home favourite
        dict(
            match_key="mumbai_indians_vs_chennai_super_kings_2026-05-09",
            home_name="Mumbai Indians",
            away_name="Chennai Super Kings",
            recommended_team="Mumbai Indians",
            outcome_label="Mumbai Indians",
            venue="Wankhede Stadium",
            tier="silver",
            sport="cricket",
            nickname="the Mumbai Indians",
        ),
    ],
)
def test_venue_tokens_not_in_rendered_body(fixture: dict) -> None:
    """Render the verdict; confirm no venue / stadium token surfaces anywhere
    in the output (body OR close — venue references are now off entirely)."""
    with _flags():
        ctx = _ctx(**fixture)
        text = render_verdict_v2(ctx).text
        for token in VENUE_TOKENS:
            assert not re.search(
                rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])",
                text,
                re.IGNORECASE,
            ), f"venue token '{token}' surfaced for {fixture['match_key']}: {text!r}"


def test_venue_reference_render_returns_none() -> None:
    """Phase 4 disable — _render_fact_clause rejects venue_reference at the
    top, regardless of name_team / body_ref. FACT_PRIORITY is intentionally
    LEFT INTACT so the rotation modulo stays byte-stable with the pre-fix
    engine; the disable lives in _render_fact_clause's early return so other
    primary fact_types fall through cleanly without renumbering candidates."""
    from verdict_engine_v2 import _render_fact_clause
    with _flags():
        ctx = _ctx(
            venue="Etihad Stadium",
            recommended_team="Manchester City",
            home_name="Manchester City",
            signals={
                "price_edge": {"available": True},
                "form_h2h": {"available": True},
            },
        )
        for name_team in (True, False):
            for body_ref in ("", "the Sky Blues", "Guardiola's side"):
                clause = _render_fact_clause(
                    ctx, "venue_reference", attempt=0,
                    name_team=name_team, body_ref=body_ref,
                )
                assert clause is None, (
                    f"venue_reference rendered (name_team={name_team}, "
                    f"body_ref={body_ref!r}): {clause!r}"
                )


def test_venue_reference_still_in_fact_priority_for_rotation_stability() -> None:
    """Rotation-modulo guard — keeping venue_reference in FACT_PRIORITY makes
    _rotated() return the same primary order as the pre-fix engine. Removing
    it would shift the rotation modulo and disturb other tests' shape choices.
    The render-time early return is the actual disable; this constant is a
    stability anchor."""
    assert "venue_reference" in FACT_PRIORITY


def test_venue_reference_function_kept_as_dead_code() -> None:
    """Phase 4 decision — keep the dispatch branch in _render_fact_clause as
    a one-line revert. This test fails if a future cleanup deletes it; that
    cleanup belongs in a separate brief once the deprecation has bedded in."""
    import inspect
    src = inspect.getsource(verdict_engine_v2._render_fact_clause)
    assert 'fact_type == "venue_reference"' in src, (
        "venue_reference branch removed from _render_fact_clause — Phase 4 "
        "decision was to keep it as dead code for cheap revert. If this "
        "deletion is intentional, file a follow-up brief and update this test."
    )
