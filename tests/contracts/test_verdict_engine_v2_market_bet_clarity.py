"""FIX-V2-VERDICT-SINGLE-MENTION-RESTRUCTURE-01 — market-bet clarity.

Asserts that non-team market bets (BTTS Yes/No, Over 2.5, Under 2.5) close on
the market name, not slot-fill a team. Team-bets continue to close with the
bare team. Body never injects team into a market-bet close.
"""
from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager

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


def _market_ctx(market: str, **overrides) -> VerdictContext:
    """Build a non-team market-bet context.

    recommended_team and outcome_label both carry the market label so the
    engine + validator agree on the close target. bet_type_is_team_outcome
    is False — the engine routes to the market-close path.
    """
    base = dict(
        match_key="liverpool_vs_chelsea_2026-05-09",
        edge_revision="rev-1",
        sport="soccer",
        league="epl",
        home_name="Liverpool",
        away_name="Chelsea",
        recommended_team=market,
        outcome_label=market,
        odds="1.95",
        bookmaker="WSB",
        tier="gold",
        signals={
            "price_edge": {"available": True},
            "form_h2h": {"available": True},
            "market_agreement": {"available": True, "bookmaker_count": 4},
        },
        venue=None,
        nickname=None,
        coach=None,
        bet_type_is_team_outcome=False,
    )
    base.update(overrides)
    return VerdictContext(**base)


def _team_ctx(**overrides) -> VerdictContext:
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
        },
        bet_type_is_team_outcome=True,
    )
    base.update(overrides)
    return VerdictContext(**base)


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", text, re.IGNORECASE) is not None


def _close_segment(text: str) -> str:
    """Last sentence — the close. Splits on ' — ' (em-dash) which separates
    body from action, then takes the trailing sentence after the action."""
    if "—" in text:
        return text.rsplit("—", 1)[1].strip()
    return text


def test_btts_yes_close_phrases_market_explicitly() -> None:
    with _flag("true"):
        ctx = _market_ctx("BTTS Yes")
        verdict = render_verdict_v2(ctx)
        text = verdict.text
        close = _close_segment(text)
        assert "BTTS Yes" in close, f"close should name BTTS Yes: {text!r}"
        # Verbiage should be one of the canonical market actions.
        assert any(
            phrase in close
            for phrase in ("Back BTTS Yes", "BTTS Yes is the play", "Lean BTTS Yes", "BTTS Yes gets the nod")
        ), f"close should use a market-action template: {text!r}"


def test_btts_no_close_phrases_market_explicitly() -> None:
    with _flag("true"):
        ctx = _market_ctx("BTTS No", tier="silver")
        verdict = render_verdict_v2(ctx)
        text = verdict.text
        close = _close_segment(text)
        assert "BTTS No" in close, f"close should name BTTS No: {text!r}"


def test_over_2_5_close_phrases_market_explicitly() -> None:
    with _flag("true"):
        ctx = _market_ctx("Over 2.5", tier="diamond")
        verdict = render_verdict_v2(ctx)
        text = verdict.text
        close = _close_segment(text)
        assert "Over 2.5" in close, f"close should name Over 2.5: {text!r}"


def test_under_2_5_close_phrases_market_explicitly() -> None:
    with _flag("true"):
        ctx = _market_ctx("Under 2.5", tier="bronze")
        verdict = render_verdict_v2(ctx)
        text = verdict.text
        close = _close_segment(text)
        assert "Under 2.5" in close, f"close should name Under 2.5: {text!r}"


def test_team_win_still_closes_with_team() -> None:
    """Regression: bet_type_is_team_outcome=True still closes with bare team."""
    with _flag("true"):
        ctx = _team_ctx()
        verdict = render_verdict_v2(ctx)
        text = verdict.text
        close = _close_segment(text)
        assert "Liverpool" in close, f"team-bet close should name Liverpool: {text!r}"
        # No 'win' suffix in the close — the bare team is the close target.
        assert "Liverpool win" not in text, f"engine should receive bare team, not 'Liverpool win': {text!r}"


def test_market_bet_body_does_not_inject_team_in_close() -> None:
    """Prove BTTS verdict doesn't leak Liverpool/Chelsea into the close."""
    with _flag("true"):
        ctx = _market_ctx("BTTS Yes")
        verdict = render_verdict_v2(ctx)
        text = verdict.text
        close = _close_segment(text)
        assert not _has_word(close, "Liverpool"), (
            f"market-bet close should not name a team: {close!r} (full: {text!r})"
        )
        assert not _has_word(close, "Chelsea"), (
            f"market-bet close should not name a team: {close!r} (full: {text!r})"
        )
