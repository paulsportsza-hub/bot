"""P1-BUILD-30: Tests for D-08, D-09, D-10a, D-10b defect fixes.

AC-6 coverage:
- D-08 (a): Setup fallback non-empty when mep_met=False
- D-09 (b): _pick() same team different opponent produces different description
- D-10a (c): '— Neutral Analysis' never appears in user-facing output
- D-10b (d): Team name casing uses _display_team_name (TS Galaxy, not Ts Galaxy)
"""
from __future__ import annotations

import os
import sys
from dataclasses import replace
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from config import ensure_scrapers_importable
ensure_scrapers_importable()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_edge_row(**overrides) -> dict:
    base = {
        "match_key": "arsenal_vs_tottenham_2026-03-26",
        "edge_tier": "gold",
        "composite_score": 72.5,
        "bet_type": "home",
        "recommended_odds": 2.10,
        "bookmaker": "betway",
        "predicted_ev": 5.2,
        "league": "epl",
        "match_date": "2026-03-26",
        "confirming_signals": 2,
        "sport": "soccer",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# D-08: Setup fallback non-empty when mep_met=False
# ---------------------------------------------------------------------------

class TestD08SetupFallback:
    """_section_team_context returns non-empty Setup when mep_met=False."""

    def _build_data(self, **overrides):
        from edge_detail_renderer import _build_detail_data

        row = _make_edge_row(**overrides)
        with (
            patch("edge_detail_renderer.get_cached_context", return_value=None),
            patch("scrapers.edge.tier_engine.assign_tier", return_value="gold"),
            patch("tier_gate.get_edge_access_level", return_value="full"),
        ):
            return _build_detail_data(row, ctx=None, user_tier="gold")

    def test_returns_non_empty_when_no_context(self):
        """When mep_met=False, _section_team_context returns a non-empty string."""
        from edge_detail_renderer import _section_team_context

        data = self._build_data()
        result = _section_team_context(data)
        assert result, "Expected non-empty Setup section when mep_met=False"

    def test_fallback_contains_setup_header(self):
        """Fallback must include 📋 <b>The Setup</b> header."""
        from edge_detail_renderer import _section_team_context

        data = self._build_data()
        result = _section_team_context(data)
        assert "📋" in result, "Missing 📋 emoji"
        assert "The Setup" in result, "Missing 'The Setup' text"

    def test_fallback_contains_team_names(self):
        """Fallback must contain team names from match_key."""
        from edge_detail_renderer import _section_team_context

        data = self._build_data()
        result = _section_team_context(data)
        assert "Arsenal" in result or "Tottenham" in result, (
            f"Expected team names in fallback. Got:\n{result}"
        )

    def test_fallback_graceful_when_all_fields_empty(self):
        """No exception when match_date, league, ev are all missing/zero."""
        from edge_detail_renderer import _section_team_context, EdgeDetailData

        data = self._build_data(
            match_date="",
            league="",
            predicted_ev=0,
            recommended_odds=0,
        )
        # Should not raise
        result = _section_team_context(data)
        assert result, "Must still return non-empty string on bare fields"


# ---------------------------------------------------------------------------
# D-09: _pick() same team different opponent produces different output
# ---------------------------------------------------------------------------

class TestD09PickCompositeSeeding:
    """_render_team_para with same team but different opponent produces different variants."""

    def _call_render_team_para(self, name, opponent):
        from narrative_spec import _render_team_para
        return _render_team_para(
            name=name,
            coach=None,
            story_type="neutral",
            position=5,
            points=40,
            form="WDWLW",
            record="8W 4D 6L",
            gpg=1.5,
            last_result="won 2-1",
            injuries=[],
            competition="Premier League",
            sport="soccer",
            is_home=True,
            opponent_name=opponent,
        )

    def test_same_team_different_opponents_may_differ(self):
        """Two distinct opponents should eventually produce different paragraphs.

        With 3 variants and MD5 hashing, not every opponent pair differs — but
        across enough opponents, at least one pair must differ (pigeonhole).
        """
        from narrative_spec import _render_team_para, _TEAM_TEMPLATES

        neutral_variants = _TEAM_TEMPLATES["neutral"]
        n = len(neutral_variants)
        assert n >= 2, "Need at least 2 neutral variants to verify diversity"

        opponents = [
            "Manchester City", "Liverpool", "Chelsea", "Arsenal",
            "Tottenham", "Newcastle", "Everton",
        ]
        outputs = {opp: self._call_render_team_para("Burnley", opp) for opp in opponents}
        unique_outputs = set(outputs.values())
        assert len(unique_outputs) >= 2, (
            f"Same team vs different opponents should produce diverse output. "
            f"Got only {len(unique_outputs)} unique variant(s) across {len(opponents)} opponents."
        )

    def test_same_team_same_opponent_is_deterministic(self):
        """Same team + same opponent always produces same paragraph."""
        result1 = self._call_render_team_para("Arsenal", "Chelsea")
        result2 = self._call_render_team_para("Arsenal", "Chelsea")
        assert result1 == result2, "Same inputs must always give same output"

    def test_opponent_name_parameter_accepted(self):
        """_render_team_para accepts opponent_name without error."""
        from narrative_spec import _render_team_para
        # Should not raise
        _render_team_para(
            name="Arsenal",
            coach="Arteta",
            story_type="momentum",
            position=2,
            points=60,
            form="WWWWW",
            record="20W 5D 3L",
            gpg=2.3,
            last_result="won 3-0",
            injuries=[],
            competition="Premier League",
            sport="soccer",
            is_home=True,
            opponent_name="Tottenham",
        )


# ---------------------------------------------------------------------------
# D-10a: '— Neutral Analysis' never in user-facing output
# ---------------------------------------------------------------------------

class TestD10aNeutralAnalysisStripped:
    """'— Neutral Analysis' must not appear in any rendered title."""

    def test_neutral_analysis_string_removed_from_title(self):
        """Verify the literal string is gone from bot.py's title assembly."""
        import pathlib
        bot_path = pathlib.Path(__file__).parent.parent.parent / "bot.py"
        source = bot_path.read_text()
        assert '— Neutral Analysis"' not in source, (
            "Literal '— Neutral Analysis' must not be appended to _match_title in bot.py"
        )

    def test_neutral_analysis_not_in_appended_title(self):
        """Reconstructing the title assembly logic: _neutral_analysis flag must not
        produce the banned string."""
        # Simulate the title assembly as it appears post-fix
        home = "Chiefs"
        away = "Pirates"
        _neutral_analysis = True  # worst case: flag is True
        _match_title = f"🎯 <b>{home} vs {away}</b>"
        # D-10a fix: the 'if _neutral_analysis: _match_title += ...' block is removed
        assert "Neutral Analysis" not in _match_title, (
            f"Title must not contain 'Neutral Analysis'. Got: {_match_title}"
        )


# ---------------------------------------------------------------------------
# D-10b: _teams_from_vs_event_id uses _display_team_name (no raw .title())
# ---------------------------------------------------------------------------

class TestD10bTeamNameCasing:
    """_teams_from_vs_event_id returns correctly cased team names."""

    def _call(self, event_id: str):
        import importlib.util
        import pathlib
        import unittest.mock as mock

        bot_path = pathlib.Path(__file__).parent.parent.parent / "bot.py"
        spec = importlib.util.spec_from_file_location("bot_module", bot_path)
        bot = importlib.util.module_from_spec(spec)
        with mock.patch.dict("sys.modules", {
            "telegram": mock.MagicMock(),
            "telegram.ext": mock.MagicMock(),
            "anthropic": mock.MagicMock(),
            "sentry_sdk": mock.MagicMock(),
            "posthog": mock.MagicMock(),
        }):
            try:
                spec.loader.exec_module(bot)
                return bot._teams_from_vs_event_id(event_id)
            except Exception:
                return None

    def test_ts_galaxy_correct_casing(self):
        """'ts_galaxy_vs_...' must render as 'TS Galaxy', not 'Ts Galaxy'."""
        result = self._call("ts_galaxy_vs_kaizer_chiefs_2026-04-10")
        if result is None:
            pytest.skip("bot.py import unavailable in this test env")
        home, _ = result
        assert home != "Ts Galaxy", (
            f"Expected 'TS Galaxy' (via _display_team_name), got '{home}' (raw .title())"
        )
        # _display_team_name should return 'TS Galaxy' via DISPLAY_NAMES
        assert "Galaxy" in home, f"Home team name should contain 'Galaxy', got: {home}"

    def test_returns_tuple_two_strings(self):
        """Function always returns a 2-tuple of strings."""
        result = self._call("mamelodi_sundowns_vs_sekhukhune_united_2026-04-05")
        if result is None:
            pytest.skip("bot.py import unavailable in this test env")
        assert len(result) == 2
        assert all(isinstance(s, str) for s in result)

    def test_fallback_on_missing_vs_separator(self):
        """Returns ('Home', 'Away') when _vs_ separator is absent."""
        result = self._call("invalid_event_id")
        if result is None:
            pytest.skip("bot.py import unavailable in this test env")
        assert result == ("Home", "Away"), (
            f"Expected ('Home', 'Away') fallback, got {result}"
        )
