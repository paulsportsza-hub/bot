from __future__ import annotations

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ensure_scrapers_importable
ensure_scrapers_importable()

from evidence_pack import (
    _add_name_variants,
    _build_simple_team_aliases,
    _display_name,
    _filter_injury_news_articles,
    _wrap_espn_context,
)


def test_injury_news_filter_rejects_unverified_player_name() -> None:
    verified: set[str] = set()
    _add_name_variants(verified, "M. Salah", min_token_len=3)
    _add_name_variants(verified, "Alisson", min_token_len=3)
    aliases = _build_simple_team_aliases("liverpool", "fulham", "Liverpool", "Fulham")

    articles = [
        {
            "title": "Ekitike, Salah and Alisson - Liverpool latest injury news after Brighton blow",
            "has_injury_mentions": True,
        },
        {
            "title": "Salah and Alisson available again for Liverpool",
            "has_injury_mentions": True,
        },
    ]

    filtered = _filter_injury_news_articles(articles, verified, aliases)

    assert [article["title"] for article in filtered] == [
        "Salah and Alisson available again for Liverpool"
    ]


def test_display_name_preserves_uppercase_suffixes() -> None:
    assert _display_name("sporting_cp") == "Sporting CP"


# ── COACH-POLISH-BUILD: coaches.json fallback in _wrap_espn_context (AC-6) ──


def test_wrap_espn_context_coach_fallback_used_when_espn_missing() -> None:
    """AC-6a: when ESPN context has no coach, coaches.json fallback is used."""
    ctx = {
        "data_available": True,
        "home_team": {"name": "Arsenal"},        # no "coach" key
        "away_team": {"name": "Bournemouth"},    # no "coach" key
    }
    with patch("narrative_spec.lookup_coach", side_effect=lambda name: f"Coach of {name}") as mock_lc:
        block = _wrap_espn_context(ctx)

    # Fallback must have been invoked for both missing coaches
    calls = [c.args[0] for c in mock_lc.call_args_list]
    assert "Arsenal" in calls, "lookup_coach not called for home team"
    assert "Bournemouth" in calls, "lookup_coach not called for away team"

    # Returned block must carry the fallback values
    assert block.home_team["coach"] == "Coach of Arsenal"
    assert block.away_team["coach"] == "Coach of Bournemouth"


def test_wrap_espn_context_espn_coach_takes_priority_over_coaches_json() -> None:
    """AC-6b: when ESPN context already has a coach, coaches.json is NOT consulted."""
    ctx = {
        "data_available": True,
        "home_team": {"name": "Arsenal", "coach": "Mikel Arteta"},
        "away_team": {"name": "Bournemouth", "coach": "Andoni Iraola"},
    }
    with patch("narrative_spec.lookup_coach") as mock_lc:
        block = _wrap_espn_context(ctx)

    # coaches.json must NOT be consulted when ESPN already has both coaches
    mock_lc.assert_not_called()

    # ESPN values must be preserved as-is
    assert block.home_team["coach"] == "Mikel Arteta"
    assert block.away_team["coach"] == "Andoni Iraola"


def test_wrap_espn_context_partial_fallback_only_missing_team() -> None:
    """AC-2: if ESPN has coach for one team only, coaches.json used only for the missing one."""
    ctx = {
        "data_available": True,
        "home_team": {"name": "Arsenal", "coach": "Mikel Arteta"},  # ESPN has coach
        "away_team": {"name": "Bournemouth"},                        # ESPN missing coach
    }
    with patch("narrative_spec.lookup_coach", return_value="Andoni Iraola") as mock_lc:
        block = _wrap_espn_context(ctx)

    # lookup_coach called only for away team
    called_names = [c.args[0] for c in mock_lc.call_args_list]
    assert "Bournemouth" in called_names
    assert "Arsenal" not in called_names

    # ESPN value intact; fallback filled the other
    assert block.home_team["coach"] == "Mikel Arteta"
    assert block.away_team["coach"] == "Andoni Iraola"


def test_wrap_espn_context_no_crash_when_coaches_json_missing() -> None:
    """AC-5: gracefully returns None when lookup_coach returns empty string (file not found)."""
    ctx = {
        "data_available": True,
        "home_team": {"name": "UnknownTeam"},
        "away_team": {"name": "AnotherUnknown"},
    }
    with patch("narrative_spec.lookup_coach", return_value=""):
        block = _wrap_espn_context(ctx)  # must not raise

    # coach key not set when fallback returns empty
    assert not block.home_team.get("coach")
    assert not block.away_team.get("coach")
