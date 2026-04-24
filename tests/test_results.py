"""Unit tests for Edge Tracker / Results Display (Wave 23)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
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
            "league_key": "psl", "edge_score": 50}

    def test_hit_rate_in_header(self):
        import bot
        text, *_ = asyncio.run(bot._build_hot_tips_page(
            [self._TIP], page=0, user_tier="diamond", hit_rate_7d=87.0,
        ))
        assert "87% Predicted Correctly (7D)" in text

    def test_live_edges_count(self):
        import bot
        text, *_ = asyncio.run(bot._build_hot_tips_page(
            [self._TIP, self._TIP], page=0, user_tier="diamond",
        ))
        assert "2 Live Edges Found" in text

    def test_resource_count_in_subline(self):
        import bot
        text, *_ = asyncio.run(bot._build_hot_tips_page(
            [self._TIP], page=0, user_tier="diamond", resource_count=1523,
        ))
        assert "1,523 external resources" in text

    def test_all_major_sa_bookmakers(self):
        import bot
        text, *_ = asyncio.run(bot._build_hot_tips_page(
            [self._TIP], page=0, user_tier="diamond",
        ))
        assert "all major SA bookmakers" in text
        # Must NOT have a specific number of SA bookmakers
        import re
        assert not re.search(r"\d+ SA bookmaker", text)

    def test_hit_rate_below_threshold_shows_edge_count(self):
        """W27-UX-FIX: hit rate < 50% falls back to edge count."""
        import bot
        text, *_ = asyncio.run(bot._build_hot_tips_page(
            [self._TIP, self._TIP], page=0, user_tier="diamond",
            hit_rate_7d=35.0,
        ))
        assert "Predicted Correctly" not in text
        assert "2 Live Edges Found" in text

    def test_no_streak_in_header(self):
        """Wave 27-UX removed streak from Hot Tips header."""
        import bot
        text, *_ = asyncio.run(bot._build_hot_tips_page(
            [self._TIP], page=0, user_tier="diamond",
            streak={"type": "win", "count": 5, "tier": None},
        ))
        assert "streak" not in text.lower()
        assert "predictions in a row" not in text


class TestHotTipsResultProof:
    _TIP = {
        "home_team": "A", "away_team": "B", "outcome": "A",
        "odds": 1.50, "ev": 3.0, "sport_key": "", "display_tier": "bronze",
        "commence_time": "2026-03-04T10:00:00+02:00", "league": "PSL",
        "league_key": "psl", "match_id": "a_vs_b_2026-03-04", "event_id": "a_vs_b_2026-03-04",
        "edge_score": 50,
    }

    def test_track_record_header_shows_last_10_and_negative_roi(self):
        import bot
        text, *_ = asyncio.run(bot._build_hot_tips_page(
            [self._TIP],
            page=0,
            user_tier="diamond",
            hit_rate_7d=38.0,
            last_10_results=["hit", "miss", "hit", "hit", "miss", "hit", "miss", "hit", "hit", "miss"],
            roi_7d=-4.2,
            edge_tracker_summary={"has_data": True, "total": 50, "hits": 25, "hit_rate_pct": 50.0, "roi": -4.2},
        ))
        assert "Last 10 Edges:" in text
        assert "7D ROI:" in text
        assert "-4.2%" in text

    def test_track_record_header_omits_sequence_under_10_settled(self):
        import bot
        text, *_ = asyncio.run(bot._build_hot_tips_page(
            [self._TIP],
            page=0,
            user_tier="diamond",
            last_10_results=["hit", "miss", "hit"],
            roi_7d=1.5,
            edge_tracker_summary={"has_data": True, "total": 50, "hits": 25, "hit_rate_pct": 50.0, "roi": 1.5},
        ))
        assert "Last 10:" not in text
        assert "7D ROI:" in text
        assert "+1.5%" in text

    def test_recently_settled_badges_are_informational_only(self):
        import bot
        recent = [
            {
                "match_key": "chiefs_vs_pirates_2026-03-13",
                "sport": "soccer",
                "league": "psl",
                "edge_tier": "gold",
                "bet_type": "Home Win",
                "recommended_odds": 2.10,
                "actual_return": 210.0,
                "result": "hit",
                "match_date": "2026-03-13",
            },
            {
                "match_key": "sundowns_vs_city_2026-03-13",
                "sport": "soccer",
                "league": "psl",
                "edge_tier": "bronze",
                "bet_type": "Away Win",
                "recommended_odds": 1.80,
                "actual_return": 0.0,
                "result": "miss",
                "match_date": "2026-03-13",
            },
        ]
        text, markup, _ = asyncio.run(bot._build_hot_tips_page(
            [self._TIP],
            page=0,
            user_tier="diamond",
            recently_settled=recent,
        ))
        assert "Recent Results" in text
        assert "✅ HIT" in text
        assert "❌ MISS" in text
        callbacks = [
            btn.callback_data
            for row in markup.inline_keyboard
            for btn in row
            if getattr(btn, "callback_data", "")
        ]
        assert sum(1 for cb in callbacks if cb.startswith("ep:pick:")) == 1

    def test_yesterday_all_misses_use_honest_language(self):
        import bot
        yesterday = [
            {
                "match_key": "chiefs_vs_pirates_2026-03-13",
                "sport": "soccer",
                "league": "psl",
                "edge_tier": "gold",
                "recommended_odds": 2.10,
                "actual_return": 0.0,
                "result": "miss",
            },
            {
                "match_key": "sundowns_vs_city_2026-03-13",
                "sport": "soccer",
                "league": "psl",
                "edge_tier": "bronze",
                "recommended_odds": 1.80,
                "actual_return": 0.0,
                "result": "miss",
            },
        ]
        text, *_ = asyncio.run(bot._build_hot_tips_page(
            [self._TIP],
            page=0,
            user_tier="diamond",
            yesterday_results=yesterday,
            edge_tracker_summary={"has_data": True, "total": 50, "hits": 25, "hit_rate_pct": 50.0, "roi": 0.0},
        ))
        assert "Yesterday:" in text
        assert "0/2 hit (0%)" in text
        assert "All 2 missed yesterday." in text

    def test_tier_track_record_line_requires_sufficient_sample(self):
        import bot
        line = bot._format_tier_track_record_line(
            {"by_tier": {"gold": {"total": 6, "hits": 4, "hit_rate": 0.667}}},
            "gold",
        )
        assert "Gold edges hit" in line
        assert "67%" in line
        assert "(4/6 settled)" in line

        no_line = bot._format_tier_track_record_line(
            {"by_tier": {"gold": {"total": 2, "hits": 2, "hit_rate": 1.0}}},
            "gold",
        )
        assert no_line == ""

    def test_header_fallback_uses_settlement_summary_when_track_record_line_empty(self):
        import bot

        edge_summary = {
            "has_data": True,
            "total": 50,
            "hits": 34,
            "hit_rate_pct": 68.0,
            "roi": 12.1,
        }
        text, *_ = asyncio.run(bot._build_hot_tips_page(
            [self._TIP],
            page=0,
            user_tier="diamond",
            last_10_results=[],
            roi_7d=None,
            edge_tracker_summary=edge_summary,
        ))

        assert "📊 7D: 34/50 hit (68%)" in text

    @pytest.mark.skip(reason="results:7 button removed from Hot Tips footer markup (W26A+)")
    def test_footer_proof_line_and_results_button_are_discoverable(self):
        import bot

        locked_tip = dict(self._TIP, display_tier="gold", edge_rating="gold")
        edge_summary = {
            "has_data": True,
            "total": 34,
            "hits": 23,
            "hit_rate_pct": 67.6,
            "roi": 12.1,
        }
        text, markup, _ = asyncio.run(bot._build_hot_tips_page(
            [locked_tip],
            page=0,
            user_tier="bronze",
            edge_tracker_summary=edge_summary,
        ))

        assert "📊 Last 7D: 23/34 hit (68%) · ROI +12.1%" in text
        assert text.index("📊 Last 7D: 23/34 hit (68%) · ROI +12.1%") < text.index("🔑 Unlock all → /subscribe")
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert "results:7" in callbacks

    def test_footer_proof_line_omits_cleanly_when_no_settlement_data(self):
        import bot

        locked_tip = dict(self._TIP, display_tier="gold", edge_rating="gold")
        text, *_ = asyncio.run(bot._build_hot_tips_page(
            [locked_tip],
            page=0,
            user_tier="bronze",
            edge_tracker_summary=bot._empty_edge_tracker_summary(),
        ))

        assert "0/0" not in text
        assert "📊 Last 7D:" not in text


class TestProfileEdgePerformance:
    @pytest.mark.asyncio
    async def test_profile_shows_paid_identity_stats_and_hub_buttons_for_effective_gold_user(self):
        import bot

        profile_data = {
            "experience_label": "Experienced",
            "sports": [
                {
                    "label": "Soccer",
                    "emoji": "⚽",
                    "leagues": [{"label": "PSL", "teams": ["Chiefs", "Sundowns", "Pirates"]}],
                },
            ],
            "risk_label": "Moderate",
            "bankroll_str": "R500",
            "notify_str": "Morning (07:00 SAST)",
        }
        edge_summary = {
            "has_data": True,
            "hits": 23,
            "total": 34,
            "hit_rate_pct": 67.6,
            "roi": 12.1,
            "streak": {"type": "win", "count": 4},
        }
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        user = SimpleNamespace(
            first_name="Mpho",
            joined_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            subscription_started_at=datetime(2026, 2, 10, tzinfo=timezone.utc),
            trial_start_date=None,
            trial_end_date=None,
            is_founding_member=False,
            user_tier="bronze",
        )

        with patch("bot.get_profile_data", new=AsyncMock(return_value=profile_data)), \
             patch("bot.db.get_user", new=AsyncMock(return_value=user)), \
             patch("bot.db.is_premium", side_effect=AssertionError("Profile CTA should use effective tier, not db.is_premium")), \
             patch("bot.db.is_trial_active", new=AsyncMock(return_value=False)), \
             patch("bot.get_effective_tier", new=AsyncMock(return_value="gold")), \
             patch("bot.db.get_profile_engagement_stats", new=AsyncMock(return_value={"total_edge_views": 18, "recent_edge_views": 4, "days_with_mzansiedge": 46})), \
             patch("bot._get_edge_tracker_summary", new=AsyncMock(return_value=edge_summary)):
            summary = await bot.format_profile_summary(123, surface="profile")
            await bot._show_profile(update, 123)

        assert "🥇 <b>Gold Member</b>" in summary
        assert "📈 <b>Your Activity</b>" in summary
        assert "👀 <b>Edges seen:</b> 18" in summary
        assert "📆 <b>With MzansiEdge:</b> 46 days" in summary
        assert "📊 <b>Your Edge Performance (7D)</b>" in summary
        assert "You've seen <b>4</b> edges this week. <b>23/34</b> hit so far on the tracked board (68%)." in summary
        assert "💰 <b>7D ROI:</b> +12.1%" in summary
        assert "🔥 Streak: <b>4 wins</b>" in summary

        markup = update.message.reply_text.call_args.kwargs["reply_markup"]
        labels = [b.text for row in markup.inline_keyboard for b in row]
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert "📋 My Plan" in labels
        assert "💎 Edge Picks" in labels
        assert "results:7" in callbacks
        assert "sub:billing" in callbacks
        assert "sub:plans" not in callbacks

    @pytest.mark.asyncio
    async def test_profile_shows_trial_identity_and_low_data_guidance(self):
        import bot

        profile_data = {
            "experience_label": "I'm new to betting",
            "sports": [],
            "risk_label": "Conservative",
            "bankroll_str": "Not set",
            "notify_str": "Not set",
        }
        now = datetime.now(timezone.utc)
        user = SimpleNamespace(
            first_name="Lebo",
            joined_at=now - timedelta(days=1),
            subscription_started_at=None,
            trial_start_date=now - timedelta(days=2),
            trial_end_date=now + timedelta(days=5),
            is_founding_member=False,
            user_tier="diamond",
        )
        update = MagicMock()
        update.message.reply_text = AsyncMock()

        with patch("bot.get_profile_data", new=AsyncMock(return_value=profile_data)), \
             patch("bot.db.get_user", new=AsyncMock(return_value=user)), \
             patch("bot.db.is_trial_active", new=AsyncMock(return_value=True)), \
             patch("bot.get_effective_tier", new=AsyncMock(return_value="diamond")), \
             patch("bot.db.get_profile_engagement_stats", new=AsyncMock(return_value={"total_edge_views": 0, "recent_edge_views": 0, "days_with_mzansiedge": 2})), \
             patch("bot._get_edge_tracker_summary", new=AsyncMock(return_value=bot._empty_edge_tracker_summary())):
            summary = await bot.format_profile_summary(123, surface="profile")
            await bot._show_profile(update, 123)

        assert "💎 <b>Diamond Trial — Day" in summary
        assert "day" in summary.lower()
        assert "You're just getting started." in summary
        assert "No settled 7-day results yet." in summary
        assert "No teams saved yet." in summary
        assert "Not set" not in summary

        markup = update.message.reply_text.call_args.kwargs["reply_markup"]
        labels = [b.text for row in markup.inline_keyboard for b in row]
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert "✨ View Plans" in labels
        assert "📋 My Plan" not in labels
        assert "sub:plans" in callbacks
        assert "sub:billing" not in callbacks

    @pytest.mark.asyncio
    async def test_profile_shows_bronze_identity_and_plan_cta(self):
        import bot

        profile_data = {
            "experience_label": "I bet sometimes",
            "sports": [{"label": "Soccer", "emoji": "⚽", "leagues": [{"label": "EPL", "teams": ["Arsenal"]}]}],
            "risk_label": "Moderate",
            "bankroll_str": "Not set",
            "notify_str": "Morning (07:00 SAST)",
        }
        user = SimpleNamespace(
            first_name="Anele",
            joined_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            subscription_started_at=None,
            trial_start_date=None,
            trial_end_date=None,
            is_founding_member=False,
            user_tier="bronze",
        )
        update = MagicMock()
        update.message.reply_text = AsyncMock()

        with patch("bot.get_profile_data", new=AsyncMock(return_value=profile_data)), \
             patch("bot.db.get_user", new=AsyncMock(return_value=user)), \
             patch("bot.db.is_trial_active", new=AsyncMock(return_value=False)), \
             patch("bot.get_effective_tier", new=AsyncMock(return_value="bronze")), \
             patch("bot.db.get_profile_engagement_stats", new=AsyncMock(return_value={"total_edge_views": 3, "recent_edge_views": 1, "days_with_mzansiedge": 18})), \
             patch("bot._get_edge_tracker_summary", new=AsyncMock(return_value=bot._empty_edge_tracker_summary())):
            summary = await bot.format_profile_summary(123, surface="profile")
            await bot._show_profile(update, 123)

        assert "🥉 <b>Bronze (Free)</b>" in summary
        labels = [b.text for row in update.message.reply_text.call_args.kwargs["reply_markup"].inline_keyboard for b in row]
        callbacks = [b.callback_data for row in update.message.reply_text.call_args.kwargs["reply_markup"].inline_keyboard for b in row]
        assert "✨ View Plans" in labels
        assert "📋 My Plan" not in labels
        assert "sub:plans" in callbacks
        assert "sub:billing" not in callbacks

    @pytest.mark.asyncio
    async def test_settings_summary_stays_on_shared_compact_renderer(self):
        import bot

        profile_data = {
            "experience_label": "Experienced",
            "sports": [],
            "risk_label": "Moderate",
            "bankroll_str": "R500",
            "notify_str": "Morning (07:00 SAST)",
        }
        edge_summary = {
            "has_data": True,
            "hits": 10,
            "total": 14,
            "hit_rate_pct": 71.4,
            "roi": 8.2,
            "streak": {"type": "win", "count": 3},
        }

        with patch("bot.get_profile_data", new=AsyncMock(return_value=profile_data)), \
             patch("bot._get_edge_tracker_summary", new=AsyncMock(return_value=edge_summary)):
            summary = await bot.format_profile_summary(123)

        assert "📋 <b>Your MzansiEdge Profile</b>" in summary
        assert "🥇 <b>Gold Member</b>" not in summary
        assert "📈 <b>Engagement</b>" not in summary
        assert "📊 <b>Edge Performance (7D)</b>" in summary

    @pytest.mark.asyncio
    async def test_profile_plan_callback_routes_to_plan_surface(self):
        import bot

        query = MagicMock()
        query.from_user.id = 123
        query.edit_message_text = AsyncMock()
        ctx = MagicMock()
        markup = MagicMock()

        with patch("bot._render_profile_plan_surface", new=AsyncMock(return_value=("plan text", markup))):
            await bot._dispatch_button(query, ctx, "sub", "billing")

        query.edit_message_text.assert_awaited_once_with(
            "plan text",
            parse_mode=bot.ParseMode.HTML,
            reply_markup=markup,
        )


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
        # Gold seeing Diamond is locked (TIER-GATE-IMPL-01)
        assert access == "locked"


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
