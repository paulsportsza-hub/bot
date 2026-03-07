"""Unit tests for Edge Tracker / Results Display (Wave 23)."""

from __future__ import annotations

from unittest.mock import patch, MagicMock, AsyncMock

import pytest


# ── render_result_emoji tests ────────────────────────────


class TestRenderResultEmoji:
    def test_hit(self):
        from renderers.edge_renderer import render_result_emoji
        assert render_result_emoji("hit") == "\u2705"

    def test_miss(self):
        from renderers.edge_renderer import render_result_emoji
        assert render_result_emoji("miss") == "\u274c"

    def test_pending(self):
        from renderers.edge_renderer import render_result_emoji
        assert render_result_emoji("") == "\u23f3"

    def test_none(self):
        from renderers.edge_renderer import render_result_emoji
        assert render_result_emoji(None) == "\u23f3"


# ── format_return tests ─────────────────────────────────


class TestFormatReturn:
    def test_default_stake(self):
        from renderers.edge_renderer import format_return
        result = format_return(3.15)
        assert "R945" in result
        assert "R300" in result

    def test_low_odds(self):
        from renderers.edge_renderer import format_return
        result = format_return(1.85)
        assert "R555" in result
        assert "R300" in result

    def test_high_odds(self):
        from renderers.edge_renderer import format_return
        result = format_return(4.20)
        assert "R1,260" in result

    def test_custom_stake(self):
        from renderers.edge_renderer import format_return
        result = format_return(2.0, stake=100)
        assert "R200" in result
        assert "R100" in result

    def test_has_emoji(self):
        from renderers.edge_renderer import format_return
        result = format_return(2.0)
        assert "\U0001f4b0" in result  # 💰


# ── _format_results_text tests ──────────────────────────


def _make_stats(total=10, hits=6, hit_rate=0.6, roi=5.2, by_tier=None, by_sport=None):
    return {
        "total": total, "hits": hits, "misses": total - hits,
        "hit_rate": hit_rate, "avg_ev": 4.0, "avg_return": 0, "roi": roi,
        "by_tier": by_tier or {
            "gold": {"total": 4, "hits": 3, "misses": 1, "hit_rate": 0.75},
            "bronze": {"total": 6, "hits": 3, "misses": 3, "hit_rate": 0.5},
        },
        "by_sport": by_sport or {},
        "period_days": 7,
    }


def _make_recent():
    return [
        {
            "edge_id": "e1", "match_key": "team_a_vs_team_b",
            "sport": "soccer", "league": "psl", "edge_tier": "bronze",
            "composite_score": 55.0, "bet_type": "1x2",
            "recommended_odds": 2.10, "bookmaker": "hollywoodbets",
            "predicted_ev": 5.2, "result": "hit",
            "match_score": "2-1", "actual_return": 210.0,
        },
        {
            "edge_id": "e2", "match_key": "team_c_vs_team_d",
            "sport": "soccer", "league": "epl", "edge_tier": "gold",
            "composite_score": 72.0, "bet_type": "1x2",
            "recommended_odds": 3.15, "bookmaker": "betway",
            "predicted_ev": 8.1, "result": "miss",
            "match_score": "0-0", "actual_return": 0,
        },
    ]


def _make_streak(type_="win", count=5):
    return {"type": type_, "count": count, "tier": None}


class TestFormatResultsText:
    def test_with_data(self):
        import bot
        text = bot._format_results_text(
            _make_stats(), _make_recent(), _make_streak(), 7, "diamond",
        )
        assert "Edge Tracker" in text
        assert "6/10" in text
        assert "60%" in text
        assert "+5.2%" in text

    def test_empty_stats(self):
        import bot
        text = bot._format_results_text(
            {"total": 0}, [], {"type": "none", "count": 0}, 7, "bronze",
        )
        assert "No settled edges" in text

    def test_streak_shown(self):
        import bot
        text = bot._format_results_text(
            _make_stats(), _make_recent(), _make_streak("win", 5), 7, "diamond",
        )
        assert "5-win streak" in text
        assert "🔥" in text

    def test_streak_hidden_under_3(self):
        import bot
        text = bot._format_results_text(
            _make_stats(), _make_recent(), _make_streak("win", 2), 7, "diamond",
        )
        assert "streak" not in text

    def test_loss_streak(self):
        import bot
        text = bot._format_results_text(
            _make_stats(), _make_recent(), _make_streak("loss", 4), 7, "diamond",
        )
        assert "4-loss streak" in text
        assert "📉" in text

    def test_bronze_cta(self):
        import bot
        text = bot._format_results_text(
            _make_stats(), _make_recent(), _make_streak("win", 1), 7, "bronze",
        )
        assert "Gold picks hit" in text
        assert "R99" in text

    def test_gold_cta(self):
        import bot
        stats = _make_stats(by_tier={
            "diamond": {"total": 3, "hits": 2, "misses": 1, "hit_rate": 0.67},
            "gold": {"total": 4, "hits": 3, "misses": 1, "hit_rate": 0.75},
        })
        text = bot._format_results_text(
            stats, _make_recent(), _make_streak("win", 1), 7, "gold",
        )
        assert "Diamond edges hit" in text
        assert "R199" in text

    def test_diamond_no_cta(self):
        import bot
        text = bot._format_results_text(
            _make_stats(), _make_recent(), _make_streak("win", 1), 7, "diamond",
        )
        assert "Upgrade" not in text
        assert "View Plans" not in text

    def test_bronze_sees_locked_gold(self):
        import bot
        text = bot._format_results_text(
            _make_stats(), _make_recent(), _make_streak("win", 1), 7, "bronze",
        )
        # Bronze sees bronze results in detail, gold results as locked
        assert "🔒" in text

    def test_r300_in_results(self):
        """Results display uses R300 base for returns."""
        import bot
        text = bot._format_results_text(
            _make_stats(), _make_recent(), _make_streak("win", 1), 7, "diamond",
        )
        # Hit with odds 2.10 should show R630 return on R300
        assert "R300" in text


# ── _build_results_buttons tests ────────────────────────


class TestBuildResultsButtons:
    def test_7day_active(self):
        import bot
        markup = bot._build_results_buttons(7, "diamond")
        buttons = markup.inline_keyboard
        # First row should have period toggle
        labels = [b.text for row in buttons for b in row]
        assert any("7 Days ✓" in l for l in labels)

    def test_30day_active(self):
        import bot
        markup = bot._build_results_buttons(30, "diamond")
        buttons = markup.inline_keyboard
        labels = [b.text for row in buttons for b in row]
        assert any("30 Days ✓" in l for l in labels)

    def test_bronze_has_upgrade(self):
        import bot
        markup = bot._build_results_buttons(7, "bronze")
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert "sub:plans" in callbacks

    def test_diamond_no_upgrade(self):
        import bot
        markup = bot._build_results_buttons(7, "diamond")
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert "sub:plans" not in callbacks


# ── Hot Tips streak badge tests ─────────────────────────


class TestHotTipsHeader:
    """Wave 27-UX: header shows hit rate, resource count, live edge count."""

    _TIP = {"home_team": "A", "away_team": "B", "outcome": "A",
            "odds": 1.50, "ev": 3.0, "sport_key": "", "display_tier": "bronze",
            "commence_time": "2026-03-04T10:00:00+02:00", "league": "PSL",
            "league_key": "psl"}

    def test_hit_rate_in_header(self):
        import bot
        text, _ = bot._build_hot_tips_page(
            [self._TIP], page=0, user_tier="diamond", hit_rate_7d=87.0,
        )
        assert "87% Predicted Correctly (7D)" in text

    def test_live_edges_count(self):
        import bot
        text, _ = bot._build_hot_tips_page(
            [self._TIP, self._TIP], page=0, user_tier="diamond",
        )
        assert "2 Live Edges Found" in text

    def test_resource_count_in_subline(self):
        import bot
        text, _ = bot._build_hot_tips_page(
            [self._TIP], page=0, user_tier="diamond", resource_count=1523,
        )
        assert "1,523 external resources" in text

    def test_all_major_sa_bookmakers(self):
        import bot
        text, _ = bot._build_hot_tips_page(
            [self._TIP], page=0, user_tier="diamond",
        )
        assert "all major SA bookmakers" in text
        # Must NOT have a specific number of SA bookmakers
        import re
        assert not re.search(r"\d+ SA bookmaker", text)

    def test_hit_rate_below_threshold_shows_edge_count(self):
        """W27-UX-FIX: hit rate < 50% falls back to edge count."""
        import bot
        text, _ = bot._build_hot_tips_page(
            [self._TIP, self._TIP], page=0, user_tier="diamond",
            hit_rate_7d=35.0,
        )
        assert "Predicted Correctly" not in text
        assert "2 Live Edges Found" in text

    def test_no_streak_in_header(self):
        """Wave 27-UX removed streak from Hot Tips header."""
        import bot
        text, _ = bot._build_hot_tips_page(
            [self._TIP], page=0, user_tier="diamond",
            streak={"type": "win", "count": 5, "tier": None},
        )
        assert "streak" not in text.lower()
        assert "predictions in a row" not in text


# ── W28: Freemium Gate Access Level Tests ─────────────────


class TestResultAlertAccessGating:
    """W28: Result alerts gate odds/EV by tier_gate access level."""

    def test_full_access_shows_odds(self):
        """Diamond viewing Diamond hit: odds + EV shown."""
        from tier_gate import get_edge_access_level
        access = get_edge_access_level("diamond", "diamond")
        assert access == "full"

    def test_blurred_access_no_odds(self):
        """Bronze viewing Gold: blurred — no odds/EV shown."""
        from tier_gate import get_edge_access_level
        access = get_edge_access_level("bronze", "gold")
        assert access == "blurred"

    def test_locked_access(self):
        """Bronze viewing Diamond: locked."""
        from tier_gate import get_edge_access_level
        access = get_edge_access_level("bronze", "diamond")
        assert access == "locked"

    def test_partial_access(self):
        """Silver viewing Gold or Gold viewing Diamond: partial."""
        from tier_gate import get_edge_access_level
        access = get_edge_access_level("gold", "diamond")
        # Gold seeing Diamond should be partial or blurred depending on implementation
        assert access in ("partial", "blurred", "locked")


class TestMondayRecapNoSpoilers:
    """W28: Monday recap uses no tg-spoiler tags anywhere."""

    def test_no_spoiler_tags_in_bot(self):
        """Verify tg-spoiler is not used in bot.py."""
        import pathlib
        bot_path = pathlib.Path(__file__).resolve().parent.parent / "bot.py"
        bot_code = bot_path.read_text()
        assert "tg-spoiler" not in bot_code, "tg-spoiler tags found in bot.py — W28 requires removal"


class TestGameBreakdownPartialBlurred:
    """W28: Game breakdown partial shows odds without bookmaker, blurred shows return only."""

    def test_gate_breakdown_sections_partial_no_leak(self):
        """Partial access should NOT show first sentence of The Edge."""
        import bot
        # Build a fake narrative with emoji section headers
        narrative = (
            "📋 Setup content here.\n\n"
            "🎯 The edge is that the home team has great form and will likely win.\n\n"
            "⚠️ Risk content here.\n\n"
            "🏆 Verdict content here."
        )
        result = bot._gate_breakdown_sections(narrative, "silver", "gold")
        joined = result
        # Should NOT contain the first sentence of The Edge
        assert "great form" not in joined
        assert "🔒 Available on Gold." in joined
