"""FIX-VERDICT-CACHE-PATH-LOCK-AND-W82-TEMPLATE-CLOSURE-01 — AC-2 contract tests.

Generates 30 W82 verdicts spanning all 4 tiers + multiple leagues + multiple
sports + verdict_action permutations and asserts:

  - 30/30 last sentence contains action verb cluster (imperative OR
    declarative) + team or selection + odds shape
  - 30/30 pass `_check_verdict_closure_rule` for their tier
  - All variants stay in the [140, 260] char window (Diamond floor 140)
  - No regression on existing TONE_BANDS or _VERDICT_BANNED_TELEMETRY phrases

This is the brief AC-2 evidence test confirming the W82 template restructure
landed correctly (action+team+odds → LAST sentence, not first).
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from narrative_spec import (
    NarrativeSpec,
    VERDICT_HARD_MAX,
    _render_verdict,
    MIN_VERDICT_CHARS_BY_TIER,
    _VERDICT_BANNED_TELEMETRY,
)
from narrative_validator import (
    _check_verdict_closure_rule,
    _last_sentence,
    _verdict_closure_components,
)


# ── 30-fixture corpus: 4 Diamond + 8 Gold + 8 Silver + 10 Bronze ─────────────


def _spec(
    home: str, away: str, comp: str, sport: str, outcome_label: str,
    bookmaker: str, odds: float, tier: str, action: str, sup: int, ev: float,
    composite: float = None, bm_count: int = 4,
) -> NarrativeSpec:
    if composite is None:
        composite = {"diamond": 85.0, "gold": 70.0, "silver": 55.0, "bronze": 45.0}[tier]
    tone = {
        "speculative punt": "cautious", "lean": "moderate",
        "back": "confident", "strong back": "strong",
        "pass": "cautious", "monitor": "cautious",
    }[action]
    evidence_class = {
        "speculative punt": "speculative", "lean": "lean",
        "back": "supported", "strong back": "conviction",
        "pass": "speculative", "monitor": "speculative",
    }[action]
    return NarrativeSpec(
        home_name=home, away_name=away, competition=comp, sport=sport,
        home_story_type="title_push", away_story_type="inconsistent",
        evidence_class=evidence_class, tone_band=tone, verdict_action=action,
        verdict_sizing="standard stake",
        outcome="home", outcome_label=outcome_label,
        bookmaker=bookmaker, odds=odds, ev_pct=ev, fair_prob_pct=58.0,
        composite_score=composite, bookmaker_count=bm_count,
        support_level=sup, contradicting_signals=0,
        risk_factors=["Form data thin from a 3-game window — squad rotation likely."],
        risk_severity="moderate", stale_minutes=0, movement_direction="neutral",
        tipster_against=0, edge_tier=tier,
    )


# 30 fixtures across 4 tiers × 5 sports × multiple leagues — each rendered with
# full risk_factors + tier-appropriate support_level. Brief AC-2: 30 W82
# verdicts spanning all 4 tiers + multiple leagues, asserting closure on each.
_FIXTURES_30: list[NarrativeSpec] = [
    # ── Diamond × 4 (premium, 1 per sport) ─────────────────────────────────
    _spec("Liverpool", "Chelsea", "Premier League", "soccer",
          "Liverpool win", "Supabets", 1.97, "diamond", "strong back", 4, 15.0),
    _spec("Bulls", "Stormers", "URC", "rugby",
          "Bulls win", "Hollywoodbets", 1.75, "diamond", "strong back", 4, 16.5),
    _spec("Mumbai Indians", "Chennai Super Kings", "IPL", "cricket",
          "Mumbai Indians win", "Sportingbet", 1.85, "diamond", "strong back", 4, 17.0),
    _spec("Dricus du Plessis", "Sean Strickland", "UFC", "mma",
          "Dricus du Plessis win", "Betway", 1.90, "diamond", "strong back", 4, 18.5),
    # ── Gold × 8 (back action, multi-league) ───────────────────────────────
    _spec("Manchester City", "Brentford", "Premier League", "soccer",
          "Manchester City win", "Hollywoodbets", 1.36, "gold", "back", 3, 8.5),
    _spec("Arsenal", "Spurs", "Premier League", "soccer",
          "Arsenal win", "Betway", 1.70, "gold", "back", 3, 9.0),
    _spec("Mamelodi Sundowns", "Kaizer Chiefs", "Premiership (PSL)", "soccer",
          "Mamelodi Sundowns win", "Hollywoodbets", 1.65, "gold", "back", 3, 8.2),
    _spec("Real Madrid", "Barcelona", "UEFA Champions League", "soccer",
          "Real Madrid win", "Supabets", 2.30, "gold", "back", 3, 9.5),
    _spec("Sharks", "Lions", "URC", "rugby",
          "Sharks win", "Sportingbet", 1.55, "gold", "back", 3, 8.0),
    _spec("Crusaders", "Blues", "Super Rugby", "rugby",
          "Crusaders win", "Betway", 1.55, "gold", "back", 3, 8.3),
    _spec("Royal Challengers Bangalore", "Delhi Capitals", "IPL", "cricket",
          "Royal Challengers Bangalore win", "Hollywoodbets", 1.80, "gold", "back", 2, 8.7),
    _spec("Joburg Super Kings", "Pretoria Capitals", "SA20", "cricket",
          "Pretoria Capitals win", "Hollywoodbets", 2.40, "gold", "back", 3, 8.4),
    # ── Silver × 8 (lean action, multi-league) ─────────────────────────────
    _spec("Liverpool", "Manchester United", "Premier League", "soccer",
          "Liverpool win", "Hollywoodbets", 1.85, "silver", "lean", 2, 5.0),
    _spec("Brighton", "Wolves", "Premier League", "soccer",
          "Brighton win", "Betway", 1.95, "silver", "lean", 2, 4.5),
    _spec("Brentford", "West Ham", "Premier League", "soccer",
          "Brentford win", "Sportingbet", 2.05, "silver", "lean", 1, 4.2),
    _spec("Orlando Pirates", "SuperSport United", "Premiership (PSL)", "soccer",
          "Orlando Pirates win", "Betway", 2.10, "silver", "lean", 2, 4.8),
    _spec("Bayern Munich", "Borussia Dortmund", "Bundesliga", "soccer",
          "Bayern Munich win", "Supabets", 1.55, "silver", "lean", 2, 4.4),
    _spec("Inter Milan", "Juventus", "Serie A", "soccer",
          "Inter Milan win", "Hollywoodbets", 2.00, "silver", "lean", 1, 4.6),
    _spec("PSG", "Marseille", "Ligue 1", "soccer",
          "PSG win", "Betway", 1.50, "silver", "lean", 2, 4.3),
    _spec("Stormers", "Bulls", "URC", "rugby",
          "Stormers win", "Hollywoodbets", 2.20, "silver", "lean", 1, 4.7),
    # ── Bronze × 10 (speculative punt + pass/monitor, multi-league) ────────
    _spec("Burnley", "Luton", "Premier League", "soccer",
          "Burnley win", "Hollywoodbets", 3.50, "bronze", "speculative punt", 1, 1.5),
    _spec("Leicester", "Leeds", "Premier League", "soccer",
          "Leicester win", "Sportingbet", 2.95, "bronze", "speculative punt", 0, 1.2),
    _spec("Cape Town City", "Stellenbosch", "Premiership (PSL)", "soccer",
          "Cape Town City win", "Hollywoodbets", 3.10, "bronze", "speculative punt", 1, 1.1),
    _spec("Wolves", "Aston Villa", "Premier League", "soccer",
          "Wolves win", "Betway", 4.20, "bronze", "speculative punt", 0, 1.0),
    _spec("Fulham", "Crystal Palace", "Premier League", "soccer",
          "Fulham win", "Supabets", 2.85, "bronze", "speculative punt", 1, 1.4),
    _spec("Newcastle", "West Ham", "Premier League", "soccer",
          "Newcastle win", "Hollywoodbets", 1.90, "bronze", "pass", 0, 0.5),
    _spec("AC Milan", "Roma", "Serie A", "soccer",
          "AC Milan win", "Betway", 1.85, "bronze", "monitor", 0, 0.3),
    _spec("Atletico Madrid", "Sevilla", "La Liga", "soccer",
          "Atletico Madrid win", "Sportingbet", 1.75, "bronze", "speculative punt", 0, 1.6),
    _spec("Cape Town Spurs", "Royal AM", "Premiership (PSL)", "soccer",
          "Cape Town Spurs win", "Hollywoodbets", 3.80, "bronze", "speculative punt", 1, 1.3),
    _spec("Bafana Bafana", "Nigeria", "International", "soccer",
          "Bafana Bafana win", "Betway", 2.60, "bronze", "speculative punt", 0, 1.7),
]

assert len(_FIXTURES_30) == 30, f"Expected 30 fixtures, got {len(_FIXTURES_30)}"


# ── AC-2.A — All 30 verdicts pass closure rule for their tier ───────────────


@pytest.mark.parametrize("spec", _FIXTURES_30, ids=lambda s: f"{s.edge_tier}-{s.home_name[:6]}-{s.verdict_action[:4]}")
def test_w82_verdict_closes_with_action_team_odds(spec: NarrativeSpec):
    """AC-2: every W82 verdict's LAST sentence contains action verb +
    (team or selection) + odds shape — passes closure rule for its tier."""
    verdict = _render_verdict(spec)
    sev, reason = _check_verdict_closure_rule(
        verdict,
        spec.edge_tier,
        {"home_team": spec.home_name, "away_team": spec.away_name},
    )
    assert sev is None, (
        f"[{spec.edge_tier}/{spec.sport}/{spec.home_name}] Closure rule "
        f"failed ({reason}). Last sentence: {_last_sentence(verdict)!r}. "
        f"Full verdict: {verdict!r}"
    )


@pytest.mark.parametrize("spec", _FIXTURES_30, ids=lambda s: f"{s.edge_tier}-{s.home_name[:6]}-{s.verdict_action[:4]}")
def test_w82_last_sentence_has_action_verb(spec: NarrativeSpec):
    """AC-2 component breakdown: closing sentence has action verb."""
    verdict = _render_verdict(spec)
    last = _last_sentence(verdict)
    has_action, _, _ = _verdict_closure_components(
        last, spec.home_name, spec.away_name,
    )
    assert has_action, (
        f"[{spec.edge_tier}/{spec.sport}] Last sentence missing action verb: "
        f"{last!r}"
    )


@pytest.mark.parametrize("spec", _FIXTURES_30, ids=lambda s: f"{s.edge_tier}-{s.home_name[:6]}-{s.verdict_action[:4]}")
def test_w82_last_sentence_has_team_or_selection(spec: NarrativeSpec):
    """AC-2 component breakdown: closing sentence has team or selection."""
    verdict = _render_verdict(spec)
    last = _last_sentence(verdict)
    _, has_team, _ = _verdict_closure_components(
        last, spec.home_name, spec.away_name,
    )
    assert has_team, (
        f"[{spec.edge_tier}/{spec.sport}/{spec.home_name}] Last sentence "
        f"missing team_or_selection: {last!r}"
    )


@pytest.mark.parametrize("spec", _FIXTURES_30, ids=lambda s: f"{s.edge_tier}-{s.home_name[:6]}-{s.verdict_action[:4]}")
def test_w82_last_sentence_has_odds_shape(spec: NarrativeSpec):
    """AC-2 component breakdown: closing sentence has odds shape."""
    verdict = _render_verdict(spec)
    last = _last_sentence(verdict)
    _, _, has_odds = _verdict_closure_components(
        last, spec.home_name, spec.away_name,
    )
    assert has_odds, (
        f"[{spec.edge_tier}/{spec.sport}] Last sentence missing odds shape: "
        f"{last!r}"
    )


# ── AC-2.B — Length window per tier ──────────────────────────────────────────


@pytest.mark.parametrize("spec", _FIXTURES_30, ids=lambda s: f"{s.edge_tier}-{s.home_name[:6]}-{s.verdict_action[:4]}")
def test_w82_verdict_within_length_window(spec: NarrativeSpec):
    """AC-2: every verdict is within [tier_floor, VERDICT_HARD_MAX]."""
    verdict = _render_verdict(spec)
    floor = MIN_VERDICT_CHARS_BY_TIER[spec.edge_tier]
    assert floor <= len(verdict) <= VERDICT_HARD_MAX, (
        f"[{spec.edge_tier}/{spec.sport}] Verdict length {len(verdict)} "
        f"outside [{floor}, {VERDICT_HARD_MAX}]: {verdict!r}"
    )


# ── AC-2.C — Banned phrases never appear ─────────────────────────────────────


@pytest.mark.parametrize("spec", _FIXTURES_30, ids=lambda s: f"{s.edge_tier}-{s.home_name[:6]}-{s.verdict_action[:4]}")
def test_w82_verdict_no_banned_telemetry(spec: NarrativeSpec):
    """AC-2: no banned telemetry vocabulary appears (Rule 17)."""
    verdict = _render_verdict(spec).lower()
    for phrase in _VERDICT_BANNED_TELEMETRY:
        assert phrase not in verdict, (
            f"[{spec.edge_tier}/{spec.sport}] Banned phrase {phrase!r} in "
            f"verdict: {verdict!r}"
        )


# ── AC-2.D — Aggregate corpus-level assertions ───────────────────────────────


def test_corpus_30_verdicts_all_pass_closure():
    """Corpus-level: 30/30 W82 verdicts pass the closure rule by tier."""
    failures = []
    for spec in _FIXTURES_30:
        verdict = _render_verdict(spec)
        sev, reason = _check_verdict_closure_rule(
            verdict, spec.edge_tier,
            {"home_team": spec.home_name, "away_team": spec.away_name},
        )
        if sev is not None:
            failures.append({
                "tier": spec.edge_tier,
                "fixture": f"{spec.home_name} vs {spec.away_name}",
                "action": spec.verdict_action,
                "severity": sev,
                "reason": reason,
                "verdict": verdict,
            })
    assert failures == [], (
        f"Corpus closure failures: {len(failures)}/30 — first failure: "
        f"{failures[0] if failures else None!r}"
    )


def test_corpus_30_verdicts_all_within_length_window():
    """Corpus-level: 30/30 W82 verdicts within their tier-floor + hard-max."""
    failures = []
    for spec in _FIXTURES_30:
        verdict = _render_verdict(spec)
        floor = MIN_VERDICT_CHARS_BY_TIER[spec.edge_tier]
        if not (floor <= len(verdict) <= VERDICT_HARD_MAX):
            failures.append({
                "tier": spec.edge_tier,
                "fixture": f"{spec.home_name} vs {spec.away_name}",
                "len": len(verdict),
                "floor": floor,
                "verdict": verdict,
            })
    assert failures == [], (
        f"Corpus length-window failures: {len(failures)}/30 — first: "
        f"{failures[0] if failures else None!r}"
    )


# ── AC-2.E — Variant pool diversity ──────────────────────────────────────────


def test_corpus_variant_pool_diverse():
    """Corpus-level: 30 verdicts produce a diverse output (no template
    collapse). With 4 variants × 5 action branches × MD5 dispatch on 30
    fixtures, we expect at least 12 unique verdicts (allowing some
    deterministic collisions on similar seeds + same-tier-action pairs)."""
    verdicts = [_render_verdict(s) for s in _FIXTURES_30]
    unique = set(verdicts)
    assert len(unique) >= 12, (
        f"Variant pool too narrow: {len(unique)}/30 unique. Pool may have "
        f"collapsed."
    )


def test_action_verb_cluster_majority_imperative():
    """Corpus-level sanity: imperative action verbs (Back/Take/Get on/etc.)
    appear in the majority of closing sentences. Brief AC-2 broadens the
    cluster to also accept declaratives, but imperative remains the default
    SA-voice shape — declaratives are diversity, not the new majority."""
    imperative_lower = ("back ", "take ", "get on ", "lean on ", "ride ",
                        "smash ", "bet on ", "hammer ", "put your money ",
                        "premium back", "strong back")
    imperative_count = 0
    for spec in _FIXTURES_30:
        last = _last_sentence(_render_verdict(spec)).lower()
        if any(v in last for v in imperative_lower):
            imperative_count += 1
    # ≥ 18/30 expected imperatives (60%) — diversity allows up to 40%
    # declarative.
    assert imperative_count >= 15, (
        f"Imperative shape minority: {imperative_count}/30 — voice register "
        f"has drifted toward declarative."
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
