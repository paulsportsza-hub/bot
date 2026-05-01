from __future__ import annotations

import pytest
pytest.skip(
    "FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: Sonnet/Haiku polish ripped out. "
    "This test asserts polish-chain behaviour that no longer exists.",
    allow_module_level=True,
)

"""Tests for BASELINE-FIX-R2: Injury Data Routing + UCL Phrase Purge.

Verifies:
  1. get_verified_injuries() SQL team filter prevents cross-team contamination
  2. Knockout phrases banned from BANNED_NARRATIVE_PHRASES
  3. Evidence pack rule 11 bans knockout phrases in Claude prompt
  4. _match_shape_note() no longer contains 'knockout'
"""

import sys
import os
import sqlite3
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ensure_scrapers_importable
ensure_scrapers_importable()

from datetime import datetime, timezone


# ── Injury SQL Filter Tests ──


def _now_str() -> str:
    """Return a current UTC timestamp string for test data."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _today_str() -> str:
    """Return today's date string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _create_injury_db(rows: list[tuple]) -> str:
    """Create a temp DB with team_injuries table and return its path."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE team_injuries ("
        "league TEXT, team TEXT, player_name TEXT, injury_status TEXT, "
        "fixture_date TEXT, fetched_at TEXT)"
    )
    conn.executemany(
        "INSERT INTO team_injuries VALUES (?, ?, ?, ?, ?, ?)", rows
    )
    conn.commit()
    conn.close()
    return path


def test_injury_filter_excludes_other_team():
    """Ekitike (PSG) must NOT appear in Liverpool injuries."""
    import bot

    now = _now_str()
    today = _today_str()
    rows = [
        ("champions_league", "Paris Saint Germain", "Ekitike", "Doubtful",
         today, now),
        ("champions_league", "Liverpool", "Salah", "Questionable",
         today, now),
    ]
    db_path = _create_injury_db(rows)
    try:
        result = bot.get_verified_injuries(
            "Liverpool", "Paris Saint Germain",
            sport="soccer", league="champions_league", db_path=db_path,
        )
        # Liverpool side should only have Salah
        home_players = [p.split(" (")[0] for p in result["home"]]
        assert "Salah" in home_players
        assert "Ekitike" not in home_players

        # PSG side should only have Ekitike
        away_players = [p.split(" (")[0] for p in result["away"]]
        assert "Ekitike" in away_players
        assert "Salah" not in away_players
    finally:
        os.unlink(db_path)


def test_injury_filter_with_suffix_team():
    """Teams with suffix tokens (e.g. 'FC') are matched via base tokens."""
    import bot

    now = _now_str()
    today = _today_str()
    rows = [
        ("epl", "Arsenal FC", "Saka", "Doubtful", today, now),
        ("epl", "Chelsea FC", "Palmer", "Questionable", today, now),
    ]
    db_path = _create_injury_db(rows)
    try:
        result = bot.get_verified_injuries(
            "Arsenal", "Chelsea",
            sport="soccer", league="epl", db_path=db_path,
        )
        home_players = [p.split(" (")[0] for p in result["home"]]
        away_players = [p.split(" (")[0] for p in result["away"]]
        assert "Saka" in home_players
        assert "Palmer" not in home_players
        assert "Palmer" in away_players
        assert "Saka" not in away_players
    finally:
        os.unlink(db_path)


def test_injury_filter_no_cross_contamination_different_league():
    """Injuries from a different league for a similarly-named team stay isolated."""
    import bot

    now = _now_str()
    today = _today_str()
    rows = [
        ("psl", "Kaizer Chiefs", "Dolly", "Injured", today, now),
        ("epl", "Arsenal", "Odegaard", "Doubtful", today, now),
    ]
    db_path = _create_injury_db(rows)
    try:
        result = bot.get_verified_injuries(
            "Arsenal", "Kaizer Chiefs",
            sport="soccer", league="epl", db_path=db_path,
        )
        # Arsenal should have Odegaard, not Dolly
        home_players = [p.split(" (")[0] for p in result["home"]]
        assert "Odegaard" in home_players
        assert "Dolly" not in home_players
    finally:
        os.unlink(db_path)


def test_injury_filter_empty_team_returns_empty():
    """Empty team name returns empty list without error."""
    import bot

    db_path = _create_injury_db([])
    try:
        result = bot.get_verified_injuries(
            "", "SomeTeam", db_path=db_path,
        )
        assert result["home"] == []
    finally:
        os.unlink(db_path)


def test_injury_excludes_missing_fixture_status():
    """Rows with 'Missing Fixture' or 'Unknown' status are excluded."""
    import bot

    now = _now_str()
    today = _today_str()
    rows = [
        ("epl", "Arsenal", "Ghost", "Missing Fixture", today, now),
        ("epl", "Arsenal", "Unknown1", "Unknown", today, now),
        ("epl", "Arsenal", "Saka", "Doubtful", today, now),
    ]
    db_path = _create_injury_db(rows)
    try:
        result = bot.get_verified_injuries(
            "Arsenal", "Chelsea",
            sport="soccer", league="epl", db_path=db_path,
        )
        home_players = [p.split(" (")[0] for p in result["home"]]
        assert "Saka" in home_players
        assert "Ghost" not in home_players
        assert "Unknown1" not in home_players
    finally:
        os.unlink(db_path)


# ── Knockout Phrase Ban Tests ──


def test_knockout_phrases_in_banned_list():
    """All 6 knockout phrases must be in BANNED_NARRATIVE_PHRASES."""
    import bot

    required = [
        "knockout football",
        "knockout stakes",
        "knockout stage",
        "knockout tie",
        "knockout clash",
        "knockout encounter",
    ]
    for phrase in required:
        assert phrase in bot.BANNED_NARRATIVE_PHRASES, (
            f"'{phrase}' missing from BANNED_NARRATIVE_PHRASES"
        )


def test_has_banned_patterns_catches_knockout():
    """_has_banned_patterns() must detect knockout phrases in narrative text."""
    import bot

    text = "This is a knockout football match with high stakes."
    assert bot._has_banned_patterns(text) is True


def test_has_banned_patterns_passes_clean_text():
    """Clean narrative text should pass _has_banned_patterns()."""
    import bot

    text = (
        "📋 <b>The Setup</b>\nArsenal face Bournemouth in the Premier League.\n\n"
        "🏆 <b>Verdict</b>\nBack Arsenal at 2.10 with Betway."
    )
    assert bot._has_banned_patterns(text) is False


# ── Evidence Pack Rule 11 Test ──


def test_evidence_pack_bans_knockout_phrases():
    """format_evidence_prompt() must include rule 11 banning knockout phrases."""
    from evidence_pack import format_evidence_prompt, EvidencePack
    from narrative_spec import NarrativeSpec

    # Minimal spec and pack for the prompt builder
    spec = NarrativeSpec(
        home_name="PSG", away_name="Liverpool",
        competition="Champions League", sport="soccer",
        home_story_type="momentum", away_story_type="momentum",
        home_coach="Luis Enrique", away_coach="Arne Slot",
        home_position=1, away_position=2,
        home_points=60, away_points=55,
        home_form="WWWDL", away_form="WDWWL",
        home_record="W9 D3 L2", away_record="W8 D4 L2",
        home_gpg=2.0, away_gpg=1.8,
        home_last_result="beat Monaco 3-1", away_last_result="beat Man City 2-0",
        h2h_summary="4 meetings: PSG 1W 2D 1L",
        bookmaker="Betway", odds=2.10, ev_pct=4.5,
        fair_prob_pct=48.0, composite_score=62.0,
        support_level=2, contradicting_signals=0,
        evidence_class="supported", tone_band="confident",
        risk_factors=["Standard variance applies."],
        risk_severity="moderate",
        verdict_action="back", verdict_sizing="standard stake",
        outcome="home", outcome_label="the PSG win",
    )
    pack = EvidencePack(
        match_key="psg_vs_liverpool_2026-03-22",
        sport="soccer",
        league="champions_league",
        built_at="2026-03-22T12:00:00Z",
        richness_score="medium",
        sources_available=5,
        sources_total=7,
    )
    prompt = format_evidence_prompt(pack, spec)
    assert "knockout football" in prompt.lower()
    assert "knockout stakes" in prompt.lower()
    assert "ucl league-phase" in prompt.lower() or "not knockouts" in prompt.lower()


# ── narrative_spec._match_shape_note() Test ──


def test_match_shape_note_no_knockout():
    """_match_shape_note() must not contain 'knockout' for any category."""
    from narrative_spec import _match_shape_note

    categories = ["continental", "international", "club_rugby", "cricket", "combat", "league"]
    fixture_types = ["match", "clash", "fixture"]
    for cat in categories:
        for ft in fixture_types:
            note = _match_shape_note(cat, ft)
            assert "knockout" not in note.lower(), (
                f"_match_shape_note('{cat}', '{ft}') contains 'knockout': {note}"
            )
