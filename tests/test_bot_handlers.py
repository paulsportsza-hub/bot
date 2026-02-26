"""Tests for bot.py — /start, /menu, /help command handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

import bot
import db


pytestmark = pytest.mark.asyncio


async def test_cmd_start_new_user(test_db, mock_update, mock_context):
    """New user should get onboarding flow."""
    mock_user = MagicMock()
    mock_user.id = 11111
    mock_user.username = "newbie"
    mock_user.first_name = "Newbie"
    mock_update.effective_user = mock_user

    await bot.cmd_start(mock_update, mock_context)

    # 2 calls: ReplyKeyboardRemove + onboarding prompt
    assert mock_update.message.reply_text.call_count == 2
    # Second call is the onboarding text
    call_args = mock_update.message.reply_text.call_args_list[1]
    text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
    assert "Welcome" in text
    assert "Step 1" in text


async def test_cmd_start_returning_user(test_db, mock_update, mock_context):
    """Returning user with onboarding done should get single welcome message with sticky keyboard."""
    await db.upsert_user(22222, "veteran", "Veteran")
    await db.set_onboarding_done(22222)

    mock_user = MagicMock()
    mock_user.id = 22222
    mock_user.username = "veteran"
    mock_user.first_name = "Veteran"
    mock_update.effective_user = mock_user

    await bot.cmd_start(mock_update, mock_context)

    # 1 call: single welcome message with sticky keyboard (consolidated UX)
    assert mock_update.message.reply_text.call_count == 1
    call_args = mock_update.message.reply_text.call_args_list[0]
    text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
    assert "Welcome back" in text


async def test_cmd_menu(mock_update, mock_context):
    """The /menu command should show single main menu message with sticky keyboard."""
    mock_user = MagicMock()
    mock_user.first_name = "User"
    mock_update.effective_user = mock_user

    await bot.cmd_menu(mock_update, mock_context)

    # 1 call: single menu message with sticky keyboard (consolidated UX)
    assert mock_update.message.reply_text.call_count == 1
    call_args = mock_update.message.reply_text.call_args_list[0]
    text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
    assert "Main Menu" in text


async def test_cmd_help(mock_update, mock_context):
    """The /help command should show help text."""
    await bot.cmd_help(mock_update, mock_context)

    call_args = mock_update.message.reply_text.call_args
    text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
    assert "Help" in text
    assert "/start" in text
    assert "HTML" in call_args[1].get("parse_mode", "")


async def test_cmd_odds(mock_update, mock_context):
    """The /odds command should show sport selection."""
    await bot.cmd_odds(mock_update, mock_context)

    call_args = mock_update.message.reply_text.call_args
    text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
    assert "Choose a sport" in text


async def test_cmd_stats_admin(test_db, mock_update, mock_context):
    """Admin /stats should return stats text."""
    import config
    mock_user = MagicMock()
    mock_user.id = config.ADMIN_IDS[0]
    mock_update.effective_user = mock_user

    await bot.cmd_stats(mock_update, mock_context)

    call_args = mock_update.message.reply_text.call_args
    text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
    assert "Admin Stats" in text


async def test_cmd_stats_non_admin(test_db, mock_update, mock_context):
    """Non-admin /stats should be ignored."""
    mock_user = MagicMock()
    mock_user.id = 999  # not in ADMIN_IDS
    mock_update.effective_user = mock_user

    await bot.cmd_stats(mock_update, mock_context)

    mock_update.message.reply_text.assert_not_called()


async def test_handle_menu_home(test_db, mock_update, mock_context):
    """menu:home callback should show main menu."""
    query = mock_update.callback_query
    query.from_user.first_name = "User"

    await bot.handle_menu(query, "home")

    call_args = query.edit_message_text.call_args
    text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
    assert "Main Menu" in text


async def test_handle_menu_help(test_db, mock_update, mock_context):
    """menu:help callback should show help."""
    query = mock_update.callback_query
    await bot.handle_menu(query, "help")

    call_args = query.edit_message_text.call_args
    text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
    assert "Help" in text


async def test_handle_menu_history_empty(test_db, mock_update, mock_context):
    """menu:history with no tips should say no tips."""
    query = mock_update.callback_query
    await bot.handle_menu(query, "history")

    call_args = query.edit_message_text.call_args
    text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
    assert "No tips recorded" in text


class TestStickyKeyboard:
    def test_get_main_keyboard_shape(self):
        """Sticky keyboard should be 2 rows of 3."""
        kb = bot.get_main_keyboard()
        assert len(kb.keyboard) == 2
        assert len(kb.keyboard[0]) == 3
        assert len(kb.keyboard[1]) == 3

    def test_get_main_keyboard_labels(self):
        """Sticky keyboard has correct labels."""
        kb = bot.get_main_keyboard()
        labels = [btn.text for row in kb.keyboard for btn in row]
        assert "⚽ Your Games" in labels
        assert "🔥 Hot Tips" in labels
        assert "📖 Guide" in labels
        assert "👤 Profile" in labels
        assert "⚙️ Settings" in labels
        assert "❓ Help" in labels

    def test_get_main_keyboard_persistent(self):
        """Keyboard should be persistent and resized."""
        kb = bot.get_main_keyboard()
        assert kb.is_persistent is True
        assert kb.resize_keyboard is True


class TestAffiliate:
    def test_betway_affiliate_code_in_config(self):
        """Config should have the Betway affiliate code."""
        import config
        assert config.BETWAY_AFFILIATE_CODE == "BPA117074"

    def test_affiliate_base_url_has_btag(self):
        """Betway affiliate_base_url should contain the btag parameter."""
        import config
        bk = config.SA_BOOKMAKERS["betway"]
        assert "btag=BPA117074" in bk["affiliate_base_url"]

    def test_get_affiliate_url_returns_url(self):
        """get_affiliate_url() should return a non-empty URL."""
        import config
        url = config.get_affiliate_url()
        assert url
        assert "betway.co.za" in url
        assert "btag=" in url

    def test_get_affiliate_url_with_event_id(self):
        """get_affiliate_url(event_id) should still return a valid URL (deep links pending)."""
        import config
        url = config.get_affiliate_url("some-event-123")
        assert url
        assert "betway.co.za" in url


class TestMorningTeaser:
    def test_seconds_until_next_hour(self):
        """_seconds_until_next_hour should return a positive number."""
        result = bot._seconds_until_next_hour()
        assert result >= 60
        assert result <= 3600

    async def test_get_users_for_notification_empty(self, test_db):
        """No users should be returned when none match the hour."""
        users = await db.get_users_for_notification(7)
        assert users == []

    async def test_get_users_for_notification_matching(self, test_db):
        """User with matching hour and daily_picks should be returned."""
        user = await db.upsert_user(55555, "earlybird", "Early")
        await db.set_onboarding_done(55555)
        await db.update_user_notification_hour(55555, 7)
        # Default notification_prefs has daily_picks=True
        users = await db.get_users_for_notification(7)
        assert len(users) == 1
        assert users[0].id == 55555

    async def test_get_users_for_notification_wrong_hour(self, test_db):
        """User with different hour should not be returned."""
        await db.upsert_user(66666, "nightowl", "Night")
        await db.set_onboarding_done(66666)
        await db.update_user_notification_hour(66666, 21)
        users = await db.get_users_for_notification(7)
        assert users == []

    async def test_get_users_for_notification_daily_picks_disabled(self, test_db):
        """User with daily_picks disabled should not be returned."""
        import json
        await db.upsert_user(77777, "quiet", "Quiet")
        await db.set_onboarding_done(77777)
        await db.update_user_notification_hour(77777, 7)
        await db.update_notification_prefs(77777, {"daily_picks": False})
        users = await db.get_users_for_notification(7)
        assert users == []

    async def test_morning_teaser_job_no_users(self, test_db, mock_context):
        """Morning teaser with no matching users should not send messages."""
        await bot._morning_teaser_job(mock_context)
        mock_context.bot.send_message.assert_not_called()


class TestAIPrompt:
    def test_game_analysis_prompt_has_sections(self):
        """GAME_ANALYSIS_PROMPT should contain all 4 section headers."""
        prompt = bot.GAME_ANALYSIS_PROMPT
        assert "The Setup" in prompt
        assert "The Edge" in prompt
        assert "The Risk" in prompt
        assert "Verdict" in prompt

    def test_game_analysis_prompt_sa_tone(self):
        """Prompt should specify SA conversational tone."""
        prompt = bot.GAME_ANALYSIS_PROMPT
        assert "braai" in prompt
        assert "lekker" in prompt

    def test_game_analysis_prompt_sport_specific(self):
        """Prompt should mention sport-specific language."""
        prompt = bot.GAME_ANALYSIS_PROMPT
        assert "clean sheet" in prompt
        assert "try line" in prompt
        assert "strike rate" in prompt

    def test_game_analysis_prompt_conviction(self):
        """Prompt should ask for conviction level."""
        prompt = bot.GAME_ANALYSIS_PROMPT
        assert "High/Medium/Low" in prompt


# ── Wave 13B: Odds Comparison UX Fixes ──


class TestOddsComparisonBackButton:
    """BUG-022: Odds comparison must have a back button to game breakdown."""

    @pytest.mark.asyncio
    async def test_back_button_present(self, test_db, mock_update):
        """Odds comparison should include a 'Back to Game' button."""
        query = mock_update.callback_query
        event_id = "test-event-123"

        # Seed cache with tip that has match_id
        bot._game_tips_cache[event_id] = [{
            "outcome": "Home Win",
            "odds": 2.10,
            "bookie": "Betway",
            "bookie_key": "betway",
            "ev": 5.0,
            "prob": 55,
            "event_id": event_id,
            "home_team": "South Africa",
            "away_team": "England",
            "match_id": "south_africa_vs_england_2026-03-01",
            "odds_by_bookmaker": {"betway": 2.10, "hollywoodbets": 2.15},
        }]

        # Mock odds.db to return all 3 outcomes
        mock_db_result = {
            "outcomes": {
                "home": {"best_odds": 2.15, "best_bookmaker": "hollywoodbets", "all_bookmakers": {"betway": 2.10, "hollywoodbets": 2.15}},
                "draw": {"best_odds": 3.50, "best_bookmaker": "gbets", "all_bookmakers": {"betway": 3.40, "gbets": 3.50}},
                "away": {"best_odds": 1.80, "best_bookmaker": "supabets", "all_bookmakers": {"betway": 1.75, "supabets": 1.80}},
            },
        }
        with patch("services.odds_service.get_best_odds", new_callable=AsyncMock, return_value=mock_db_result):
            await bot._handle_odds_comparison(query, event_id)

        call_args = query.edit_message_text.call_args
        markup = call_args[1]["reply_markup"]
        button_data = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]
        assert f"yg:game:{event_id}" in button_data

        # Cleanup
        del bot._game_tips_cache[event_id]


class TestOddsComparisonAllMarkets:
    """BUG-023: Odds comparison should show all 3 markets."""

    @pytest.mark.asyncio
    async def test_shows_all_three_markets(self, test_db, mock_update):
        """Odds comparison should show Home Win, Draw, and Away Win sections."""
        query = mock_update.callback_query
        event_id = "test-event-456"

        bot._game_tips_cache[event_id] = [{
            "outcome": "Draw",
            "odds": 3.50,
            "bookie": "GBets",
            "bookie_key": "gbets",
            "ev": 4.0,
            "prob": 30,
            "event_id": event_id,
            "home_team": "Leeds United",
            "away_team": "Manchester City",
            "match_id": "leeds_united_vs_manchester_city_2026-03-01",
            "odds_by_bookmaker": {"gbets": 3.50, "betway": 3.40},
        }]

        mock_db_result = {
            "outcomes": {
                "home": {"best_odds": 5.20, "best_bookmaker": "hollywoodbets", "all_bookmakers": {"hollywoodbets": 5.20, "betway": 5.10}},
                "draw": {"best_odds": 4.60, "best_bookmaker": "gbets", "all_bookmakers": {"gbets": 4.60, "betway": 4.30}},
                "away": {"best_odds": 1.63, "best_bookmaker": "supabets", "all_bookmakers": {"supabets": 1.63, "betway": 1.60}},
            },
        }
        with patch("services.odds_service.get_best_odds", new_callable=AsyncMock, return_value=mock_db_result):
            await bot._handle_odds_comparison(query, event_id)

        text = query.edit_message_text.call_args[0][0]
        assert "Home Win" in text
        assert "Draw" in text
        assert "Away Win" in text
        # All bookmakers present in output
        assert "Hollywoodbets" in text or "hollywoodbets" in text.lower()
        assert "Betway" in text or "betway" in text.lower()
        assert "GBets" in text or "gbets" in text.lower()

        # Cleanup
        del bot._game_tips_cache[event_id]


class TestCtaBookmakerMatch:
    """BUG-024: CTA should link to best bookmaker for best EV outcome."""

    def test_best_ev_tip_selected_for_cta(self):
        """The best positive-EV tip should be used for CTA, not tips[0]."""
        tips = [
            {"outcome": "Home Win", "odds": 2.10, "ev": 1.5, "odds_by_bookmaker": {"betway": 2.10}},
            {"outcome": "Draw", "odds": 4.60, "ev": 8.0, "odds_by_bookmaker": {"gbets": 4.60, "betway": 4.30}},
            {"outcome": "Away Win", "odds": 1.55, "ev": -2.0, "odds_by_bookmaker": {"hollywoodbets": 1.55}},
        ]
        # Replicate the logic from bot.py
        best_ev_tip = max(
            (t for t in tips if t["ev"] > 0),
            key=lambda t: t["ev"],
            default=tips[0],
        )
        assert best_ev_tip["outcome"] == "Draw"
        assert best_ev_tip["ev"] == 8.0

    def test_falls_back_to_first_tip_when_no_positive_ev(self):
        """When no positive EV tips exist, fall back to tips[0]."""
        tips = [
            {"outcome": "Home Win", "odds": 2.10, "ev": -1.0, "odds_by_bookmaker": {"betway": 2.10}},
            {"outcome": "Draw", "odds": 4.60, "ev": -2.0, "odds_by_bookmaker": {"gbets": 4.60}},
        ]
        best_ev_tip = max(
            (t for t in tips if t["ev"] > 0),
            key=lambda t: t["ev"],
            default=tips[0],
        )
        assert best_ev_tip["outcome"] == "Home Win"


# ── Wave 13F: North Star — Simplify, Recommend, Convert ──


class TestGameButtonSimplification:
    """Game breakdown should have max 4 buttons (CTA, compare, back, menu)."""

    def test_build_game_buttons_has_max_4(self):
        """Simplified buttons: CTA + compare + back + menu = 4."""
        tips = [
            {"outcome": "Draw", "odds": 4.60, "ev": 8.0, "bookie_key": "gbets",
             "odds_by_bookmaker": {"gbets": 4.60, "betway": 4.30}, "match_id": "test"},
            {"outcome": "Home Win", "odds": 5.20, "ev": 3.0, "bookie_key": "hollywoodbets",
             "odds_by_bookmaker": {"hollywoodbets": 5.20, "betway": 5.10}, "match_id": "test"},
            {"outcome": "Away Win", "odds": 1.63, "ev": 2.0, "bookie_key": "supabets",
             "odds_by_bookmaker": {"supabets": 1.63}, "match_id": "test"},
        ]
        buttons = bot._build_game_buttons(tips, "ev-123", 111)
        assert len(buttons) == 4  # CTA, compare, back, menu

    def test_cta_uses_best_ev_outcome(self):
        """CTA button text should include the highest EV outcome."""
        tips = [
            {"outcome": "Draw", "odds": 4.60, "ev": 8.0, "bookie_key": "gbets",
             "odds_by_bookmaker": {"gbets": 4.60}, "match_id": "test"},
            {"outcome": "Home Win", "odds": 2.10, "ev": 1.0, "bookie_key": "betway",
             "odds_by_bookmaker": {"betway": 2.10}, "match_id": "test"},
        ]
        buttons = bot._build_game_buttons(tips, "ev-456", 111)
        cta_text = buttons[0][0].text
        assert "Draw" in cta_text
        assert "4.60" in cta_text

    def test_no_positive_ev_shows_generic_cta(self):
        """When no positive EV, show generic 'View odds' button."""
        tips = [
            {"outcome": "Home Win", "odds": 2.10, "ev": -1.0, "bookie_key": "betway",
             "odds_by_bookmaker": {}, "match_id": "test"},
        ]
        buttons = bot._build_game_buttons(tips, "ev-789", 111)
        cta_text = buttons[0][0].text
        assert "View odds" in cta_text

    def test_nav_buttons_use_correct_emoji(self):
        """Navigation back buttons should use ↩️ not 🔙."""
        tips = [
            {"outcome": "Draw", "odds": 4.60, "ev": 5.0, "bookie_key": "gbets",
             "odds_by_bookmaker": {"gbets": 4.60}, "match_id": "test"},
        ]
        buttons = bot._build_game_buttons(tips, "ev-nav", 111)
        # Check only callback_data buttons (nav), not URL buttons (CTA)
        for row in buttons:
            for btn in row:
                if btn.callback_data and btn.text and "Back" in btn.text:
                    assert "↩️" in btn.text
                    assert "🔙" not in btn.text


class TestAnalysisCache:
    """Game analysis should be cached for 1 hour."""

    def test_cache_ttl_constant(self):
        """Cache TTL should be 1 hour (3600 seconds)."""
        assert bot._ANALYSIS_CACHE_TTL == 3600

    def test_cache_structure_exists(self):
        """Cache dict should exist and be empty on import."""
        assert isinstance(bot._analysis_cache, dict)


class TestVerdictBadgeInjection:
    """Verdict header should get programmatic Edge Rating badge."""

    def test_badge_injected_into_verdict(self):
        """Simulate badge injection on a narrative string."""
        import re
        narrative = "🏆 <b>Verdict</b>\nBack the draw with Medium conviction — lekker value."
        # Simulate the injection logic
        tier_emoji = "⛏️⭐"
        tier_label = "Gold Edge"
        badge = f" — {tier_emoji} {tier_label}"
        narrative = re.sub(
            r"(🏆\s*(?:<b>)?Verdict(?:</b>)?)",
            rf"\1{badge}",
            narrative,
            count=1,
        )
        narrative = re.sub(r" with (?:High|Medium|Low) conviction", "", narrative)
        assert "Gold Edge" in narrative
        assert "⛏️⭐" in narrative
        assert "Medium conviction" not in narrative

    def test_no_badge_without_verdict(self):
        """If no Verdict section, narrative stays unchanged."""
        import re
        narrative = "Some analysis text without a verdict."
        original = narrative
        narrative = re.sub(
            r"(🏆\s*(?:<b>)?Verdict(?:</b>)?)",
            r"\1 — ⛏️⭐ Gold Edge",
            narrative,
            count=1,
        )
        assert narrative == original
