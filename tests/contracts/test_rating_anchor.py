
import pytest
pytest.skip(
    "FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: Sonnet/Haiku polish ripped out. "
    "This test asserts polish-chain behaviour that no longer exists.",
    allow_module_level=True,
)

"""FIX-NARRATIVE-RATING-ANCHOR-01 — Kill fabricated Elo/Glicko-2 numbers in prose.

Covers:
  AC-2: Unit tests for _find_rating_anchor_violations (8 cases a-h).
  AC-3: _validate_polish gate 8d rejects polish containing ratings not in evidence pack.
"""

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
    """Citing a rating clearly outside ±5 tolerance fires fabricated_rating.

    Fixture data updated under FIX-NARRATIVE-RATING-TOLERANCE-WIDEN-01 (2026-04-27)
    when _RATING_TOLERANCE widened 2.0→5.0: 1858 (diff=4.9) is now within tolerance,
    so this test uses 1860 (diff=6.9) to retain its out-of-tolerance assertion.
    """
    from bot import _find_rating_anchor_violations

    # 1860 vs nearest anchor 1853.1 — diff = 6.9, outside ±5 tolerance
    narrative = "Arsenal's strength rating stands at 1860 heading into this clash."
    result = _find_rating_anchor_violations(narrative, _ARSENAL_ANCHORS)
    assert any("fabricated_rating" in r for r in result), (
        f"Expected fabricated_rating for out-of-tolerance rating; got {result}"
    )
    assert any("1860" in r for r in result), (
        f"Expected fabricated value '1860' in reason; got {result}"
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


# ── _RATING_TOLERANCE constant pinned to 5.0 (FIX-NARRATIVE-RATING-TOLERANCE-WIDEN-01)

def test_rating_tolerance_constant_value():
    """_RATING_TOLERANCE must be exactly 5.0 (regression guard against accidental tightening).

    Locked under FIX-NARRATIVE-RATING-TOLERANCE-WIDEN-01 (2026-04-27): widened from
    the original 2.0 (FIX-RATING-01 baseline) to absorb daily Glicko-2 cron drift on
    stable team ratings. CLAUDE.md Rule 10 forbids tightening below 5.0 without
    monitoring evidence of false-fabrication rate < 1% across a 7-day window.
    """
    from bot import _RATING_TOLERANCE

    assert _RATING_TOLERANCE == 5.0, (
        f"_RATING_TOLERANCE should be 5.0 (FIX-NARRATIVE-RATING-TOLERANCE-WIDEN-01); "
        f"got {_RATING_TOLERANCE}"
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


# ─────────────────────────────────────────────────────────────────────────────
# FIX-NARRATIVE-RATING-TOLERANCE-WIDEN-01 (2026-04-27): widened tolerance ±2→±5
# to absorb daily Glicko-2 cron drift on stable team ratings.
# Brief: https://www.notion.so/34fd9048d73c81078fc8d0a303d3952a
# Predecessor: FIX-NARRATIVE-RATING-PROMPT-PLACEHOLDER-01 (Finding B).
# ─────────────────────────────────────────────────────────────────────────────


def test_rating_within_5pt_drift_passes():
    """A cited rating 5 points off the anchor must pass at the new ±5 tolerance.

    Calibration anchor: ±5.0 absorbs ~one Glicko-2 daily cron cycle on stable teams
    (5–15pt average shift per parent INV-NARRATIVE-AUDIT-LAUNCH-DAY-01). 1858 cited
    against 1853 anchor → diff = 5.0 → helper uses `> _RATING_TOLERANCE` so 5.0pt
    is precisely on the no-flag side of the boundary.
    """
    from bot import _find_rating_anchor_violations

    anchors = {"home": {"glicko2": 1853.0}, "away": {"glicko2": 1500.0}}
    narrative = "Arsenal carry a Glicko-2 mark of 1858 into this fixture."
    result = _find_rating_anchor_violations(narrative, anchors)
    assert result == [], (
        f"5pt drift (cited 1858 vs anchor 1853) must pass under widened ±5 tolerance; "
        f"got {result}"
    )


def test_rating_off_by_10pt_fires():
    """A cited rating 10 points off all anchors must still fire fabricated_rating.

    Confirms the widening preserves catch-rate on genuine fabrications. INV cases
    were 50+ pt deltas — 10pt is comfortably above the ±5 threshold.
    """
    from bot import _find_rating_anchor_violations

    anchors = {"home": {"glicko2": 1858.0}, "away": {"glicko2": 1500.0}}
    narrative = "Arsenal head into this with a Glicko-2 rating of 1868 — a clear edge."
    result = _find_rating_anchor_violations(narrative, anchors)
    assert any("fabricated_rating" in r for r in result), (
        f"10pt drift (cited 1868 vs anchor 1858) must still fire fabricated_rating; "
        f"got {result}"
    )
    assert any("1868" in r for r in result), (
        f"Expected fabricated value '1868' in reason list; got {result}"
    )


def test_rating_widening_calibration_boundary():
    """Boundary smoke test: 4pt drift passes, 6pt drift fires.

    Validates the ±5 boundary holds in both directions:
      - 4.0pt diff → no flag (within tolerance)
      - 6.0pt diff → fabricated_rating (outside tolerance)
    Catches accidental off-by-one regressions in the comparison operator.
    """
    from bot import _find_rating_anchor_violations

    anchors = {"home": {"glicko2": 1850.0}, "away": {"glicko2": 1500.0}}

    # 4pt drift — must pass
    within = _find_rating_anchor_violations(
        "Arsenal sit on a Glicko-2 reading of 1854 entering this fixture.", anchors
    )
    assert within == [], f"4pt drift must pass at ±5 tolerance; got {within}"

    # 6pt drift — must fire
    outside = _find_rating_anchor_violations(
        "Arsenal sit on a Glicko-2 reading of 1856 entering this fixture.", anchors
    )
    assert any("fabricated_rating" in r for r in outside), (
        f"6pt drift must fire fabricated_rating at ±5 tolerance; got {outside}"
    )


def test_no_literal_arsenal_elo_in_prompt():
    """Permanent regression guard against literal Arsenal Elo values in prompts.

    Per VERIFY's caveat #1 from the predecessor brief
    (FIX-NARRATIVE-RATING-PROMPT-PLACEHOLDER-01): renders format_evidence_prompt()
    for both branches (edge + match_preview) across 5 non-Arsenal fixtures spanning
    soccer (EPL/PSL/La Liga/UCL) and rugby (URC), and asserts the rendered string
    contains zero '1853' / '1551' substrings. The historical bug: the prompt
    example phrase '1853 vs 1551' was Arsenal's literal Elo values; Sonnet copied
    these to other matches. Anchor block is now built per-fixture from team_ratings
    DB, but a future cargo-cult re-introduction would resurface the leak. This
    test is the canary.
    """
    import datetime as dt
    from types import SimpleNamespace

    from evidence_pack import EvidencePack, format_evidence_prompt

    fixtures = [
        ("liverpool_vs_manchester_city_2026-05-02", "soccer", "EPL"),
        ("orlando_pirates_vs_kaizer_chiefs_2026-05-03", "soccer", "PSL"),
        ("real_madrid_vs_barcelona_2026-05-04", "soccer", "La Liga"),
        ("paris_saint_germain_vs_bayern_munich_2026-05-05", "soccer", "Champions League"),
        ("bulls_vs_stormers_2026-05-06", "rugby", "URC"),
    ]
    banned = ("1853", "1551")

    for match_key, sport, league in fixtures:
        home_key, rest = match_key.split("_vs_", 1)
        away_key = rest.rsplit("_", 1)[0]
        spec = SimpleNamespace(
            home_name=home_key.replace("_", " ").title(),
            away_name=away_key.replace("_", " ").title(),
            sport=sport,
            competition=league,
            bookmaker="Betway",
            odds=1.85,
            verdict_action="lean back",
            verdict_sizing="moderate",
            evidence_class="supported",
            tone_band="moderate",
            edge_tier="gold",
            sa_tag="lean",
            h2h_history="No prior meetings",
        )
        pack = EvidencePack(
            match_key=match_key,
            sport=sport,
            league=league,
            built_at=dt.datetime.now(dt.timezone.utc).isoformat(),
            richness_score="medium",
            sources_available=4,
            sources_total=8,
        )

        for preview in (False, True):
            prompt = format_evidence_prompt(pack, spec, match_preview=preview)
            assert isinstance(prompt, str), (
                f"format_evidence_prompt must return str for {match_key} preview={preview}"
            )
            for literal in banned:
                assert literal not in prompt, (
                    f"Banned literal {literal!r} must not appear in {match_key} "
                    f"(preview={preview}). This regression is the cargo-cult Arsenal "
                    f"Elo leak from FIX-NARRATIVE-RATING-PROMPT-PLACEHOLDER-01."
                )
