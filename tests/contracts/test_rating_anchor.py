"""FIX-NARRATIVE-RATING-ANCHOR-01 — Kill fabricated Elo/Glicko-2 numbers in prose.

Covers:
  AC-2: Unit tests for _find_rating_anchor_violations (8 cases a-h).
  AC-3: _validate_polish gate 8d rejects polish containing ratings not in evidence pack.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ensure_scrapers_importable

ensure_scrapers_importable()


# ── Real-world anchor values from odds.db (used across AC-2 tests) ────────────

_ARSENAL_ANCHORS = {
    "home": {"glicko2": 1778.9, "elo": 1853.1},
    "away": {"glicko2": 1529.2, "elo": 1551.2},
}

_ZEBRE_DRAGONS_ANCHORS = {
    "home": {"glicko2": 1223.7},   # zebre
    "away": {"glicko2": 1221.3},   # dragons
}


# ── AC-2a: exact match → [] ───────────────────────────────────────────────────

def test_exact_anchor_match_passes():
    """Citing a rating that exactly matches an anchor returns []."""
    from bot import _find_rating_anchor_violations

    narrative = (
        "📋 <b>The Setup</b>\n"
        "Arsenal's Elo rating of 1853 gives them a clear advantage heading into this one."
    )
    result = _find_rating_anchor_violations(narrative, _ARSENAL_ANCHORS)
    assert result == [], f"Expected [] for exact Elo match; got {result}"


# ── AC-2b: off by 1 (within tolerance) → [] ──────────────────────────────────

def test_rating_within_tolerance_passes():
    """Citing a rating off by 1 point (within ±2 tolerance) returns []."""
    from bot import _find_rating_anchor_violations

    # 1854 vs anchor 1853.1 — diff = 0.9, within tolerance
    narrative = "Arsenal carry a rating mark of 1854 into this fixture."
    result = _find_rating_anchor_violations(narrative, _ARSENAL_ANCHORS)
    assert result == [], f"Expected [] for rating within ±2; got {result}"


# ── AC-2c: off by 5 (outside tolerance) → fabricated ─────────────────────────

def test_rating_outside_tolerance_flagged():
    """Citing a rating off by 5 points (outside ±2 tolerance) fires fabricated_rating."""
    from bot import _find_rating_anchor_violations

    # 1858 vs nearest anchor 1853.1 — diff = 4.9, outside tolerance
    narrative = "Arsenal's strength rating stands at 1858 heading into this clash."
    result = _find_rating_anchor_violations(narrative, _ARSENAL_ANCHORS)
    assert any("fabricated_rating" in r for r in result), (
        f"Expected fabricated_rating for out-of-tolerance rating; got {result}"
    )
    assert any("1858" in r for r in result), (
        f"Expected fabricated value '1858' in reason; got {result}"
    )


# ── AC-2d: 4-digit number present but no team_ratings → no_team_ratings_anchor ─

def test_no_team_ratings_anchor_fires_when_rating_cited():
    """When a 4-digit rating is cited but no team_ratings anchor is provided, returns no_team_ratings_anchor."""
    from bot import _find_rating_anchor_violations

    narrative = "Based on their ratings of 1853 and 1551, this looks like a mismatch."
    result = _find_rating_anchor_violations(narrative, None)
    assert result == ["no_team_ratings_anchor"], (
        f"Expected ['no_team_ratings_anchor']; got {result}"
    )


# ── AC-2e: cited gap matches actual gap ±2 → [] ───────────────────────────────

def test_gap_within_tolerance_passes():
    """A rating gap mentioned in narrative that matches actual gap ±2 returns []."""
    from bot import _find_rating_anchor_violations

    # Arsenal anchors: max home = 1853.1, max away = 1551.2 → actual gap = 301.9
    # Narrative mentions "1853" (passes rating check) + "302-point gap" (diff=0.1, passes gap check)
    narrative = (
        "Arsenal's Elo mark of 1853 gives them a 302-point rating gap over Fulham — "
        "that kind of differential shows up in every metric."
    )
    result = _find_rating_anchor_violations(narrative, _ARSENAL_ANCHORS)
    assert result == [], f"Expected [] for gap within ±2; got {result}"


# ── AC-2f: cited gap off by 50 → fabricated_gap ──────────────────────────────

def test_gap_outside_tolerance_flagged():
    """A rating gap that deviates from actual by >2 fires fabricated_gap."""
    from bot import _find_rating_anchor_violations

    # Narrative mentions "1853" (passes rating check — within ±2 of anchor 1853.1)
    # + "350-point gap" (actual ≈ 302, diff = 48 → outside ±2 → fabricated_gap)
    narrative = (
        "Arsenal's Elo mark of 1853 gives them a 350-point gap over Fulham — "
        "a chasm in quality that makes this a straightforward analytical call."
    )
    result = _find_rating_anchor_violations(narrative, _ARSENAL_ANCHORS)
    assert any("fabricated_gap" in r for r in result), (
        f"Expected fabricated_gap for cited gap off by 48 pts; got {result}"
    )
    assert any("350" in r for r in result), (
        f"Expected '350' in reason; got {result}"
    )


# ── AC-2g: no rating mentions → [] ───────────────────────────────────────────

def test_no_rating_mentions_returns_empty_list():
    """Narrative with no 4-digit rating numbers returns [] regardless of anchors."""
    from bot import _find_rating_anchor_violations

    narrative = (
        "Arsenal have been dominant at home this season, winning six straight. "
        "Fulham hold solid mid-table form and will make this competitive."
    )
    result = _find_rating_anchor_violations(narrative, _ARSENAL_ANCHORS)
    assert result == [], f"Expected [] when no ratings cited; got {result}"


# ── AC-2h: no team_ratings, no rating mentions → [] ──────────────────────────

def test_no_ratings_no_anchor_returns_empty_list():
    """Cricket/MMA narrative with no team_ratings provided and no rating mentions returns []."""
    from bot import _find_rating_anchor_violations

    mma_narrative = (
        "This title contender fight pits two elite middleweights against each other. "
        "The stylistic matchup should produce an explosive encounter in the later rounds."
    )
    result = _find_rating_anchor_violations(mma_narrative, None)
    assert result == [], (
        f"Expected [] when no ratings cited and no anchor provided; got {result}"
    )


# ── AC-2 bonus: zebre/dragons known fabrication catches real case ─────────────

def test_zebre_dragons_fabricated_values_caught():
    """The concrete zebre/dragons fabrication ('1209 vs 1145') is caught correctly."""
    from bot import _find_rating_anchor_violations

    # The actual fabricated values from the bug report — neither matches zebre(1223.7)/dragons(1221.3)
    narrative = (
        "Zebre hold a 1209 rating compared to Dragons' 1145 — "
        "the numbers suggest a narrow home advantage."
    )
    result = _find_rating_anchor_violations(narrative, _ZEBRE_DRAGONS_ANCHORS)
    assert any("fabricated_rating" in r for r in result), (
        f"Expected fabricated_rating for 1209/1145 vs anchors 1223.7/1221.3; got {result}"
    )


# ── AC-2 bonus: _RATING_TOLERANCE constant is exactly 2.0 ────────────────────

def test_rating_tolerance_constant_value():
    """_RATING_TOLERANCE must be exactly 2.0 (calibration starting point)."""
    from bot import _RATING_TOLERANCE

    assert _RATING_TOLERANCE == 2.0, (
        f"_RATING_TOLERANCE should be 2.0; got {_RATING_TOLERANCE}"
    )


# ── AC-2 bonus: empty team_ratings dict → no_team_ratings_anchor ─────────────

def test_empty_anchors_dict_fires_no_anchor():
    """Empty team_ratings dict with a cited rating fires no_team_ratings_anchor."""
    from bot import _find_rating_anchor_violations

    result = _find_rating_anchor_violations("Arsenal's rating of 1853 is impressive.", {})
    assert result == ["no_team_ratings_anchor"], (
        f"Expected ['no_team_ratings_anchor'] for empty anchors dict; got {result}"
    )


# ── AC-3: _validate_polish gate 8d rejects fabricated ratings ─────────────────

def test_validate_polish_rejects_fabricated_ratings():
    """Gate 8d: _validate_polish returns False when cited ratings don't match evidence pack.

    The narrative cites Arsenal's Elo values (1853 vs 1551) but the evidence pack
    only provides Glicko-2 values (1778.9 vs 1529.2). Neither cited number is within
    ±2 of any anchor → gate 8d fires → _validate_polish returns False.
    """
    import bot
    from narrative_spec import NarrativeSpec

    spec = NarrativeSpec(
        home_name="Arsenal",
        away_name="Fulham",
        competition="Premier League",
        sport="soccer",
        home_story_type="momentum",
        away_story_type="anonymous",
        outcome="home",
        outcome_label="Arsenal home win",
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

    # Narrative cites Elo values (1853, 1551) but evidence pack only has Glicko-2
    # anchors (1778.9, 1529.2). Both cited numbers are >2 pts away from all anchors.
    polished = (
        "📋 <b>The Setup</b>\n"
        "Arsenal head into this as the stronger side on ratings, with an Elo mark of 1853 "
        "compared to Fulham's 1551 — a meaningful gap that shows up across the home record "
        "this season. Arteta's men have controlled Premier League games from front to back.\n\n"
        "🎯 <b>The Edge</b>\n"
        "Hollywoodbets price Arsenal home at 1.85. At a fair probability of 58%, that is a "
        "lean-tier expected value gap of 4.5% — enough to back at small stake.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "The Saka fitness concern is real — Arsenal's attacking creativity drops without "
        "their main creator in the wide channels on the left flank.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Discount the Saka fitness concern — Arsenal have sufficient cover. "
        "Back Arteta's side at 1.85 with Hollywoodbets, small stake on a lean edge "
        "supported by a significant ratings advantage over Fulham here."
    )
    # baseline = polished ensures gates 9/11/12 trivially pass (no new names introduced)
    baseline = polished

    evidence_pack = {
        "team_ratings": {
            "home": {"glicko2": 1778.9},   # Arsenal Glicko-2 only
            "away": {"glicko2": 1529.2},   # Fulham Glicko-2 only
        }
    }

    result = bot._validate_polish(polished, baseline, spec, evidence_pack=evidence_pack)
    assert result is False, (
        "_validate_polish must reject polish containing Elo values (1853, 1551) "
        "when evidence pack only anchors Glicko-2 values (1778.9, 1529.2)"
    )


# ── AC-3 control: correct anchors pass gate 8d ───────────────────────────────

def test_validate_polish_passes_when_ratings_match_anchors():
    """Gate 8d: _validate_polish returns True when cited ratings match evidence pack anchors."""
    import bot
    from narrative_spec import NarrativeSpec

    spec = NarrativeSpec(
        home_name="Arsenal",
        away_name="Fulham",
        competition="Premier League",
        sport="soccer",
        home_story_type="momentum",
        away_story_type="anonymous",
        outcome="home",
        outcome_label="Arsenal home win",
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

    # Narrative cites Elo values (1853, 1551) and evidence pack includes those exact Elo anchors
    polished = (
        "📋 <b>The Setup</b>\n"
        "Arsenal head into this as the stronger side on ratings, with an Elo mark of 1853 "
        "compared to Fulham's 1551 — a meaningful gap that shows up across the home record "
        "this season. Arteta's men have controlled Premier League games from front to back.\n\n"
        "🎯 <b>The Edge</b>\n"
        "Hollywoodbets price Arsenal home at 1.85. At a fair probability of 58%, that is a "
        "lean-tier expected value gap of 4.5% — enough to back at small stake.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "The Saka fitness concern is real — Arsenal's attacking creativity drops without "
        "their main creator in the wide channels on the left flank.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Discount the Saka fitness concern — Arsenal have sufficient cover. "
        "Back Arteta's side at 1.85 with Hollywoodbets, small stake on a lean edge "
        "supported by a significant ratings advantage over Fulham here."
    )
    baseline = polished

    # Evidence pack includes BOTH Glicko-2 and Elo — 1853 matches Elo anchor 1853.1 (diff=0.1)
    evidence_pack = {
        "team_ratings": {
            "home": {"glicko2": 1778.9, "elo": 1853.1},
            "away": {"glicko2": 1529.2, "elo": 1551.2},
        }
    }

    result = bot._validate_polish(polished, baseline, spec, evidence_pack=evidence_pack)
    assert result is True, (
        "_validate_polish must pass when cited Elo values (1853, 1551) match "
        "evidence pack Elo anchors (1853.1, 1551.2) within ±2 tolerance"
    )
