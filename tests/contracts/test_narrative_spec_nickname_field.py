"""FIX-V2-VERDICT-NICKNAME-COACH-BODY-AND-VENUE-DROP-01 — NarrativeSpec nickname plumbing.

Asserts the dataclass carries the new field with default '', and
build_narrative_spec populates it via lookup_nickname using the recommended
team WHEN V2_BODY_REFERENCE is enabled (gated post Codex P2 round-1 finding —
flag=false fully restores the pre-fix lead identity path). verdict_corpus.
_spec_to_verdict_context already reads getattr(spec, 'nickname', None) and
feeds it to VerdictContext.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import pytest

import narrative_spec
from narrative_spec import NarrativeSpec, build_narrative_spec, lookup_nickname


@contextmanager
def _body_ref_flag(value: str) -> Iterator[None]:
    """Pin V2_BODY_REFERENCE for the test body — the flag gates whether
    build_narrative_spec calls lookup_nickname (Codex P2 round-1 fix)."""
    prev = os.environ.get("V2_BODY_REFERENCE")
    os.environ["V2_BODY_REFERENCE"] = value
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("V2_BODY_REFERENCE", None)
        else:
            os.environ["V2_BODY_REFERENCE"] = prev


# ── Dataclass field shape ────────────────────────────────────────────────────


def test_narrative_spec_has_nickname_field() -> None:
    """The dataclass exposes a `nickname: str` with default ''. Default makes
    legacy callers that construct NarrativeSpec without it forward-compatible."""
    fields = NarrativeSpec.__dataclass_fields__
    assert "nickname" in fields, "NarrativeSpec missing `nickname` field"
    field = fields["nickname"]
    assert field.type is str or field.type == "str", (
        f"nickname annotation should be str, got {field.type}"
    )
    spec = NarrativeSpec(
        home_name="X",
        away_name="Y",
        competition="C",
        sport="soccer",
        home_story_type="",
        away_story_type="",
    )
    assert spec.nickname == ""


# ── build_narrative_spec populates nickname ─────────────────────────────────


def _stub_bot_imports():
    """Patch the lazy imports build_narrative_spec pulls from bot.py so the
    test runs without a live Sentry / DB env."""
    return patch.multiple(
        "bot",
        _decide_team_story=lambda *a, **k: "neutral",
        _build_verified_scaffold=lambda *a, **k: "",
        _scaffold_last_result=lambda *a, **k: "",
        _parse_record=lambda *a, **k: None,
        get_verified_injuries=lambda *a, **k: {"home": [], "away": []},
    )


def _edge_data(home: str, away: str, outcome: str = "home") -> dict:
    return {
        "home_team": home,
        "away_team": away,
        "outcome": outcome,
        "best_odds": 2.0,
        "best_bookmaker": "WSB",
        "edge_pct": 5.0,
        "fair_prob": 0.5,
        "composite_score": 50.0,
        "edge_tier": "gold",
        "match_key": f"{home.lower().replace(' ', '_')}_vs_{away.lower().replace(' ', '_')}_2026-05-09",
        "league": "epl",
        "confirming_signals": 2,
        "contradicting_signals": 0,
    }


def _ctx_data(home: str, away: str) -> dict:
    return {
        "home_team": {"name": home},
        "away_team": {"name": away},
        "venue": "",
    }


def test_build_narrative_spec_populates_nickname_when_known() -> None:
    """Recommended team = Liverpool → spec.nickname = 'the Reds' from
    bot/data/team_nicknames.json. Flag must be on for plumbing to fire."""
    with _body_ref_flag("true"), _stub_bot_imports():
        spec = build_narrative_spec(
            ctx_data=_ctx_data("Liverpool", "Chelsea"),
            edge_data=_edge_data("Liverpool", "Chelsea", outcome="home"),
            tips=[],
            sport="soccer",
        )
    assert spec.nickname == "the Reds", f"expected 'the Reds', got {spec.nickname!r}"


def test_build_narrative_spec_leaves_nickname_empty_when_unknown() -> None:
    """An unmapped team returns '' from lookup_nickname, so spec.nickname
    stays empty — the engine then falls through to coach / anaphor."""
    with _body_ref_flag("true"), _stub_bot_imports():
        spec = build_narrative_spec(
            ctx_data=_ctx_data("Some Unknown FC", "Another Mystery"),
            edge_data=_edge_data("Some Unknown FC", "Another Mystery", outcome="home"),
            tips=[],
            sport="soccer",
        )
    assert spec.nickname == "", f"expected '', got {spec.nickname!r}"


def test_build_narrative_spec_picks_recommended_not_opposing_nickname() -> None:
    """Recommendation = Chelsea (away) → spec.nickname = 'the Blues' (Chelsea's
    nickname), NOT Liverpool's 'the Reds' even though Liverpool is also in the
    fixture."""
    with _body_ref_flag("true"), _stub_bot_imports():
        spec = build_narrative_spec(
            ctx_data=_ctx_data("Liverpool", "Chelsea"),
            edge_data=_edge_data("Liverpool", "Chelsea", outcome="away"),
            tips=[],
            sport="soccer",
        )
    assert spec.nickname == "the Blues", (
        f"expected Chelsea's nickname 'the Blues', got {spec.nickname!r}"
    )


def test_build_narrative_spec_flag_off_skips_nickname() -> None:
    """V2_BODY_REFERENCE=false fully restores pre-fix lead path: spec.nickname
    stays empty even for a mapped team. Codex P2 round-1 ensures
    identity_label sees no alias and reverts to bare-team lead."""
    with _body_ref_flag("false"), _stub_bot_imports():
        spec = build_narrative_spec(
            ctx_data=_ctx_data("Liverpool", "Chelsea"),
            edge_data=_edge_data("Liverpool", "Chelsea", outcome="home"),
            tips=[],
            sport="soccer",
        )
    assert spec.nickname == "", (
        f"flag=false should skip nickname plumbing, got {spec.nickname!r}"
    )


# ── New dictionary entries reachable via lookup_nickname ────────────────────


@pytest.mark.parametrize(
    "team,expected",
    [
        # Phase 5 longtail consolidation — at least one entry per cluster.
        ("Marumo Gallants", "Gallants"),
        ("TS Galaxy", "Galaxy"),
        ("Stellenbosch", "Stellies"),
        ("AmaZulu", "Usuthu"),
        ("West Ham United", "the Hammers"),
        ("Crystal Palace", "Palace"),
        ("Highlanders", "the Landers"),
        ("Hurricanes", "the Canes"),
    ],
)
def test_lookup_nickname_covers_phase5_longtail(team: str, expected: str) -> None:
    # Reset cache so the test reads the on-disk JSON freshly.
    narrative_spec._NICKNAME_LOOKUP_CACHE = None
    assert lookup_nickname(team) == expected, (
        f"expected {expected!r} for {team!r}, got {lookup_nickname(team)!r}"
    )
