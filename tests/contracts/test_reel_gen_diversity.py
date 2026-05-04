"""Contract tests for FIX-REEL-GEN-SPORT-DIVERSITY-01.

Tests cover:
  (a) empty history → no filter applied
  (b) yesterday had rugby → today rugby excluded
  (c) same match_key in window → excluded
  (d) backward compat: meta.json missing sport/match_key fields → no crash
"""
import json
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Resolve reel_generator location
_REEL_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "reel_cards" / "reel_generator.py"

# Import helpers by loading the module as a namespace so we don't trigger
# module-level crontab / bot setup that reel_generator.py skips at import.
import importlib.util


def _load_reel_module():
    spec = importlib.util.spec_from_file_location("reel_generator", _REEL_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    # Stub out env file load so tests don't need publisher/.env
    with patch("builtins.open", side_effect=FileNotFoundError):
        try:
            spec.loader.exec_module(mod)
        except Exception:
            pass
    return mod


# Load once
_reel = _load_reel_module()


# ---------------------------------------------------------------------------
# _recent_sports_used
# ---------------------------------------------------------------------------

class TestRecentSportsUsed:
    def test_empty_output_root_returns_empty_set(self, tmp_path):
        """No date dirs → no blocked sports."""
        with patch.object(_reel, "OUTPUT_ROOT", tmp_path):
            result = _reel._recent_sports_used("2026-04-23", 3)
        assert result == set()

    def test_no_meta_json_returns_empty_set(self, tmp_path):
        """Date dir exists but no meta.json files → no blocked sports."""
        (tmp_path / "2026-04-22" / "abc123").mkdir(parents=True)
        with patch.object(_reel, "OUTPUT_ROOT", tmp_path):
            result = _reel._recent_sports_used("2026-04-23", 3)
        assert result == set()

    def test_yesterday_rugby_appears_in_result(self, tmp_path):
        """meta.json with sport=rugby yesterday → rugby in blocked set."""
        pick_dir = tmp_path / "2026-04-22" / "abc123"
        pick_dir.mkdir(parents=True)
        (pick_dir / "meta.json").write_text(json.dumps({"sport": "rugby", "match_key": "bulls_vs_sharks_2026-04-22"}))
        with patch.object(_reel, "OUTPUT_ROOT", tmp_path):
            result = _reel._recent_sports_used("2026-04-23", 3)
        assert "rugby" in result

    def test_today_is_excluded_from_window(self, tmp_path):
        """Picks from today itself should not block today (range is 1..days, excl. today)."""
        pick_dir = tmp_path / "2026-04-23" / "abc123"
        pick_dir.mkdir(parents=True)
        (pick_dir / "meta.json").write_text(json.dumps({"sport": "rugby", "match_key": "bulls_vs_sharks_2026-04-23"}))
        with patch.object(_reel, "OUTPUT_ROOT", tmp_path):
            result = _reel._recent_sports_used("2026-04-23", 3)
        assert result == set()

    def test_sport_outside_window_not_blocked(self, tmp_path):
        """Picks older than `days` ago should not appear in result."""
        pick_dir = tmp_path / "2026-04-19" / "abc123"  # 4 days ago, window=3
        pick_dir.mkdir(parents=True)
        (pick_dir / "meta.json").write_text(json.dumps({"sport": "rugby", "match_key": "x"}))
        with patch.object(_reel, "OUTPUT_ROOT", tmp_path):
            result = _reel._recent_sports_used("2026-04-23", 3)
        assert "rugby" not in result

    def test_meta_without_sport_field_no_crash(self, tmp_path):
        """Backward compat: old meta.json without sport key → no crash, no block."""
        pick_dir = tmp_path / "2026-04-22" / "abc123"
        pick_dir.mkdir(parents=True)
        (pick_dir / "meta.json").write_text(json.dumps({"pick_team": "Bulls", "tier": "gold"}))
        with patch.object(_reel, "OUTPUT_ROOT", tmp_path):
            result = _reel._recent_sports_used("2026-04-23", 3)
        assert result == set()

    def test_lowercase_normalisation(self, tmp_path):
        """Sport values are lowercased before adding to set."""
        pick_dir = tmp_path / "2026-04-22" / "abc123"
        pick_dir.mkdir(parents=True)
        (pick_dir / "meta.json").write_text(json.dumps({"sport": "Rugby", "match_key": "x"}))
        with patch.object(_reel, "OUTPUT_ROOT", tmp_path):
            result = _reel._recent_sports_used("2026-04-23", 3)
        assert "rugby" in result
        assert "Rugby" not in result

    def test_multiple_sports_across_days(self, tmp_path):
        """Collects sports from multiple past days."""
        for day, sport in [("2026-04-22", "rugby"), ("2026-04-21", "soccer")]:
            pd = tmp_path / day / "aaa"
            pd.mkdir(parents=True)
            (pd / "meta.json").write_text(json.dumps({"sport": sport}))
        with patch.object(_reel, "OUTPUT_ROOT", tmp_path):
            result = _reel._recent_sports_used("2026-04-23", 3)
        assert result == {"rugby", "soccer"}


# ---------------------------------------------------------------------------
# _recent_match_keys_used
# ---------------------------------------------------------------------------

class TestRecentMatchKeysUsed:
    def test_empty_output_root_returns_empty_set(self, tmp_path):
        with patch.object(_reel, "OUTPUT_ROOT", tmp_path):
            result = _reel._recent_match_keys_used("2026-04-23", 14)
        assert result == set()

    def test_match_key_in_window_is_blocked(self, tmp_path):
        mk = "benetton_vs_leinster_2026-04-22"
        pick_dir = tmp_path / "2026-04-22" / "abc"
        pick_dir.mkdir(parents=True)
        (pick_dir / "meta.json").write_text(json.dumps({"sport": "rugby", "match_key": mk}))
        with patch.object(_reel, "OUTPUT_ROOT", tmp_path):
            result = _reel._recent_match_keys_used("2026-04-23", 14)
        assert mk in result

    def test_match_key_outside_window_not_blocked(self, tmp_path):
        mk = "benetton_vs_leinster_2026-04-08"
        pick_dir = tmp_path / "2026-04-08" / "abc"  # 15 days ago, window=14
        pick_dir.mkdir(parents=True)
        (pick_dir / "meta.json").write_text(json.dumps({"sport": "rugby", "match_key": mk}))
        with patch.object(_reel, "OUTPUT_ROOT", tmp_path):
            result = _reel._recent_match_keys_used("2026-04-23", 14)
        assert mk not in result

    def test_meta_without_match_key_no_crash(self, tmp_path):
        pick_dir = tmp_path / "2026-04-22" / "abc"
        pick_dir.mkdir(parents=True)
        (pick_dir / "meta.json").write_text(json.dumps({"sport": "rugby"}))
        with patch.object(_reel, "OUTPUT_ROOT", tmp_path):
            result = _reel._recent_match_keys_used("2026-04-23", 14)
        assert result == set()

    def test_corrupted_meta_json_no_crash(self, tmp_path):
        pick_dir = tmp_path / "2026-04-22" / "abc"
        pick_dir.mkdir(parents=True)
        (pick_dir / "meta.json").write_text("not valid json {{")
        with patch.object(_reel, "OUTPUT_ROOT", tmp_path):
            result = _reel._recent_match_keys_used("2026-04-23", 14)
        assert result == set()


# ---------------------------------------------------------------------------
# _select_top_tier_pick diversity integration
# ---------------------------------------------------------------------------

def _make_row(match_key: str, sport: str, tier: str, composite: float = 75.0, **kwargs) -> dict:
    base = {
        "edge_id": f"edge_{match_key}",
        "match_key": match_key,
        "sport": sport,
        "league": "test_league",
        "edge_tier": tier,
        "composite_score": composite,
        "bet_type": "home_win",
        "recommended_odds": 2.10,
        "bookmaker": "betway",
        "match_date": "2026-04-25",
        "home_team": "Home",
        "away_team": "Away",
    }
    base.update(kwargs)
    return base


def _mock_row(data: dict):
    """Build an object that behaves like sqlite3.Row for our fixture."""
    class FakeRow:
        def __getitem__(self, key):
            return data[key]
        def get(self, key, default=None):
            return data.get(key, default)
        def keys(self):
            return data.keys()
    return FakeRow()


class TestSelectTopTierPickDiversity:
    """Integration tests for _select_top_tier_pick diversity guards."""

    def _run(self, today: str, rows_by_tier: dict, tmp_path: Path, blocked_days: int = 0):
        """Helper: patch OUTPUT_ROOT + sqlite + diamond gate, call _select_top_tier_pick."""
        import sqlite3

        def fake_connect(path, **kw):
            conn = MagicMock()
            conn.__enter__ = lambda s: s
            conn.__exit__ = MagicMock(return_value=False)
            conn.row_factory = None

            def execute(sql, params=None):
                if params is None:
                    # PRAGMA statements (no params) — return a no-op cursor
                    return MagicMock()
                tier = params[0]
                raw_rows = rows_by_tier.get(tier, [])
                cursor = MagicMock()
                cursor.fetchall.return_value = [_mock_row(r) for r in raw_rows]
                return cursor

            conn.execute = execute
            conn.close = MagicMock()
            return conn

        with patch.object(_reel, "OUTPUT_ROOT", tmp_path), \
             patch("sqlite3.connect", side_effect=fake_connect), \
             patch.object(_reel, "_diamond_used_recently", return_value=False):
            return _reel._select_top_tier_pick(today)

    def test_empty_history_no_filter_applied(self, tmp_path):
        """No prior picks → no diversity filter → first gold row returned."""
        rows = {"gold": [_make_row("chiefs_vs_pirates_2026-04-25", "soccer", "gold")]}
        result = self._run("2026-04-23", rows, tmp_path)
        assert result is not None
        tier, row = result
        assert tier == "gold"
        assert row["match_key"] == "chiefs_vs_pirates_2026-04-25"

    def test_yesterday_rugby_blocks_today_rugby(self, tmp_path):
        """Yesterday had rugby → today's rugby candidates are excluded."""
        # Write yesterday's pick
        pd = tmp_path / "2026-04-22" / "abc"
        pd.mkdir(parents=True)
        (pd / "meta.json").write_text(json.dumps({"sport": "rugby", "match_key": "old_match"}))

        rows = {"gold": [_make_row("bulls_vs_sharks_2026-04-25", "rugby", "gold")]}
        result = self._run("2026-04-23", rows, tmp_path)
        assert result is None  # rugby blocked, no other candidates

    def test_same_match_key_in_window_excluded(self, tmp_path):
        """Same match_key within MATCH_UNIQUENESS_DAYS → excluded."""
        mk = "benetton_vs_leinster_2026-04-22"
        pd = tmp_path / "2026-04-22" / "abc"
        pd.mkdir(parents=True)
        (pd / "meta.json").write_text(json.dumps({"sport": "rugby", "match_key": mk}))

        rows = {"gold": [_make_row(mk, "rugby", "gold")]}
        result = self._run("2026-04-23", rows, tmp_path)
        assert result is None

    def test_different_sport_passes_after_rugby_block(self, tmp_path):
        """Rugby blocked but soccer candidate available → soccer returned."""
        pd = tmp_path / "2026-04-22" / "abc"
        pd.mkdir(parents=True)
        (pd / "meta.json").write_text(json.dumps({"sport": "rugby", "match_key": "old_match"}))

        rows = {
            "gold": [
                _make_row("bulls_vs_sharks_2026-04-25", "rugby", "gold", composite=80.0),
                _make_row("chiefs_vs_pirates_2026-04-25", "soccer", "gold", composite=75.0),
            ]
        }
        result = self._run("2026-04-23", rows, tmp_path)
        assert result is not None
        _, row = result
        assert row["sport"] == "soccer"

    def test_tier_priority_preserved_within_filtered_set(self, tmp_path):
        """Diamond candidate (if passes) takes priority over Gold even after filtering."""
        rows = {
            "diamond": [_make_row("star_match_2026-04-25", "soccer", "diamond", composite=90.0)],
            "gold": [_make_row("good_match_2026-04-25", "soccer", "gold", composite=80.0)],
        }
        result = self._run("2026-04-23", rows, tmp_path)
        assert result is not None
        tier, _ = result
        assert tier == "diamond"

    def test_no_rows_returns_none(self, tmp_path):
        """No rows in any tier → None returned."""
        result = self._run("2026-04-23", {}, tmp_path)
        assert result is None

    def test_backward_compat_old_meta_no_sport_field(self, tmp_path):
        """Old meta.json without sport/match_key fields → no crash, no false block."""
        pd = tmp_path / "2026-04-22" / "abc"
        pd.mkdir(parents=True)
        (pd / "meta.json").write_text(json.dumps({"pick_team": "BULLS", "tier": "gold"}))

        rows = {"gold": [_make_row("bulls_vs_sharks_2026-04-25", "rugby", "gold")]}
        result = self._run("2026-04-23", rows, tmp_path)
        # Old meta has no sport → blocked_sports is empty → rugby passes
        assert result is not None
        _, row = result
        assert row["sport"] == "rugby"
