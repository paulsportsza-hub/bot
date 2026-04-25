"""FIX-PREGEN-SETUP-PRICING-LEAK-01 — Setup-section pricing-language ban.

Three layers of protection against Sonnet polish leaking decimal/odds vocabulary
into The Setup section, where the absolute-ban detector
`_find_stale_setup_patterns` (bot.py:16307) will DELETE the row.

1. Polish prompt text itself contains the STRICT BAN instructions.
2. `_validate_polish()` defensively rejects any polished output that the
   detector flags.
3. The deterministic W82 baseline never produces banned vocabulary in Setup.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ensure_scrapers_importable

ensure_scrapers_importable()


_BANNED_TOKENS = [
    "bookmaker",
    "odds",
    "price",
    "priced",
    "implied",
    "implied probability",
    "implied chance",
    "fair probability",
    "fair value",
    "expected value",
    "model reads",
]


def _minimal_pack(sport: str = "soccer", league: str = "Premier League"):
    """Build a minimal EvidencePack for prompt-rendering."""
    from evidence_pack import EvidencePack

    return EvidencePack(
        match_key="home_vs_away_2026-05-02",
        sport=sport,
        league=league,
        built_at="2026-04-25T10:00:00Z",
    )


def _minimal_spec(home: str = "Arsenal", away: str = "Fulham"):
    """Build a minimal NarrativeSpec — just what format_evidence_prompt reads."""
    from narrative_spec import NarrativeSpec

    return NarrativeSpec(
        home_name=home,
        away_name=away,
        competition="Premier League",
        sport="soccer",
        home_story_type="momentum",
        away_story_type="anonymous",
        outcome="home",
        outcome_label=f"{home} home win",
        bookmaker="Hollywoodbets",
        odds=1.85,
        ev_pct=4.5,
        fair_prob_pct=58.0,
        composite_score=62.0,
        evidence_class="lean",
        tone_band="moderate",
        verdict_action="lean",
        verdict_sizing="small stake",
        edge_tier="gold",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — polish prompt text contains the STRICT BAN block.
# ─────────────────────────────────────────────────────────────────────────────


def test_setup_instruction_contains_strict_ban_block():
    """format_evidence_prompt() Setup section must enumerate the 11 banned tokens
    + the literal phrase 'STRICT BAN'."""
    from evidence_pack import format_evidence_prompt

    prompt = format_evidence_prompt(_minimal_pack(), _minimal_spec())

    assert "STRICT BAN" in prompt, (
        "polish prompt missing 'STRICT BAN' anchor — prompt drift detected"
    )

    # Every banned token must appear inside the prompt.
    for token in _BANNED_TOKENS:
        assert token in prompt, f"banned-token '{token}' missing from polish prompt"

    # The Setup section must NOT instruct Sonnet to pivot to odds/line-movements.
    # Locate Setup-section instruction span (📋 to 🎯).
    setup_idx = prompt.find("📋 <b>The Setup</b>")
    edge_idx = prompt.find("🎯 <b>The Edge</b>")
    assert setup_idx != -1 and edge_idx != -1
    setup_block = prompt[setup_idx:edge_idx]
    assert "Do NOT pivot to odds structure or line movements" in setup_block, (
        "Setup section is missing the explicit 'Do NOT pivot to odds structure' clause"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — _validate_polish defensively rejects Setup pricing leak.
# ─────────────────────────────────────────────────────────────────────────────


def test_validate_polish_rejects_setup_pricing():
    """A polish output whose Setup contains 'implied probability of 85%' must
    be rejected by _validate_polish() (defensive gate 8a)."""
    import bot

    spec = _minimal_spec()

    # A polished output that satisfies every other validator gate (4 headers,
    # team names, bookmaker name + odds, no global banned phrases) but leaks
    # 'implied' + a decimal into The Setup. The detector's odds_in_setup branch
    # should fire; _validate_polish should return False.
    polished = (
        "📋 <b>The Setup</b>\n"
        "Arsenal arrive in form. The Elo-implied home win probability is 85% "
        "and the model reads them at 1.85.\n\n"
        "🎯 <b>The Edge</b>\n"
        "Hollywoodbets are at 1.85, fair probability 58%, EV 4.5%.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "Limited evidence depth on the away side.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Lean Arsenal at 1.85 on Hollywoodbets — small stake play with the "
        "model and tipster backing aligned, sensible exposure for a gold-tier "
        "edge with tipster consensus pulling the same way."
    )
    baseline = polished  # baseline irrelevant for this gate

    assert bot._validate_polish(polished, baseline, spec) is False, (
        "defensive Setup-pricing gate failed to reject 'implied probability of 85%'"
    )


def test_validate_polish_accepts_clean_setup():
    """Sanity guard: a polished output with clean Setup prose passes the gate."""
    import bot

    spec = _minimal_spec()

    polished = (
        "📋 <b>The Setup</b>\n"
        "Arsenal sit on 70 points with a strong recent run. Fulham are mid-table "
        "and have struggled away from home.\n\n"
        "🎯 <b>The Edge</b>\n"
        "Hollywoodbets are at 1.85, fair probability 58%, EV 4.5%.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "Limited evidence depth on the away side, so size accordingly.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Lean Arsenal at 1.85 on Hollywoodbets — small stake play with the "
        "model and tipster backing aligned, sensible exposure for a gold-tier "
        "edge with tipster consensus pulling the same way."
    )
    baseline = polished

    assert bot._validate_polish(polished, baseline, spec) is True


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — W82 baseline never produces Setup pricing leaks.
# ─────────────────────────────────────────────────────────────────────────────


_BASELINE_FIXTURES = [
    # 5 soccer
    ("soccer", "Premier League", "Arsenal", "Fulham"),
    ("soccer", "Premier League", "Liverpool", "Crystal Palace"),
    ("soccer", "La Liga", "Real Madrid", "Sevilla"),
    ("soccer", "Champions League", "Paris Saint-Germain", "Bayern Munich"),
    ("soccer", "PSL", "Mamelodi Sundowns", "Kaizer Chiefs"),
    # 5 rugby
    ("rugby", "URC", "Bulls", "Stormers"),
    ("rugby", "URC", "Sharks", "Lions"),
    ("rugby", "URC", "Edinburgh", "Sharks"),
    ("rugby", "URC", "Benetton Treviso", "Leinster"),
    ("rugby", "Super Rugby", "Crusaders", "Brumbies"),
    # 5 cricket
    ("cricket", "IPL", "Royal Challengers Bengaluru", "Gujarat Titans"),
    ("cricket", "IPL", "Mumbai Indians", "Chennai Super Kings"),
    ("cricket", "SA20", "Sunrisers Eastern Cape", "Joburg Super Kings"),
    ("cricket", "T20I", "Bangladesh", "Sri Lanka"),
    ("cricket", "Test", "Australia", "India"),
    # 5 mma
    ("mma", "UFC", "Dricus Du Plessis", "Sean Strickland"),
    ("mma", "UFC", "Islam Makhachev", "Charles Oliveira"),
    ("mma", "UFC", "Alex Pereira", "Magomed Ankalaev"),
    ("mma", "UFC", "Tom Aspinall", "Curtis Blaydes"),
    ("mma", "UFC", "Ilia Topuria", "Max Holloway"),
]


@pytest.mark.parametrize("sport,league,home,away", _BASELINE_FIXTURES)
def test_baseline_setup_never_contains_pricing(sport, league, home, away):
    """W82 deterministic baseline must never emit Setup-section pricing language.

    Regression guard: if `_render_baseline()` is changed to inject odds/bookmaker
    vocabulary into Setup, this test catches it before users do.
    """
    import bot
    from narrative_spec import build_narrative_spec, _render_baseline

    edge_data = {
        "home_team": home,
        "away_team": away,
        "league": league,
        "best_bookmaker": "Hollywoodbets",
        "best_odds": 1.85,
        "edge_pct": 4.5,
        "outcome": "home",
        "outcome_team": home,
        "confirming_signals": 2,
        "composite_score": 62.0,
        "bookmaker_count": 5,
        "stale_minutes": 0,
        "movement_direction": "neutral",
        "tipster_against": 0,
    }
    tips = [
        {
            "outcome": "home",
            "odds": 1.85,
            "bookie": "Hollywoodbets",
            "bookmaker": "Hollywoodbets",
            "ev": 4.5,
            "prob": 58.0,
            "home_team": home,
            "away_team": away,
        }
    ]

    spec = build_narrative_spec({}, edge_data, tips, sport)
    baseline = _render_baseline(spec)

    reasons = bot._find_stale_setup_patterns(baseline)
    assert reasons == [], (
        f"baseline Setup pricing leak in {sport} {home} vs {away}: {reasons}\n"
        f"--- baseline ---\n{baseline}"
    )
