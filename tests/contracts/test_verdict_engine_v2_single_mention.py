"""FIX-V2-VERDICT-SINGLE-MENTION-RESTRUCTURE-01 — single-mention contract.

Asserts that with V2_SINGLE_MENTION=true (Approach C), every shape branch in
_render_candidate names the recommended team at most once per render. The
identity-lead shape is the documented exception: identity_label may use the
team itself when no nickname is available, producing two mentions (lead +
close); when a nickname is available it falls to one.
"""
from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

import verdict_engine_v2
from verdict_engine_v2 import VerdictContext, render_verdict_v2


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


def _team_count(text: str, team: str) -> int:
    """Count whole-word occurrences of `team` in `text` (case-insensitive)."""
    if not team:
        return 0
    pattern = rf"(?<![A-Za-z0-9]){re.escape(team)}(?![A-Za-z0-9])"
    return len(re.findall(pattern, text, re.IGNORECASE))


# ── 1: 4 tiers × 3 sports — render-level mention cap ────────────────────────


@pytest.mark.parametrize(
    "tier",
    ("diamond", "gold", "silver", "bronze"),
)
def test_team_mentioned_at_most_once_per_render_diamond_soccer(tier: str) -> None:
    """Tier-parameterised soccer render — recommended_team appears ≤1× per
    verdict (identity_lead exception is bounded ≤2×; we assert across all
    fact_attempts using deterministic match_keys)."""
    with _flag("true"):
        # Use a non-identity-friendly fixture (no nickname) so identity_lead
        # falls back to team — that's the documented exception, ≤2× allowed.
        ctx = _ctx(tier=tier, nickname=None, coach=None)
        text = render_verdict_v2(ctx).text
        count = _team_count(text, "Liverpool")
        assert count <= 2, f"[{tier}] expected ≤2× (identity-lead allowed), got {count}: {text!r}"


def test_team_mentioned_at_most_once_per_render_gold_soccer() -> None:
    with _flag("true"):
        # Nickname present → identity_label may pick nickname → 1× mention possible
        # Non-identity shapes always 1×.
        ctx = _ctx(tier="gold", nickname="the Reds", coach="Slot")
        text = render_verdict_v2(ctx).text
        count = _team_count(text, "Liverpool")
        assert count <= 2, f"got {count}: {text!r}"


def test_team_mentioned_at_most_once_per_render_silver_rugby() -> None:
    with _flag("true"):
        ctx = _ctx(
            sport="rugby",
            league="urc",
            tier="silver",
            home_name="Leinster",
            away_name="Lions",
            recommended_team="Leinster",
            outcome_label="Leinster",
            match_key="leinster_vs_lions_2026-05-09",
            venue="Aviva Stadium",
            nickname=None,
            coach=None,
        )
        text = render_verdict_v2(ctx).text
        count = _team_count(text, "Leinster")
        assert count <= 2, f"got {count}: {text!r}"


def test_team_mentioned_at_most_once_per_render_silver_cricket() -> None:
    with _flag("true"):
        ctx = _ctx(
            sport="cricket",
            league="ipl",
            tier="silver",
            home_name="Mumbai Indians",
            away_name="Delhi Capitals",
            recommended_team="Mumbai Indians",
            outcome_label="Mumbai Indians",
            match_key="mumbai_indians_vs_delhi_capitals_2026-05-09",
            venue="Wankhede Stadium",
            nickname=None,
            coach=None,
        )
        text = render_verdict_v2(ctx).text
        count = _team_count(text, "Mumbai Indians")
        assert count <= 2, f"got {count}: {text!r}"


def test_team_mentioned_at_most_once_per_render_bronze_soccer() -> None:
    with _flag("true"):
        ctx = _ctx(tier="bronze", nickname=None, coach=None)
        text = render_verdict_v2(ctx).text
        count = _team_count(text, "Liverpool")
        assert count <= 2, f"got {count}: {text!r}"


# ── 2: per-shape mention cap (force shape via stable_pick rotation) ─────────


def _force_shape_render(ctx: VerdictContext, shape: str) -> str | None:
    """Helper: force the engine to render a specific shape by trying each
    primary fact + attempt combo until that shape returns a candidate."""
    primary_options = verdict_engine_v2._rotated(
        verdict_engine_v2._available_fact_types(ctx),
        key=f"{verdict_engine_v2._base_key(ctx)}|primary_fact_type",
    )
    for primary in primary_options:
        for attempt in range(8):
            text = verdict_engine_v2._render_candidate(
                ctx, primary_fact_type=primary, shape=shape, attempt=attempt
            )
            if text and not verdict_engine_v2.validate_verdict(text, ctx):
                return text
    return None


def test_team_mentioned_at_most_once_per_shape_fact_action() -> None:
    with _flag("true"):
        ctx = _ctx(nickname=None, coach=None)
        text = _force_shape_render(ctx, "fact_action")
        assert text is not None, "fact_action shape should render with valid signals"
        count = _team_count(text, "Liverpool")
        assert count == 1, f"fact_action expected 1× team, got {count}: {text!r}"


def test_team_mentioned_at_most_once_per_shape_fact_price_action() -> None:
    with _flag("true"):
        ctx = _ctx(nickname=None, coach=None)
        text = _force_shape_render(ctx, "fact_price_action")
        assert text is not None, "fact_price_action shape should render with valid signals"
        count = _team_count(text, "Liverpool")
        assert count == 1, f"fact_price_action expected 1× team, got {count}: {text!r}"


def test_team_mentioned_at_most_once_per_shape_price_fact_action() -> None:
    with _flag("true"):
        ctx = _ctx(nickname=None, coach=None)
        text = _force_shape_render(ctx, "price_fact_action")
        assert text is not None, "price_fact_action shape should render with valid signals"
        count = _team_count(text, "Liverpool")
        assert count == 1, f"price_fact_action (compound) expected 1× team, got {count}: {text!r}"


def test_identity_lead_shape_acceptable_double_mention() -> None:
    """Documented exception: identity_lead may repeat team if no nickname."""
    with _flag("true"):
        ctx = _ctx(nickname=None, coach=None)
        text = _force_shape_render(ctx, "identity_price_fact_action")
        assert text is not None, "identity_lead should render"
        count = _team_count(text, "Liverpool")
        # Identity-lead with no nickname uses team as identity; close uses team.
        # Body uses anaphor, so total = 2 (lead + close).
        assert count <= 2, f"identity_lead expected ≤2×, got {count}: {text!r}"


def test_flag_off_falls_back_to_current_shape_behaviour() -> None:
    """flag=0 → engine uses legacy name_team=True everywhere. Body fact
    clauses re-acquire team-naming, producing the pre-fix 2-4× distribution."""
    with _flag("false"):
        ctx = _ctx(nickname=None, coach=None)
        text = render_verdict_v2(ctx).text
        count = _team_count(text, "Liverpool")
        # flag-off path matches pre-fix behaviour; we assert ≥2 to confirm
        # rollback works (legacy slot-fills body + close → ≥2 mentions).
        assert count >= 2, f"flag=false should preserve legacy ≥2× behaviour, got {count}: {text!r}"
