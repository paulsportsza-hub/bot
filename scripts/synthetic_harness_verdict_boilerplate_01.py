"""FIX-NARRATIVE-BOILERPLATE-VERDICT-TEMPLATE-01 synthetic harness (HG-1, AC-7).

Renders 4 tiers (Bronze/Silver/Gold/Diamond) × 5 sports (soccer/rugby/cricket/
combat/cricket_t20) = 20 fixtures via _render_baseline() / _render_verdict()
and dumps each evidence file plus a summary.json under
reports/e2e-screenshots/FIX-NARRATIVE-BOILERPLATE-VERDICT-TEMPLATE-01-*.

Asserts:
  - boilerplate_substring_count == 0 across all 20 fixtures
  - "supporting indicator sit" never appears
  - all 4 tiers cite team / EV% / odds / bookmaker

Run from /home/paulsportsza/bot:
  .venv/bin/python scripts/synthetic_harness_verdict_boilerplate_01.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from narrative_spec import (  # noqa: E402
    NarrativeSpec,
    _render_baseline,
    _render_verdict,
)


_FORBIDDEN_PHRASES = (
    "supporting indicator sit",
)

# 4 tier configs aligned to verdict_action / tone_band / evidence_class
_TIER_CONFIG = {
    "bronze":  ("speculative punt", "tiny exposure",   "speculative", "cautious",  1, 3.5),
    "silver":  ("lean",             "small stake",     "lean",        "moderate",  2, 4.5),
    "gold":    ("back",             "standard stake",  "supported",   "confident", 3, 8.0),
    "diamond": ("strong back",      "confident stake", "conviction",  "strong",    4, 15.5),
}

_FIXTURES = [
    # (sport, home, away, league, outcome_label, bookmaker, odds, risk_factor)
    ("soccer",  "Arsenal",          "Chelsea",         "Premier League",
     "Arsenal win",          "Hollywoodbets", 1.85,
     "Form data is thin from a 3-game window. Tipster consensus is unavailable."),
    ("rugby",   "Bulls",            "Stormers",        "URC",
     "Bulls win",            "Betway",        1.75,
     "Squad rotation is the main concern after midweek travel."),
    ("cricket", "Bangladesh",       "New Zealand",     "ICC ODI",
     "New Zealand win",      "WSB",           2.10,
     "Toss-dependent conditions could swing the match early."),
    ("combat",  "Dricus Du Plessis","Khamzat Chimaev", "UFC",
     "Du Plessis win",       "SuperSportBet", 2.30,
     "Stylistic matchup uncertainty — wrestling vs striking."),
    ("cricket", "Punjab Kings",     "Rajasthan Royals","IPL",
     "Punjab Kings win",     "Supabets",      1.88,
     "Pitch report flagged variable bounce — unusual for the venue."),
]


_OUT_DIR = Path("/home/paulsportsza/reports/e2e-screenshots")
_PREFIX = "FIX-NARRATIVE-BOILERPLATE-VERDICT-TEMPLATE-01-"


def _build_spec(tier: str, fixture: tuple) -> NarrativeSpec:
    sport, home, away, league, outcome_label, bk, odds, risk = fixture
    action, sizing, ec, tone, support, ev = _TIER_CONFIG[tier]
    return NarrativeSpec(
        home_name=home, away_name=away,
        competition=league, sport=sport,
        home_story_type="neutral", away_story_type="neutral",
        evidence_class=ec, tone_band=tone,
        verdict_action=action, verdict_sizing=sizing,
        outcome="home" if outcome_label.startswith(home) else "away",
        outcome_label=outcome_label,
        bookmaker=bk, odds=odds, ev_pct=ev,
        fair_prob_pct=100.0 / odds,
        composite_score=50.0 + ev * 2,
        bookmaker_count=4, support_level=support, contradicting_signals=0,
        risk_factors=[risk], risk_severity="moderate",
        stale_minutes=0, movement_direction="neutral", tipster_against=0,
        edge_tier=tier,
    )


def _check_fixture_data(verdict: str, fixture: tuple, ev: float) -> dict:
    """Returns dict of per-check results."""
    _sport, home, away, _league, outcome_label, bk, odds, _ = fixture
    # Match team via outcome_label tokens (handles surnames in combat sports
    # where outcome_label="Du Plessis win" but home="Dricus Du Plessis").
    label_tokens = [t for t in re.findall(r"[A-Za-z]+", outcome_label) if t.lower() != "win"]
    team_token = " ".join(label_tokens) or home
    ev_int = int(round(ev))
    return {
        "cites_team": team_token.lower() in verdict.lower(),
        "cites_odds": f"{odds:.2f}" in verdict,
        "cites_bookmaker": bk in verdict,
        "cites_ev_int": (f"+{ev_int}%" in verdict) or (f"{ev:.1f}%" in verdict),
        "boilerplate_count": sum(verdict.lower().count(p) for p in _FORBIDDEN_PHRASES),
        "singular_indicator_sit_pattern": bool(
            re.search(r"\b\d+\s+supporting\s+indicator(?!s)\s+sit\b", verdict.lower())
        ),
    }


def main() -> int:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    rendered: list[dict] = []
    overall_pass = True
    boilerplate_count_total = 0

    for tier in ("bronze", "silver", "gold", "diamond"):
        for fx in _FIXTURES:
            sport = fx[0]
            spec = _build_spec(tier, fx)
            verdict = _render_verdict(spec)
            baseline = _render_baseline(spec)
            checks = _check_fixture_data(verdict, fx, _TIER_CONFIG[tier][5])
            boilerplate_count_total += checks["boilerplate_count"]
            fixture_pass = (
                checks["boilerplate_count"] == 0
                and not checks["singular_indicator_sit_pattern"]
                and checks["cites_team"]
                and checks["cites_odds"]
                and checks["cites_bookmaker"]
                and checks["cites_ev_int"]
            )
            if not fixture_pass:
                overall_pass = False

            slug = f"{tier}-{sport}-{fx[1].lower().replace(' ', '_')}-{fx[2].lower().replace(' ', '_')}"
            evidence_path = _OUT_DIR / f"{_PREFIX}{slug}.txt"
            evidence_path.write_text(
                "=" * 72 + "\n"
                f"FIX-NARRATIVE-BOILERPLATE-VERDICT-TEMPLATE-01 — synthetic render\n"
                f"timestamp:  {timestamp}\n"
                f"tier:       {tier}\n"
                f"sport:      {sport}\n"
                f"fixture:    {fx[1]} vs {fx[2]} ({fx[3]})\n"
                f"odds:       {fx[6]} ({fx[5]})\n"
                f"ev:         {_TIER_CONFIG[tier][5]}\n"
                + "=" * 72 + "\n\n"
                + "VERDICT (rendered):\n" + verdict + "\n\n"
                + "BASELINE (4-section narrative, last 1200 chars):\n"
                + baseline[-1200:] + "\n\n"
                + "ASSERTIONS:\n"
                + json.dumps(checks, indent=2) + "\n\n"
                + f"PASS: {fixture_pass}\n"
            )
            rendered.append({
                "tier": tier,
                "sport": sport,
                "fixture": f"{fx[1]} vs {fx[2]}",
                "verdict": verdict,
                "checks": checks,
                "pass": fixture_pass,
                "evidence_file": evidence_path.name,
            })

    summary = {
        "brief": "FIX-NARRATIVE-BOILERPLATE-VERDICT-TEMPLATE-01",
        "timestamp": timestamp,
        "fixture_count": len(rendered),
        "tiers": ["bronze", "silver", "gold", "diamond"],
        "sports": sorted(list({fx[0] for fx in _FIXTURES})),
        "boilerplate_substring_count": boilerplate_count_total,
        "overall_pass": overall_pass,
        "fixtures": rendered,
    }
    summary_path = _OUT_DIR / f"{_PREFIX}summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))

    print(f"Wrote {len(rendered) + 1} evidence files to {_OUT_DIR}")
    print(f"Boilerplate substring count: {boilerplate_count_total}")
    print(f"Overall pass: {overall_pass}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
