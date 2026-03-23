from __future__ import annotations

import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.expanduser("~"))
sys.path.insert(0, os.path.join(os.path.expanduser("~"), "scrapers"))
sys.path.insert(0, os.path.join(os.path.expanduser("~"), "bot"))

from narrative_spec import NarrativeSpec, _render_setup, _render_setup_no_context, _render_team_para
from scrapers.match_context_fetcher import _apply_soccer_team_fallback, _lookup_domestic_soccer_league


def _make_no_context_spec(**overrides) -> NarrativeSpec:
    spec = NarrativeSpec(
        home_name="Barcelona",
        away_name="Atletico Madrid",
        competition="Champions League",
        sport="soccer",
        home_story_type="neutral",
        away_story_type="neutral",
    )
    for key, value in overrides.items():
        setattr(spec, key, value)
    return spec


def test_no_context_setup_is_scene_setting_only() -> None:
    spec = _make_no_context_spec(
        bookmaker="Hollywoodbets",
        odds=2.48,
        ev_pct=7.4,
        fair_prob_pct=49.0,
        outcome_label="Barcelona win",
    )
    text = _render_setup_no_context(spec)
    lowered = text.lower()

    banned_terms = [
        "expected value",
        "fair probability",
        "implied probability",
        "model reads",
        "bookmaker",
        "hollywoodbets",
        "betway",
    ]
    for term in banned_terms:
        assert term not in lowered

    assert not re.search(r"\b\d+\.\d{1,2}\b", text)
    sentences = [s for s in re.split(r"[.!?]+(?:\s|$)", text) if s.strip()]
    assert 2 <= len(sentences) <= 3


def test_champions_league_no_context_setup_purges_old_european_night_phrase() -> None:
    text = _render_setup_no_context(_make_no_context_spec())
    lowered = text.lower()

    assert "measured european night" not in lowered
    assert "enough status for the occasion" not in lowered


def test_united_rugby_championship_no_context_setup_uses_rugby_frame() -> None:
    spec = NarrativeSpec(
        home_name="Lions",
        away_name="Edinburgh",
        competition="United Rugby Championship",
        sport="rugby",
        home_story_type="neutral",
        away_story_type="neutral",
    )

    text = _render_setup_no_context(spec)
    lowered = text.lower()

    assert "european night" not in lowered
    assert "football even starts" not in lowered
    assert (
        "club rugby" in lowered
        or "set-piece" in lowered
        or "middle third" in lowered
        or "field-position" in lowered
        or "composure" in lowered
        or "repeat control" in lowered
        or "exits, pressure" in lowered
        or "discipline, restarts" in lowered
    )


def test_no_context_setup_drops_known_repetition_phrases() -> None:
    text = _render_setup_no_context(_make_no_context_spec())
    lowered = text.lower()

    banned = [
        "club rugby at this level",
        "the competition itself gives the fixture enough structure",
        "takes its character from control rather than noise",
        "mid-table and on a roll",
    ]
    for phrase in banned:
        assert phrase not in lowered


def test_no_context_setup_varies_by_market_state() -> None:
    base = _make_no_context_spec(competition="Premier League", sport="soccer")
    price_only = _render_setup_no_context(
        _make_no_context_spec(
            competition=base.competition,
            sport=base.sport,
            support_level=0,
            ev_pct=1.2,
            odds=3.45,
            composite_score=49.0,
        )
    )
    multi_signal = _render_setup_no_context(
        _make_no_context_spec(
            competition=base.competition,
            sport=base.sport,
            support_level=3,
            ev_pct=7.8,
            odds=1.74,
            composite_score=61.0,
        )
    )

    assert price_only != multi_signal
    assert "no support stack" in price_only.lower() or "only a narrow edge" in price_only.lower()
    assert "multiple signals" in multi_signal.lower() or "signal count" in multi_signal.lower()
    assert "short favourite" in multi_signal.lower() or "clear favourite" in multi_signal.lower()


def test_neutral_template_drops_apology_language_and_interprets_form() -> None:
    text = _render_team_para(
        "Brentford",
        "Thomas Frank",
        "neutral",
        11,
        42,
        "WDLDW",
        "",
        None,
        "",
        [],
        "Premier League",
        "soccer",
        True,
    )
    lowered = text.lower()
    assert "limited context available" not in lowered
    assert "for what it's worth" not in lowered
    assert "without a strong recent record to lean on" not in lowered
    assert "Form reads W-D-L-D-W" in text


def test_momentum_template_with_unknown_position_drops_mid_table_shorthand() -> None:
    text = _render_team_para(
        "Paris Saint-Germain",
        "Luis Enrique",
        "momentum",
        None,
        None,
        "WWDWD",
        "",
        2.1,
        "",
        [],
        "Champions League",
        "soccer",
        True,
    )
    lowered = text.lower()

    assert "mid-table" not in lowered
    assert "on a roll" not in lowered
    assert "champions league" in lowered


def test_thin_context_setup_gets_bridge_sentence() -> None:
    spec = NarrativeSpec(
        home_name="Arsenal",
        away_name="Man City",
        competition="Premier League",
        sport="soccer",
        home_story_type="neutral",
        away_story_type="neutral",
        home_form="WDLDW",
        away_form="DLWDW",
    )
    text = _render_setup(spec)
    assert "That gives Arsenal vs Man City in Premier League a clear shape before kickoff" in text


def test_lookup_domestic_soccer_league_prefers_real_domestic_path() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE team_api_ids (league TEXT, espn_id TEXT)")
    conn.executemany(
        "INSERT INTO team_api_ids (league, espn_id) VALUES (?, ?)",
        [
            ("champions_league", "359"),
            ("epl", "359"),
        ],
    )
    assert _lookup_domestic_soccer_league(conn, "359", exclude_league="champions_league") == "epl"


def test_apply_soccer_team_fallback_only_fills_sparse_fields() -> None:
    base = {
        "league_position": None,
        "points": None,
        "games_played": None,
        "record": None,
        "form": "",
        "last_5": [],
        "top_scorer": None,
        "goals_per_game": 0.0,
        "conceded_per_game": 0.0,
        "home_record": "W0 D0 L0",
        "away_record": "W0 D0 L0",
        "context_source": {"standings_league": "champions_league", "form_league": "champions_league"},
        "league_key": "champions_league",
    }
    fallback = {
        "league_key": "epl",
        "standing": {
            "league_position": 2,
            "points": 61,
            "games_played": 29,
            "record": "W18 D7 L4",
            "goals_for": 60,
            "goals_against": 27,
            "goal_difference": 33,
            "note": "",
        },
        "results": [
            {"result": "W", "score": "2-0", "date": "2026-03-01", "home_away": "home", "opponent": "Chelsea", "venue": ""},
            {"result": "D", "score": "1-1", "date": "2026-02-24", "home_away": "away", "opponent": "Villa", "venue": ""},
            {"result": "W", "score": "3-1", "date": "2026-02-17", "home_away": "home", "opponent": "Palace", "venue": ""},
        ],
        "top_scorer": {"name": "Bukayo Saka", "goals": 11},
        "goals_per_game": 2.0,
        "conceded_per_game": 0.7,
        "home_record": "W8 D3 L1",
        "away_record": "W6 D4 L2",
    }

    merged = _apply_soccer_team_fallback(base, fallback, replace_form=True)

    assert merged["league_position"] == 2
    assert merged["form"] == "WDW"
    assert merged["top_scorer"]["name"] == "Bukayo Saka"
    assert merged["context_source"]["standings_league"] == "epl"
    assert merged["context_source"]["form_league"] == "epl"
