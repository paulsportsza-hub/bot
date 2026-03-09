"""Comprehensive tests for the game breakdown quality gate system.

Tests cover:
- _validate_breakdown: terse detection, empty section detection, sentence counting
- _build_programmatic_narrative: rich output from verified data
- _format_verified_context: last 5 scores, all fields present
- Integration: validator + fallback produce acceptable output
"""

import pytest
import re
import sys
import os

# Ensure bot module is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bot import (
    _validate_breakdown,
    _build_programmatic_narrative,
    _format_verified_context,
    sanitize_ai_response,
)


# ── Sample data ──

RICH_CTX = {
    "data_available": True,
    "sport": "soccer",
    "league": "English Premier League",
    "league_key": "epl",
    "venue": "Molineux Stadium, Wolverhampton",
    "home_team": {
        "name": "Wolverhampton Wanderers",
        "espn_id": "380",
        "coach": "Rob Edwards",
        "league_position": 20,
        "points": 13,
        "games_played": 29,
        "record": "2-7-20",
        "form": "WLDDL",
        "last_5": [
            {"opponent": "Aston Villa", "result": "W", "score": "2-0",
             "home_away": "home"},
            {"opponent": "Crystal Palace", "result": "L", "score": "0-1",
             "home_away": "away"},
            {"opponent": "Arsenal", "result": "D", "score": "2-2",
             "home_away": "home"},
        ],
        "top_scorer": {"name": "Arokodare", "goals": 2},
        "goals_per_game": 1.0,
        "conceded_per_game": 1.2,
        "home_record": "W2 D3 L10",
        "away_record": "W0 D4 L10",
        "goals_for": 20,
        "goals_against": 51,
        "goal_difference": -31,
    },
    "away_team": {
        "name": "Liverpool",
        "espn_id": "364",
        "coach": "A. Slot",
        "league_position": 5,
        "points": 48,
        "games_played": 28,
        "record": "14-6-8",
        "form": "WWWLW",
        "last_5": [
            {"opponent": "West Ham", "result": "W", "score": "5-2",
             "home_away": "home"},
            {"opponent": "Forest", "result": "W", "score": "1-0",
             "home_away": "away"},
            {"opponent": "Sunderland", "result": "W", "score": "1-0",
             "home_away": "away"},
        ],
        "top_scorer": {"name": "Ekitike", "goals": 11},
        "goals_per_game": 2.4,
        "conceded_per_game": 1.0,
        "home_record": "W8 D3 L3",
        "away_record": "W6 D3 L5",
        "goals_for": 47,
        "goals_against": 37,
        "goal_difference": 10,
    },
    "head_to_head": [
        {"date": "2025-02-16", "home": "Liverpool", "away": "Wolverhampton Wanderers",
         "score": "2-1"},
        {"date": "2024-09-28", "home": "Wolverhampton Wanderers", "away": "Liverpool",
         "score": "1-2"},
    ],
}

CRICKET_CTX = {
    "data_available": True,
    "sport": "cricket",
    "league": "T20 World Cup",
    "league_key": "t20_world_cup",
    "venue": "Eden Gardens, Kolkata",
    "home_team": {
        "name": "South Africa",
        "league_position": 1,
        "wins": 3,
        "losses": 0,
        "points": 6,
        "nrr": 2.259,
        "matches_played": 3,
        "coach": "Shukri Conrad",
    },
    "away_team": {
        "name": "New Zealand",
        "league_position": 2,
        "wins": 1,
        "losses": 1,
        "points": 3,
        "nrr": 1.39,
        "matches_played": 3,
        "coach": "Rob Walter",
    },
    "head_to_head": None,
}

SAMPLE_TIPS = [
    {"outcome": "Wolves", "odds": 6.30, "bookie": "GBets",
     "ev": 5.5, "prob": 17},
    {"outcome": "Draw", "odds": 4.85, "bookie": "SSB",
     "ev": 5.7, "prob": 22},
    {"outcome": "Liverpool", "odds": 1.52, "bookie": "SupaBets",
     "ev": 1.3, "prob": 67},
]

# ── Terse (BAD) output examples ──

TERSE_OUTPUT = """📋 <b>The Setup</b>
Wolverhampton Wanderers: 20th on 13 points from 29 games, record 2-7-20, form WLDDL, 1.0 goals/game, under Rob Edwards.
Liverpool: 5th on 48 points from 28 games, record 14-6-8, form WWWLW, 2.4 goals/game, under A. Slot.

🎯 <b>The Edge</b>

⚠️ <b>The Risk</b>
Liverpool might rest players.

🏆 <b>Verdict</b>
Back the draw."""

TERSE_OUTPUT_2 = """📋 <b>The Setup</b>
South Africa: 1st on 6 points, 3W-0L, NRR +2.259, under Shukri Conrad.
New Zealand: under Rob Walter.

🎯 <b>The Edge</b>
Some edge analysis here.

⚠️ <b>The Risk</b>
Weather could play a role.

🏆 <b>Verdict</b>
Back South Africa."""

# ── Good (PASS) output examples ──

GOOD_OUTPUT = """📋 <b>The Setup</b>
Liverpool head to Molineux sitting 5th on 48 points, with Arne Slot's side riding
a three-game winning streak including a ruthless 5-2 demolition of West Ham.
Hugo Ekitike leads the line with 11 goals, and the 4-2-3-1 has been devastating.
Wolves are rock bottom on 13 points and haven't won away all season (W0 D4 L10),
though Rob Edwards' men did nick a shock 2-0 against Villa last time out.
Liverpool have won both recent H2H meetings, and key concern is Frimpong
and Gravenberch flagged as injury doubts.

🎯 <b>The Edge</b>
The best value sits with the Draw at 4.85 (SuperSportBet), carrying +5.7% EV
against a 22% implied probability. Wolves at 6.30 also offer decent value at
+5.5% EV with GBets leading the market.

⚠️ <b>The Risk</b>
Liverpool's injury list could be overblown — they've got enough quality in depth.

🏆 <b>Verdict</b>
Back the Draw at 4.85 for genuine value against vulnerable Liverpool."""


# ═══════════════════════════════════════════════════════════════════════════
# Tests for _validate_breakdown
# ═══════════════════════════════════════════════════════════════════════════

class TestValidateBreakdown:
    """Tests for the quality gate validator."""

    def test_good_output_passes(self):
        passed, issues = _validate_breakdown(GOOD_OUTPUT, RICH_CTX)
        assert passed is True
        assert issues == []

    def test_terse_setup_detected(self):
        passed, issues = _validate_breakdown(TERSE_OUTPUT, RICH_CTX)
        assert passed is False
        assert "TERSE_SETUP" in issues

    def test_terse_cricket_detected(self):
        """Cricket terse format (stats + coach-only lines) should fail."""
        passed, issues = _validate_breakdown(TERSE_OUTPUT_2, CRICKET_CTX)
        assert passed is False
        # Should detect terse (stats line) or short setup or empty edge
        assert "TERSE_SETUP" in issues or "SHORT_SETUP" in issues

    def test_empty_edge_detected(self):
        passed, issues = _validate_breakdown(TERSE_OUTPUT, RICH_CTX)
        assert "EMPTY_EDGE" in issues

    def test_short_setup_detected(self):
        short = """📋 <b>The Setup</b>
Two teams play football.

🎯 <b>The Edge</b>
Liverpool are value at these odds with strong EV percentages.

⚠️ <b>The Risk</b>
Could go either way.

🏆 <b>Verdict</b>
Back Liverpool."""
        passed, issues = _validate_breakdown(short, RICH_CTX)
        assert passed is False
        assert "SHORT_SETUP" in issues

    def test_missing_section_detected(self):
        no_edge = """📋 <b>The Setup</b>
A detailed multi-sentence narrative paragraph about the match that weaves
standings and form and coaches together into a compelling story. Liverpool
are flying high. Wolves are struggling badly.

⚠️ <b>The Risk</b>
Could go either way.

🏆 <b>Verdict</b>
Back Liverpool."""
        passed, issues = _validate_breakdown(no_edge, RICH_CTX)
        assert passed is False
        assert "MISSING_🎯" in issues

    def test_no_data_fails(self):
        passed, issues = _validate_breakdown("NO_DATA", {})
        assert passed is False
        assert "NO_NARRATIVE" in issues

    def test_empty_string_fails(self):
        passed, issues = _validate_breakdown("", {})
        assert passed is False

    def test_none_fails(self):
        passed, issues = _validate_breakdown(None, {})
        assert passed is False

    def test_long_narrative_paragraph_passes(self):
        """A proper narrative with 5+ sentences should pass."""
        good = """📋 <b>The Setup</b>
Liverpool head to Molineux sitting 5th on 48 points after a dominant run of form.
Arne Slot's side have won three of their last four including a 5-2 demolition of
West Ham that showcased their attacking firepower. Hugo Ekitike leads the scoring
charts with 11 goals and has been in devastating form. Wolves are rooted to the
bottom on just 13 points with a goal difference of -31. Rob Edwards' men did
manage a shock 2-0 win over Villa last time out, proving they can still surprise.
The two sides last met in February 2025 with Liverpool winning 2-1.

🎯 <b>The Edge</b>
The draw at 4.85 from SuperSportBet carries a healthy +5.7% edge. With Liverpool's
injury concerns and Wolves' desperation at the bottom, this could go sideways.

⚠️ <b>The Risk</b>
Liverpool have enough quality to steamroll Wolves even with injuries.

🏆 <b>Verdict</b>
Back the draw at 4.85 for value."""
        passed, issues = _validate_breakdown(good, RICH_CTX)
        assert passed is True, f"Should pass but got: {issues}"


# ═══════════════════════════════════════════════════════════════════════════
# Tests for _build_programmatic_narrative
# ═══════════════════════════════════════════════════════════════════════════

class TestProgrammaticNarrative:
    """Tests for the programmatic fallback narrative builder."""

    def test_produces_all_sections(self):
        result = _build_programmatic_narrative(RICH_CTX, SAMPLE_TIPS, "soccer")
        assert "📋" in result
        assert "🎯" in result
        assert "⚠️" in result
        assert "🏆" in result

    def test_includes_team_names(self):
        result = _build_programmatic_narrative(RICH_CTX, SAMPLE_TIPS, "soccer")
        assert "Wolverhampton Wanderers" in result
        assert "Liverpool" in result

    def test_includes_standings(self):
        result = _build_programmatic_narrative(RICH_CTX, SAMPLE_TIPS, "soccer")
        assert "20th" in result or "20" in result
        assert "5th" in result or "48 points" in result

    def test_includes_coaches(self):
        # W80-PROSE: last-name-only coach references ("Edwards'" / "Slot has them")
        result = _build_programmatic_narrative(RICH_CTX, SAMPLE_TIPS, "soccer")
        assert "Edwards" in result
        assert "Slot" in result

    def test_includes_form(self):
        result = _build_programmatic_narrative(RICH_CTX, SAMPLE_TIPS, "soccer")
        assert "WLDDL" in result or "WWWLW" in result

    def test_includes_gpg(self):
        # W80-PROSE: GPG expressed as "X a game" (analyst prose) not "per game"
        result = _build_programmatic_narrative(RICH_CTX, SAMPLE_TIPS, "soccer")
        assert "a game" in result or "per game" in result

    def test_includes_odds_in_edge(self):
        result = _build_programmatic_narrative(RICH_CTX, SAMPLE_TIPS, "soccer")
        assert "5.7%" in result or "5.5%" in result
        assert "Draw" in result or "Wolves" in result

    def test_includes_h2h(self):
        result = _build_programmatic_narrative(RICH_CTX, SAMPLE_TIPS, "soccer")
        assert "2-1" in result or "meeting" in result.lower()

    def test_includes_record(self):
        # W79-PHASE2: venue names no longer in code-built Setup (AI owns context details)
        # Instead, verify home/away record data is present
        result = _build_programmatic_narrative(RICH_CTX, SAMPLE_TIPS, "soccer")
        assert "home" in result.lower() or "road" in result.lower()

    def test_passes_own_quality_gate(self):
        """The programmatic fallback MUST pass the quality gate."""
        result = _build_programmatic_narrative(RICH_CTX, SAMPLE_TIPS, "soccer")
        passed, issues = _validate_breakdown(result, RICH_CTX)
        assert passed is True, f"Programmatic fallback failed quality gate: {issues}"

    def test_cricket_context(self):
        result = _build_programmatic_narrative(CRICKET_CTX, SAMPLE_TIPS, "cricket")
        assert "South Africa" in result
        assert "New Zealand" in result
        assert "📋" in result

    def test_no_data_returns_empty(self):
        result = _build_programmatic_narrative({}, None, "soccer")
        assert result == ""

    def test_no_tips_still_produces_output(self):
        result = _build_programmatic_narrative(RICH_CTX, None, "soccer")
        assert "📋" in result
        assert "Limited odds" in result or "check back" in result.lower()

    def test_cricket_programmatic_passes_quality_gate(self):
        """Cricket programmatic fallback must also pass quality gate."""
        result = _build_programmatic_narrative(CRICKET_CTX, SAMPLE_TIPS, "cricket")
        passed, issues = _validate_breakdown(result, CRICKET_CTX)
        assert passed is True, f"Cricket fallback failed: {issues}"


# ═══════════════════════════════════════════════════════════════════════════
# Tests for _format_verified_context (score field fix)
# ═══════════════════════════════════════════════════════════════════════════

class TestFormatVerifiedContext:
    """Tests for verified context formatting — especially last 5 scores."""

    def test_last5_scores_from_score_field(self):
        """Score field (e.g. '2-0') should appear in formatted output."""
        result = _format_verified_context(RICH_CTX)
        assert "2-0" in result  # Aston Villa score
        assert "0-1" in result  # Crystal Palace score
        assert "2-2" in result  # Arsenal score

    def test_no_empty_scores(self):
        """No 'W  vs' pattern (missing score) should appear."""
        result = _format_verified_context(RICH_CTX)
        # Pattern: result letter followed by double space (missing score)
        assert not re.search(r'[WLD]\s{2,}vs', result), \
            f"Found empty score pattern in: {result}"

    def test_includes_venue(self):
        result = _format_verified_context(RICH_CTX)
        assert "Molineux" in result

    def test_includes_coach(self):
        result = _format_verified_context(RICH_CTX)
        assert "Rob Edwards" in result
        assert "Slot" in result

    def test_includes_top_scorer(self):
        result = _format_verified_context(RICH_CTX)
        assert "Arokodare" in result
        assert "Ekitike" in result

    def test_includes_home_away_record(self):
        result = _format_verified_context(RICH_CTX)
        assert "Home record" in result
        assert "Away record" in result

    def test_includes_goals_for_against(self):
        result = _format_verified_context(RICH_CTX)
        assert "20 scored" in result or "47 scored" in result

    def test_includes_h2h(self):
        result = _format_verified_context(RICH_CTX)
        assert "HEAD-TO-HEAD" in result
        assert "2-1" in result

    def test_includes_position(self):
        result = _format_verified_context(RICH_CTX)
        assert "League position: 20" in result
        assert "League position: 5" in result

    def test_cricket_includes_nrr(self):
        result = _format_verified_context(CRICKET_CTX)
        assert "Net Run Rate" in result
        assert "2.259" in result

    def test_cricket_includes_wins_losses(self):
        result = _format_verified_context(CRICKET_CTX)
        assert "Wins: 3" in result
        assert "Losses: 0" in result

    def test_no_data_returns_empty(self):
        result = _format_verified_context({"data_available": False})
        assert result == ""

    def test_fallback_score_from_goals_for_against(self):
        """If 'score' field missing but goals_for/against present, use those."""
        ctx = {
            "data_available": True,
            "sport": "soccer",
            "league": "Test",
            "home_team": {
                "name": "Team A",
                "last_5": [
                    {"opponent": "Team X", "result": "W",
                     "goals_for": "3", "goals_against": "1",
                     "home_away": "home"},
                ],
            },
            "away_team": {"name": "Team B"},
        }
        result = _format_verified_context(ctx)
        assert "3-1" in result


# ═══════════════════════════════════════════════════════════════════════════
# Integration tests
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegration:
    """End-to-end integration tests for the quality gate pipeline."""

    def test_terse_detected_and_fallback_works(self):
        """If Claude produces terse output, programmatic fallback takes over."""
        # Simulate: Claude gives terse → quality gate fails → build programmatic
        passed, issues = _validate_breakdown(TERSE_OUTPUT, RICH_CTX)
        assert not passed
        fallback = _build_programmatic_narrative(RICH_CTX, SAMPLE_TIPS, "soccer")
        passed2, issues2 = _validate_breakdown(fallback, RICH_CTX)
        assert passed2, f"Fallback should pass but got: {issues2}"

    def test_good_output_not_replaced(self):
        """Good narrative output should pass gate without fallback."""
        passed, _ = _validate_breakdown(GOOD_OUTPUT, RICH_CTX)
        assert passed

    def test_sanitize_preserves_quality(self):
        """sanitize_ai_response should not break a good narrative."""
        sanitized = sanitize_ai_response(GOOD_OUTPUT)
        passed, issues = _validate_breakdown(sanitized, RICH_CTX)
        assert passed, f"Sanitized good output failed: {issues}"
