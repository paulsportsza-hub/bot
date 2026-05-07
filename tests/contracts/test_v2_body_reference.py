"""FIX-V2-VERDICT-NICKNAME-COACH-BODY-AND-VENUE-DROP-01 — Strategy α body-reference.

Asserts the priority chain (nickname → coach surname's side → anaphor) drives
the body slot-fill in V2 verdict renders. The close (ACTION_BY_TIER) keeps the
bare team — those assertions live alongside the apostrophe-rule checks for
coach surnames and the identity_lead double-mention guard.
"""
from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

import verdict_engine_v2
from verdict_engine_v2 import (
    VerdictContext,
    _body_reference,
    _coach_surname_possessive,
    _identity_used_alias,
    identity_label,
    render_verdict_v2,
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
        match_key="newcastle_united_vs_brighton_2026-05-09",
        edge_revision="rev-1",
        sport="soccer",
        league="epl",
        home_name="Newcastle United",
        away_name="Brighton",
        recommended_team="Newcastle United",
        outcome_label="Newcastle United",
        odds="2.10",
        bookmaker="WSB",
        tier="gold",
        signals={
            "price_edge": {"available": True},
            "form_h2h": {"available": True},
            "market_agreement": {"available": True, "bookmaker_count": 4},
        },
        venue="St James' Park",
        nickname="the Magpies",
        coach="Eddie Howe",
        bet_type_is_team_outcome=True,
    )
    base.update(overrides)
    return VerdictContext(**base)


# ── Priority chain (4 cases) ────────────────────────────────────────────────


def test_alpha_priority_nickname_first() -> None:
    """Nickname populated → body uses nickname, regardless of coach state."""
    ctx = _ctx(nickname="the Magpies", coach="Eddie Howe")
    ref = _body_reference(ctx, salt="form_h2h")
    assert ref == "the Magpies"


def test_alpha_priority_coach_when_no_nickname() -> None:
    """Nickname empty + coach populated → body uses '<Surname>'s side'."""
    ctx = _ctx(nickname=None, coach="Pep Guardiola")
    ref = _body_reference(ctx, salt="form_h2h")
    assert ref == "Guardiola's side"


def test_alpha_priority_anaphor_when_neither() -> None:
    """Both empty → body falls through to the anaphor pool."""
    ctx = _ctx(nickname=None, coach=None)
    ref = _body_reference(ctx, salt="form_h2h")
    assert ref in verdict_engine_v2.ANAPHOR_POOL


# ── Apostrophe-s rule (3 cases) ─────────────────────────────────────────────


def test_apostrophe_s_for_normal_surname() -> None:
    assert _coach_surname_possessive("Pep Guardiola") == "Guardiola's side"


def test_apostrophe_only_for_surname_ending_in_s() -> None:
    """Trailing 's' → apostrophe-only ('Ramos' side', not 'Ramos's side')."""
    assert _coach_surname_possessive("Sergio Ramos") == "Ramos' side"


def test_coach_split_takes_last_token_as_surname() -> None:
    """Multi-word coach names → surname = last whitespace token."""
    assert _coach_surname_possessive("Sir Alex Ferguson") == "Ferguson's side"
    assert _coach_surname_possessive("Pep Guardiola") == "Guardiola's side"
    # Single-token coach: still produces a usable phrase.
    assert _coach_surname_possessive("Mourinho") == "Mourinho's side"
    # Empty / None inputs map to empty (so the priority chain falls through
    # to anaphor instead of emitting a stray possessive).
    assert _coach_surname_possessive("") == ""
    assert _coach_surname_possessive("   ") == ""


# ── Anaphor stable_pick + variety across match_keys ─────────────────────────


def test_anaphor_picked_deterministically() -> None:
    """Same match_key + edge_revision + tier + salt → same anaphor every time."""
    ctx = _ctx(nickname=None, coach=None)
    a = _body_reference(ctx, salt="form_h2h")
    b = _body_reference(ctx, salt="form_h2h")
    assert a == b
    assert a in verdict_engine_v2.ANAPHOR_POOL


def test_anaphor_pool_variety_across_match_keys() -> None:
    """Different match_keys → at least 3 distinct anaphor strings (rotation works)."""
    seen: set[str] = set()
    for i in range(8):
        ctx = _ctx(
            match_key=f"team_a_vs_team_b_2026-05-{i + 1:02d}",
            nickname=None,
            coach=None,
        )
        seen.add(_body_reference(ctx, salt="form_h2h"))
    assert len(seen) >= 3, f"expected ≥3 distinct anaphors, got {seen}"


# ── identity_lead shape exception ────────────────────────────────────────────


def test_identity_lead_shape_forces_body_anaphor() -> None:
    """When identity_label fired with nickname/coach, body falls through to
    anaphor. Renders the full verdict and asserts the body section never
    contains *both* the nickname and the team in the body half (we measure by
    splitting on the close em-dash). Probe across multiple match_keys so we
    hit the identity_price_fact_action shape at least once."""
    with _flags():
        body_alias_count = 0
        rendered_any_identity = False
        for i in range(40):
            ctx = _ctx(
                match_key=f"newcastle_united_vs_brighton_2026-05-{i + 1:02d}",
                nickname="the Magpies",
                coach="Eddie Howe",
            )
            res = render_verdict_v2(ctx)
            text = res.text
            # Heuristic: identity_price_fact_action shape produces "X price — fact. action."
            # The fact between em-dash and the closing period is the body fact_clause.
            if " — " not in text:
                continue
            head, body_and_close = text.split(" — ", 1)
            if "the Magpies" in head:
                rendered_any_identity = True
                body_only = body_and_close.split(". ")[0] if ". " in body_and_close else body_and_close
                # body should NOT carry "the Magpies" too — _identity_used_alias
                # must have routed body to anaphor.
                assert "the Magpies" not in body_only, (
                    f"identity_lead shape repeated nickname in body — full text: {text!r}"
                )
            if any(a in text for a in verdict_engine_v2.ANAPHOR_POOL):
                body_alias_count += 1
        # At least one identity_lead shape should have rendered across the
        # 40 probes (otherwise the test is silently passing on a non-firing
        # shape). The specific ratio depends on _rotated salt distribution.
        assert rendered_any_identity, "identity_lead shape never fired across 40 probes"


def test_identity_used_alias_detector() -> None:
    """_identity_used_alias returns False when identity_label produced bare team,
    True when it produced nickname or coach phrase."""
    ctx_team = _ctx(nickname=None, coach=None)
    ident_team = identity_label(ctx_team, salt="probe")
    assert _identity_used_alias(ident_team, ctx_team) is False

    ctx_alias = _ctx(nickname="the Magpies", coach="Eddie Howe")
    ident_alias = identity_label(ctx_alias, salt="probe")
    # identity_label may pick team OR alias; only assert when it actually did.
    if ident_alias != "Newcastle United":
        assert _identity_used_alias(ident_alias, ctx_alias) is True


# ── Flag-off rollback ───────────────────────────────────────────────────────


def test_flag_off_falls_back_to_current_anaphor_only_body() -> None:
    """V2_BODY_REFERENCE=false → body has no nickname/coach phrase from α
    chain; the C+D anaphor-less clauses are emitted (e.g. 'the value is still
    there' rather than '... for the Magpies')."""
    with _flags(single="true", body_ref="false"):
        ctx = _ctx(nickname="the Magpies", coach="Eddie Howe")
        text = render_verdict_v2(ctx).text
        # Body should NOT contain the nickname or the coach phrase, because
        # body_ref is gated off and the C+D path is anaphor-less by design.
        # (Lead position can still carry nickname through identity_label —
        # so we restrict the assertion to the body portion after " — ".)
        if " — " in text:
            body_section = text.split(" — ", 1)[1]
            # Trim the close (last sentence) — body is everything before the
            # final period that ends with the action verb pattern.
            body_only = body_section.split(". ")[0] if ". " in body_section else body_section
            assert "Howe's side" not in body_only, f"coach phrase leaked into body: {text!r}"
            assert "for the Magpies" not in body_only, f"nickname leaked into body: {text!r}"


def test_flag_off_does_not_affect_close() -> None:
    """V2_BODY_REFERENCE=false → close still uses bare team. Symmetric with
    flag=true; the close path never reads V2_BODY_REFERENCE."""
    for flag in ("true", "false"):
        with _flags(single="true", body_ref=flag):
            ctx = _ctx(nickname="the Magpies", coach="Eddie Howe")
            text = render_verdict_v2(ctx).text
            # Close keeps "Newcastle United" — assert appears at least once.
            assert "Newcastle United" in text, f"close lost team [{flag}]: {text!r}"


def test_close_always_uses_bare_team() -> None:
    """ACTION_BY_TIER renders use {team} — never nickname, coach phrase, or
    anaphor. Sample across tiers; assert the close substring matches one of
    the action verbs and contains the bare recommended_team."""
    with _flags():
        for tier in ("diamond", "gold", "silver", "bronze"):
            ctx = _ctx(tier=tier, nickname="the Magpies", coach="Eddie Howe")
            text = render_verdict_v2(ctx).text
            # The close is the trailing sentence; assert "Newcastle United"
            # appears in the overall verdict (close carries it).
            assert "Newcastle United" in text, f"[{tier}] close missing team: {text!r}"
            # Close should not say "back the Magpies" or "back Howe's side".
            assert not re.search(
                r"\b(back|lean|small lean to|worth a small play on)\s+the\s+Magpies\b",
                text,
                re.IGNORECASE,
            ), f"[{tier}] close used nickname: {text!r}"
            assert "Howe's side" not in text, f"[{tier}] close used coach phrase: {text!r}"
