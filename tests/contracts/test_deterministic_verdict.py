"""BUILD-VERDICT-01 — Deterministic verdict blacklist contract test.

Synthesises 100 NarrativeSpec instances across all sports/tiers/evidence classes
and asserts that _render_verdict() emits zero blacklisted phrases.

Regression guard: if any test fails, a banned phrase has crept back into the
deterministic verdict templates in narrative_spec.py.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from narrative_spec import NarrativeSpec, _render_verdict
from bot import _VERDICT_BLACKLIST


_SPORTS = ["soccer", "rugby", "cricket", "boxing"]
_VERDICT_ACTIONS = ["speculative punt", "lean", "back", "strong back", "monitor"]
_TONES = ["cautious", "moderate", "confident", "strong"]
_EVIDENCE_CLASSES = ["speculative", "lean", "supported", "conviction"]
_SIZINGS = {
    "speculative punt": "tiny exposure",
    "lean": "small stake",
    "back": "standard stake",
    "strong back": "confident stake",
    "monitor": "monitor",
}
_TONES_FOR_ACTION = {
    "speculative punt": "cautious",
    "lean": "moderate",
    "back": "confident",
    "strong back": "strong",
    "monitor": "cautious",
}
_EVIDENCE_FOR_ACTION = {
    "speculative punt": "speculative",
    "lean": "lean",
    "back": "supported",
    "strong back": "conviction",
    "monitor": "speculative",
}


def _make_spec(
    sport: str,
    verdict_action: str,
    outcome: str,
    outcome_label: str,
    home_name: str,
    away_name: str,
    ev_pct: float = 4.5,
    support_level: int = 2,
    stale_minutes: int = 30,
    bookmaker: str = "Betway",
    odds: float = 2.10,
    edge_tier: str = "gold",
) -> NarrativeSpec:
    tone = _TONES_FOR_ACTION[verdict_action]
    evidence_class = _EVIDENCE_FOR_ACTION[verdict_action]
    sizing = _SIZINGS[verdict_action]
    return NarrativeSpec(
        home_name=home_name,
        away_name=away_name,
        competition="Premier League",
        sport=sport,
        home_story_type="momentum",
        away_story_type="neutral",
        evidence_class=evidence_class,
        tone_band=tone,
        verdict_action=verdict_action,
        verdict_sizing=sizing,
        outcome=outcome,
        outcome_label=outcome_label,
        bookmaker=bookmaker,
        odds=odds,
        ev_pct=ev_pct,
        support_level=support_level,
        edge_tier=edge_tier,
        stale_minutes=stale_minutes,
        movement_direction="neutral",
        tipster_against=0,
    )


def _build_100_specs() -> list[NarrativeSpec]:
    specs: list[NarrativeSpec] = []
    fixture_pairs = [
        ("Arsenal", "Chelsea", "soccer"),
        ("Sundowns", "Pirates", "soccer"),
        ("Stormers", "Bulls", "rugby"),
        ("South Africa", "New Zealand", "rugby"),
        ("India", "Australia", "cricket"),
        ("Proteas", "England", "cricket"),
        ("Fury", "Usyk", "boxing"),
        ("Du Plessis", "Adesanya", "boxing"),
        ("Liverpool", "Man City", "soccer"),
        ("Amakhosi", "Usuthu", "soccer"),
    ]
    outcomes_by_sport = {
        "soccer": [("home", "home win"), ("away", "away win"), ("draw", "the draw")],
        "rugby": [("home", "home win"), ("away", "away win")],
        "cricket": [("home", "home win"), ("away", "away win")],
        "boxing": [("home", "home win"), ("away", "away win")],
    }
    actions = ["speculative punt", "lean", "back", "strong back"]
    ev_levels = [2.1, 5.5, 10.2, 15.8]
    support_levels = [0, 1, 2, 3]
    bookmakers = ["Betway", "Hollywoodbets", "Supabets", "GBets"]
    odds_values = [1.55, 1.85, 2.10, 3.20]

    idx = 0
    for home, away, sport in fixture_pairs:
        outcomes = outcomes_by_sport.get(sport, [("home", "home win")])
        for outcome, outcome_label in outcomes:
            for action in actions:
                i = idx % len(ev_levels)
                spec = _make_spec(
                    sport=sport,
                    verdict_action=action,
                    outcome=outcome,
                    outcome_label=outcome_label,
                    home_name=home,
                    away_name=away,
                    ev_pct=ev_levels[i],
                    support_level=support_levels[i],
                    bookmaker=bookmakers[i % len(bookmakers)],
                    odds=odds_values[i % len(odds_values)],
                    stale_minutes=30 if i % 2 == 0 else 720,
                )
                specs.append(spec)
                idx += 1
                if len(specs) >= 100:
                    return specs

    # Fill remaining with monitor action across sports
    while len(specs) < 100:
        home, away, sport = fixture_pairs[len(specs) % len(fixture_pairs)]
        spec = _make_spec(
            sport=sport,
            verdict_action="monitor",
            outcome="home",
            outcome_label="home win",
            home_name=home,
            away_name=away,
            ev_pct=-0.5,
            support_level=0,
        )
        specs.append(spec)

    return specs[:100]


_ALL_SPECS = _build_100_specs()


class TestDeterministicVerdictBlacklist:
    """BUILD-VERDICT-01: 100 spec sweep — zero blacklisted phrases in _render_verdict output."""

    @pytest.mark.parametrize("spec", _ALL_SPECS, ids=[
        f"{i:03d}_{s.sport}_{s.verdict_action[:4]}_{s.home_name[:4]}"
        for i, s in enumerate(_ALL_SPECS)
    ])
    def test_no_blacklisted_phrase(self, spec: NarrativeSpec) -> None:
        verdict = _render_verdict(spec)
        low = verdict.lower()
        for phrase in _VERDICT_BLACKLIST:
            assert phrase not in low, (
                f"Banned phrase {phrase!r} found in verdict for "
                f"{spec.sport}/{spec.verdict_action}/{spec.home_name} vs {spec.away_name}. "
                f"Verdict: {verdict!r}"
            )

    @pytest.mark.parametrize("spec", _ALL_SPECS, ids=[
        f"{i:03d}_{s.sport}_{s.verdict_action[:4]}_{s.home_name[:4]}"
        for i, s in enumerate(_ALL_SPECS)
    ])
    def test_verdict_not_empty_or_trivial(self, spec: NarrativeSpec) -> None:
        verdict = _render_verdict(spec)
        assert verdict and len(verdict) >= 140, (
            f"Verdict too short ({len(verdict)} chars, floor=140) for "
            f"{spec.sport}/{spec.verdict_action}/{spec.home_name} vs {spec.away_name}. "
            f"Got: {verdict!r}"
        )
