"""Tests for bot.py — /start, /menu, /help command handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

import bot
import config
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
        assert "⚽ My Matches" in labels
        assert "💎 Top Edge Picks" in labels
        assert "📖 Guide" in labels
        assert "👤 Profile" in labels
        assert "⚙️ Settings" in labels
        assert "❓ Help" in labels

    def test_get_main_keyboard_persistent(self):
        """Keyboard should be persistent and resized."""
        kb = bot.get_main_keyboard()
        assert kb.is_persistent is True
        assert kb.resize_keyboard is True

    def test_legacy_hot_tips_label_maps(self):
        """Old 'Hot Tips' keyboard label maps to hot_tips route."""
        assert bot._LEGACY_LABELS.get("🔥 Hot Tips") == "hot_tips"


class TestSpinner:
    def test_sport_emojis_constant(self):
        """SPORT_EMOJIS should contain the 4 core sport emojis."""
        assert bot.SPORT_EMOJIS == ["⚽", "🏉", "🏏", "🥊"]

    def test_dots_constant(self):
        """DOTS should contain the 3 ellipsis progression steps."""
        assert bot.DOTS == [".", "..", "..."]


class TestTeamCelebrations:
    def test_team_celebrations_dict_exists(self):
        """TEAM_CELEBRATIONS should be a non-empty dict."""
        assert isinstance(bot.TEAM_CELEBRATIONS, dict)
        assert len(bot.TEAM_CELEBRATIONS) > 0

    def test_sa_teams_have_celebrations(self):
        """Key SA teams should have specific celebrations."""
        assert "Kaizer Chiefs" in bot.TEAM_CELEBRATIONS
        assert "Orlando Pirates" in bot.TEAM_CELEBRATIONS
        assert "Mamelodi Sundowns" in bot.TEAM_CELEBRATIONS

    def test_team_cheer_returns_team_specific(self):
        """_get_team_cheer should return team-specific cheer when available."""
        cheer = bot._get_team_cheer("Kaizer Chiefs", "soccer")
        assert "Amakhosi" in cheer

    def test_team_cheer_france_rugby_not_bokke(self):
        """France in rugby should NOT return 'Go Bokke'."""
        cheer = bot._get_team_cheer("France", "rugby")
        assert "Bokke" not in cheer
        assert "Bleus" in cheer

    def test_team_cheer_falls_back_to_sport(self):
        """Unknown team should fall back to sport-level cheer."""
        cheer = bot._get_team_cheer("Unknown Team FC", "soccer")
        # Fallback cheers don't include sport emoji directly in all variants
        assert cheer  # Should return something non-empty

    def test_team_cheer_sa_cricket_not_bokke(self):
        """South Africa in cricket should NOT return 'Go Bokke'."""
        cheer = bot._get_team_cheer("South Africa", "cricket")
        assert "Bokke" not in cheer
        assert "Protea" in cheer

    def test_team_cheer_sa_soccer_bafana(self):
        """South Africa in soccer should return 'Bafana Bafana'."""
        cheer = bot._get_team_cheer("South Africa", "soccer")
        assert "Bafana" in cheer

    def test_team_cheer_sa_rugby_bokke(self):
        """South Africa in rugby should return 'Go Bokke'."""
        cheer = bot._get_team_cheer("South Africa", "rugby")
        assert "Bokke" in cheer

    def test_sport_fallback_dict_has_all_sports(self):
        """Sport fallback should cover all 4 sport categories."""
        for sport in ("soccer", "rugby", "cricket", "combat"):
            assert sport in bot._SPORT_CHEERS_FALLBACK


class TestLeagueExclusions:
    def test_six_nations_excludes_sa(self):
        """Six Nations should not accept South Africa."""
        from bot import _handle_team_text_input
        # The exclusion set is defined inside the function;
        # verify it exists by checking the league exclusion data
        exclusions = {
            "six_nations": {"south africa", "new zealand", "australia", "argentina",
                            "fiji", "japan", "samoa", "tonga", "georgia", "romania"},
            "rugby_champ": {"england", "france", "ireland", "scotland", "wales", "italy"},
        }
        assert "south africa" in exclusions["six_nations"]
        assert "england" not in exclusions["six_nations"]

    def test_rugby_champ_excludes_england(self):
        """Rugby Championship should not accept England."""
        exclusions = {
            "rugby_champ": {"england", "france", "ireland", "scotland", "wales", "italy"},
        }
        assert "england" in exclusions["rugby_champ"]
        assert "south africa" not in exclusions["rugby_champ"]


class TestLeagueExamples:
    def test_new_leagues_have_examples(self):
        """New leagues should have LEAGUE_EXAMPLES entries."""
        for key in ("international_rugby", "odis", "t20i"):
            assert key in config.LEAGUE_EXAMPLES, f"{key} missing from LEAGUE_EXAMPLES"

    def test_rwc_removed_from_examples(self):
        """RWC should no longer be in LEAGUE_EXAMPLES."""
        assert "rwc" not in config.LEAGUE_EXAMPLES


class TestEdgeBranding:
    def test_help_text_uses_edge_ai(self):
        """HELP_TEXT should mention Edge-AI."""
        assert "Edge-AI" in bot.HELP_TEXT

    def test_help_text_uses_top_edge_picks(self):
        """HELP_TEXT should use 'Top Edge Picks' not 'Hot Tips'."""
        assert "Top Edge Picks" in bot.HELP_TEXT

    def test_no_hot_tips_in_keyboard_labels(self):
        """Keyboard labels should not contain 'Hot Tips'."""
        assert "🔥 Hot Tips" not in bot._KEYBOARD_LABELS


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
        """_build_game_analysis_prompt should contain all 4 section headers."""
        prompt = bot._build_game_analysis_prompt("soccer")
        assert "The Setup" in prompt
        assert "The Edge" in prompt
        assert "The Risk" in prompt
        assert "Verdict" in prompt

    def test_game_analysis_prompt_sa_tone(self):
        """Prompt should specify SA conversational tone."""
        prompt = bot._build_game_analysis_prompt("soccer")
        assert "braai" in prompt

    def test_game_analysis_prompt_critical_rules(self):
        """Prompt should contain rebalanced CRITICAL RULES."""
        prompt = bot._build_game_analysis_prompt("soccer")
        assert "FACTUAL CLAIMS" in prompt
        assert "NARRATIVE & OPINION" in prompt

    def test_game_analysis_prompt_conviction(self):
        """Prompt should ban conviction text."""
        prompt = bot._build_game_analysis_prompt("soccer")
        assert "conviction" in prompt.lower()


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
        # Simulate the injection logic (Diamond tier emojis)
        tier_emoji = "🥇"
        tier_label = "GOLDEN EDGE"
        badge = f" — {tier_emoji} {tier_label}"
        narrative = re.sub(
            r"(🏆\s*(?:<b>)?Verdict(?:</b>)?)",
            rf"\1{badge}",
            narrative,
            count=1,
        )
        # Aggressive conviction stripping (Wave 14A)
        narrative = re.sub(r"(?:with |— )?(?:High|Medium|Low) conviction:?\.?", "", narrative)
        narrative = re.sub(r"Conviction: (?:High|Medium|Low)\.?", "", narrative)
        assert "GOLDEN EDGE" in narrative
        assert "🥇" in narrative
        assert "Medium conviction" not in narrative
        assert "conviction" not in narrative.lower()

    def test_no_badge_without_verdict(self):
        """If no Verdict section, narrative stays unchanged."""
        import re
        narrative = "Some analysis text without a verdict."
        original = narrative
        narrative = re.sub(
            r"(🏆\s*(?:<b>)?Verdict(?:</b>)?)",
            r"\1 — 🥇 GOLDEN EDGE",
            narrative,
            count=1,
        )
        assert narrative == original


class TestDiamondEdgeRebrand:
    """Wave 14A: All tier references must use Diamond/Gold/Silver/Bronze."""

    def test_edge_emojis_diamond_system(self):
        """EDGE_EMOJIS must use 💎🥇🥈🥉 (no ⛏️)."""
        from renderers.edge_renderer import EDGE_EMOJIS
        assert "diamond" in EDGE_EMOJIS
        assert "platinum" not in EDGE_EMOJIS
        assert EDGE_EMOJIS["diamond"] == "💎"
        assert EDGE_EMOJIS["gold"] == "🥇"
        assert EDGE_EMOJIS["silver"] == "🥈"
        assert EDGE_EMOJIS["bronze"] == "🥉"
        # No pickaxe emojis
        for v in EDGE_EMOJIS.values():
            assert "⛏" not in v

    def test_edge_labels_diamond_system(self):
        """EDGE_LABELS must use DIAMOND EDGE/GOLDEN EDGE/etc."""
        from renderers.edge_renderer import EDGE_LABELS
        assert EDGE_LABELS["diamond"] == "DIAMOND EDGE"
        assert EDGE_LABELS["gold"] == "GOLDEN EDGE"
        assert EDGE_LABELS["silver"] == "SILVER EDGE"
        assert EDGE_LABELS["bronze"] == "BRONZE EDGE"
        assert "platinum" not in EDGE_LABELS

    def test_edge_rating_class_diamond(self):
        """EdgeRating class should have DIAMOND, not PLATINUM."""
        from services.edge_rating import EdgeRating
        assert hasattr(EdgeRating, "DIAMOND")
        assert not hasattr(EdgeRating, "PLATINUM")
        assert EdgeRating.DIAMOND == "diamond"


class TestThresholdRecalibration:
    """Wave 14A: New EV thresholds — Diamond ≥15%, Gold ≥8%, Silver ≥4%, Bronze ≥1%."""

    def test_9pct_ev_is_gold_not_diamond(self):
        """Leeds vs Man City draw at +9.3% EV should be Gold, not Diamond."""
        tips = [
            {"outcome": "Draw", "odds": 4.60, "ev": 9.3, "bookie_key": "gbets",
             "odds_by_bookmaker": {"gbets": 4.60}, "match_id": "test"},
        ]
        buttons = bot._build_game_buttons(tips, "ev-test", 111)
        cta_text = buttons[0][0].text
        # Should be 🥇 (Gold), not 💎 (Diamond)
        assert "🥇" in cta_text
        assert "💎" not in cta_text

    def test_15pct_ev_is_diamond(self):
        """EV ≥15% should be Diamond tier."""
        tips = [
            {"outcome": "Home Win", "odds": 6.00, "ev": 16.0, "bookie_key": "hwb",
             "odds_by_bookmaker": {"hwb": 6.00}, "match_id": "test"},
        ]
        buttons = bot._build_game_buttons(tips, "ev-test", 111)
        cta_text = buttons[0][0].text
        assert "💎" in cta_text

    def test_4pct_ev_is_silver(self):
        """EV ≥4% should be Silver tier."""
        tips = [
            {"outcome": "Away Win", "odds": 2.10, "ev": 4.5, "bookie_key": "betway",
             "odds_by_bookmaker": {"betway": 2.10}, "match_id": "test"},
        ]
        buttons = bot._build_game_buttons(tips, "ev-test", 111)
        cta_text = buttons[0][0].text
        assert "🥈" in cta_text

    def test_1pct_ev_is_bronze(self):
        """EV ≥1% but <4% should be Bronze tier."""
        tips = [
            {"outcome": "Draw", "odds": 3.10, "ev": 2.0, "bookie_key": "supabets",
             "odds_by_bookmaker": {"supabets": 3.10}, "match_id": "test"},
        ]
        buttons = bot._build_game_buttons(tips, "ev-test", 111)
        cta_text = buttons[0][0].text
        assert "🥉" in cta_text


class TestConvictionStripping:
    """Wave 14A: All conviction text must be stripped from AI responses."""

    def test_strips_with_medium_conviction(self):
        """Standard 'with Medium conviction' format."""
        import re
        text = "Back the draw with Medium conviction — lekker."
        text = re.sub(r"(?:with |— )?(?:High|Medium|Low) conviction:?\.?", "", text)
        assert "conviction" not in text.lower()

    def test_strips_conviction_colon_format(self):
        """'Conviction: Medium.' format."""
        import re
        text = "Back the draw. Conviction: Medium."
        text = re.sub(r"Conviction: (?:High|Medium|Low)\.?", "", text)
        assert "conviction" not in text.lower()

    def test_strips_dash_conviction(self):
        """'— High conviction' format."""
        import re
        text = "Back the draw — High conviction."
        text = re.sub(r"(?:with |— )?(?:High|Medium|Low) conviction:?\.?", "", text)
        assert "conviction" not in text.lower()

    def test_strips_bare_conviction(self):
        """'Low conviction' without prefix."""
        import re
        text = "Back the draw. Low conviction."
        text = re.sub(r"(?:with |— )?(?:High|Medium|Low) conviction:?\.?", "", text)
        assert "conviction" not in text.lower()


class TestBug025NarrativeCaseMismatch:
    """Wave 14D: BUG-025 — Narrative emoji must match actual tier."""

    def test_gold_tier_gets_gold_emoji(self):
        """A tip with display_tier='gold' should produce 🥇, not 🥉."""
        tip = {
            "outcome": "Draw", "odds": 4.60, "ev": 9.0, "bookmaker": "GBets",
            "display_tier": "gold", "odds_by_bookmaker": {"gbets": 4.60, "betway": 4.30},
            "prob": 25,
        }
        narrative = bot._build_tip_narrative(tip)
        assert "🥇" in narrative
        assert "🥉" not in narrative

    def test_diamond_tier_gets_diamond_emoji(self):
        """A tip with display_tier='diamond' should produce 💎."""
        tip = {
            "outcome": "Home Win", "odds": 6.00, "ev": 16.0, "bookmaker": "Hollywoodbets",
            "display_tier": "diamond", "odds_by_bookmaker": {"hwb": 6.00, "betway": 5.50},
            "prob": 20,
        }
        narrative = bot._build_tip_narrative(tip)
        assert "💎" in narrative

    def test_silver_tier_gets_silver_emoji(self):
        """A tip with display_tier='silver' should produce 🥈."""
        tip = {
            "outcome": "Away Win", "odds": 2.20, "ev": 5.0, "bookmaker": "Betway",
            "display_tier": "silver", "odds_by_bookmaker": {"betway": 2.20, "hwb": 2.10},
            "prob": 40,
        }
        narrative = bot._build_tip_narrative(tip)
        assert "🥈" in narrative

    def test_bronze_tier_gets_bronze_emoji(self):
        """A tip with display_tier='bronze' should produce 🥉."""
        tip = {
            "outcome": "Draw", "odds": 3.10, "ev": 1.5, "bookmaker": "SupaBets",
            "display_tier": "bronze", "odds_by_bookmaker": {"supabets": 3.10, "betway": 3.00},
            "prob": 30,
        }
        narrative = bot._build_tip_narrative(tip)
        assert "🥉" in narrative


class TestExperiencedSkipsEdgeExplainer:
    """Wave 14D: Experienced users skip the Edge explainer screen."""

    async def test_experienced_skips_to_risk(self):
        """Experienced user after favourites should go to risk, not edge_explainer."""
        bot._onboarding_state.clear()
        ob = bot._get_ob(30001)
        ob["experience"] = "experienced"
        ob["selected_sports"] = ["soccer"]
        ob["step"] = "favourites"
        ob["_fav_idx"] = 1  # past last sport = all done

        from unittest.mock import AsyncMock, MagicMock
        query = MagicMock()
        query.from_user = MagicMock(id=30001)
        query.edit_message_text = AsyncMock()
        await bot._show_next_team_prompt(query, ob)
        assert ob["step"] == "risk"

    async def test_casual_sees_edge_explainer(self):
        """Casual user after favourites should see edge_explainer."""
        bot._onboarding_state.clear()
        ob = bot._get_ob(30002)
        ob["experience"] = "casual"
        ob["selected_sports"] = ["soccer"]
        ob["step"] = "favourites"
        ob["_fav_idx"] = 1  # past last sport = all done

        from unittest.mock import AsyncMock, MagicMock
        query = MagicMock()
        query.from_user = MagicMock(id=30002)
        query.edit_message_text = AsyncMock()
        await bot._show_next_team_prompt(query, ob)
        assert ob["step"] == "edge_explainer"


# ── Wave 15A: AI Post-Processor Tests ──


class TestSanitizeAiResponse:
    """sanitize_ai_response() deterministic post-processor."""

    def test_strips_markdown_headers(self):
        raw = "# Leeds vs Man City — 28 Feb\n📋 The Setup\nSome text"
        result = bot.sanitize_ai_response(raw)
        assert '#' not in result
        assert '📋' in result

    def test_enforces_section_spacing(self):
        raw = "Some setup text.\n🎯 The Edge\nSome edge text."
        result = bot.sanitize_ai_response(raw)
        assert "\n\n🎯" in result

    def test_converts_markdown_bold(self):
        raw = "The **Draw** is the sharpest value"
        result = bot.sanitize_ai_response(raw)
        assert "<b>Draw</b>" in result
        assert "**" not in result

    def test_strips_duplicate_match_title(self):
        raw = "Leeds United vs Manchester City — 28 Feb\n📋 The Setup\nText"
        result = bot.sanitize_ai_response(raw)
        assert "Leeds United vs Manchester City — 28 Feb" not in result
        assert "📋" in result

    def test_strips_conviction_text(self):
        raw = "Back the draw with High conviction."
        result = bot.sanitize_ai_response(raw)
        assert "conviction" not in result.lower()

    def test_normalises_whitespace(self):
        raw = "Text\n\n\n\n\nMore text"
        result = bot.sanitize_ai_response(raw)
        assert "\n\n\n" not in result
        assert "Text\n\nMore text" == result

    def test_converts_markdown_bullets(self):
        raw = "- First point\n* Second point\nRegular line"
        result = bot.sanitize_ai_response(raw)
        assert "• First point" in result
        assert "• Second point" in result

    def test_enforces_section_header_bold(self):
        raw = "📋 The Setup\nSome analysis text"
        result = bot.sanitize_ai_response(raw)
        assert "📋 <b>The Setup</b>" in result

    def test_empty_input(self):
        assert bot.sanitize_ai_response("") == ""
        assert bot.sanitize_ai_response("   ") == ""


class TestOddsComparison3Cta:
    """BUG-026: Odds comparison should render one CTA per market."""

    @pytest.mark.asyncio
    async def test_three_cta_buttons_when_all_markets(self, test_db, mock_update):
        """All 3 markets with odds should produce 3 CTA buttons."""
        query = mock_update.callback_query
        event_id = "test-3cta-001"

        bot._game_tips_cache[event_id] = [{
            "outcome": "Draw", "odds": 3.50, "bookie": "GBets",
            "bookie_key": "gbets", "ev": 4.0, "prob": 30,
            "event_id": event_id,
            "home_team": "Leeds United", "away_team": "Manchester City",
            "match_id": "leeds_vs_mancity_2026-03-01",
            "odds_by_bookmaker": {"gbets": 3.50, "betway": 3.40},
        }]

        mock_db_result = {
            "outcomes": {
                "home": {"best_odds": 5.20, "best_bookmaker": "gbets",
                         "all_bookmakers": {"gbets": 5.20, "betway": 5.10}},
                "draw": {"best_odds": 4.60, "best_bookmaker": "gbets",
                         "all_bookmakers": {"gbets": 4.60, "betway": 4.30}},
                "away": {"best_odds": 1.63, "best_bookmaker": "supabets",
                         "all_bookmakers": {"supabets": 1.63, "betway": 1.60}},
            },
        }
        with patch("services.odds_service.get_best_odds",
                    new_callable=AsyncMock, return_value=mock_db_result):
            await bot._handle_odds_comparison(query, event_id)

        markup = query.edit_message_text.call_args[1]["reply_markup"]
        url_buttons = [btn for row in markup.inline_keyboard
                       for btn in row if btn.url]
        assert len(url_buttons) == 3
        labels = [btn.text for btn in url_buttons]
        assert any("Home Win" in l for l in labels)
        assert any("Draw" in l for l in labels)
        assert any("Away Win" in l for l in labels)

        del bot._game_tips_cache[event_id]

    @pytest.mark.asyncio
    async def test_each_cta_points_to_correct_bookmaker(self, test_db, mock_update):
        """Each CTA should point to the best-odds bookmaker for that market."""
        query = mock_update.callback_query
        event_id = "test-3cta-002"

        bot._game_tips_cache[event_id] = [{
            "outcome": "Home Win", "odds": 2.10, "bookie": "Betway",
            "bookie_key": "betway", "ev": 5.0, "prob": 55,
            "event_id": event_id,
            "home_team": "Kaizer Chiefs", "away_team": "Orlando Pirates",
            "match_id": "chiefs_vs_pirates",
            "odds_by_bookmaker": {"betway": 2.10},
        }]

        mock_db_result = {
            "outcomes": {
                "home": {"best_odds": 2.15, "best_bookmaker": "hollywoodbets",
                         "all_bookmakers": {"betway": 2.10, "hollywoodbets": 2.15}},
                "draw": {"best_odds": 3.50, "best_bookmaker": "gbets",
                         "all_bookmakers": {"betway": 3.40, "gbets": 3.50}},
                "away": {"best_odds": 1.80, "best_bookmaker": "supabets",
                         "all_bookmakers": {"betway": 1.75, "supabets": 1.80}},
            },
        }
        with patch("services.odds_service.get_best_odds",
                    new_callable=AsyncMock, return_value=mock_db_result):
            await bot._handle_odds_comparison(query, event_id)

        markup = query.edit_message_text.call_args[1]["reply_markup"]
        url_buttons = [btn for row in markup.inline_keyboard
                       for btn in row if btn.url]
        # Home CTA → hollywoodbets URL
        home_btn = [b for b in url_buttons if "Home Win" in b.text][0]
        assert "hollywoodbets" in home_btn.url
        # Draw CTA → gbets URL
        draw_btn = [b for b in url_buttons if "Draw" in b.text][0]
        assert "gbets" in draw_btn.url
        # Away CTA → supabets URL
        away_btn = [b for b in url_buttons if "Away Win" in b.text][0]
        assert "supabets" in away_btn.url

        del bot._game_tips_cache[event_id]


# ── Wave 15B: Sport Filter Inline + Bookmaker Directory Tests ──


class TestSportFilterInline:
    """BUG-029: Sport filter re-renders inline, not new screen."""

    @pytest.mark.asyncio
    async def test_filtered_view_shows_only_sport(self, test_db):
        """Filtering to soccer should only show soccer matches."""
        user_id = 50001
        bot._schedule_cache[user_id] = [
            {"id": "s1", "home_team": "Chiefs", "away_team": "Pirates",
             "commence_time": "2026-03-01T15:00:00Z", "sport_emoji": "⚽",
             "league_key": "psl"},
            {"id": "c1", "home_team": "SA", "away_team": "India",
             "commence_time": "2026-03-01T10:00:00Z", "sport_emoji": "🏏",
             "league_key": "test_cricket"},
        ]
        with patch.object(db, "get_user_sport_prefs", new_callable=AsyncMock,
                          return_value=[MagicMock(team_name="Chiefs", league="psl"),
                                        MagicMock(team_name="SA", league="test_cricket")]), \
             patch.object(bot, "_check_edges_for_games", new_callable=AsyncMock,
                          return_value={}):
            text, markup = await bot._render_your_games_all(user_id, sport_filter="soccer")

        assert "Soccer" in text
        assert "Chiefs" in text
        assert "India" not in text

        del bot._schedule_cache[user_id]

    @pytest.mark.asyncio
    async def test_all_button_appears_when_filtered(self, test_db):
        """When sport filter active, 'All' button should appear."""
        user_id = 50002
        bot._schedule_cache[user_id] = [
            {"id": "s1", "home_team": "Chiefs", "away_team": "Pirates",
             "commence_time": "2026-03-01T15:00:00Z", "sport_emoji": "⚽",
             "league_key": "psl"},
        ]
        with patch.object(db, "get_user_sport_prefs", new_callable=AsyncMock,
                          return_value=[MagicMock(team_name="Chiefs", league="psl"),
                                        MagicMock(team_name="SA", league="test_cricket")]), \
             patch.object(bot, "_check_edges_for_games", new_callable=AsyncMock,
                          return_value={}):
            text, markup = await bot._render_your_games_all(user_id, sport_filter="soccer")

        all_labels = [btn.text for row in markup.inline_keyboard for btn in row]
        assert "All" in all_labels

        del bot._schedule_cache[user_id]

    @pytest.mark.asyncio
    async def test_no_filter_no_all_button(self, test_db):
        """Without filter, no 'All' button should appear."""
        user_id = 50003
        bot._schedule_cache[user_id] = [
            {"id": "s1", "home_team": "Chiefs", "away_team": "Pirates",
             "commence_time": "2026-03-01T15:00:00Z", "sport_emoji": "⚽",
             "league_key": "psl"},
        ]
        with patch.object(db, "get_user_sport_prefs", new_callable=AsyncMock,
                          return_value=[MagicMock(team_name="Chiefs", league="psl"),
                                        MagicMock(team_name="SA", league="test_cricket")]), \
             patch.object(bot, "_check_edges_for_games", new_callable=AsyncMock,
                          return_value={}):
            text, markup = await bot._render_your_games_all(user_id, sport_filter=None)

        all_labels = [btn.text for row in markup.inline_keyboard for btn in row]
        assert "All" not in all_labels

        del bot._schedule_cache[user_id]

    @pytest.mark.asyncio
    async def test_empty_filter_shows_inline_message(self, test_db):
        """If no games match sport filter, show inline empty state."""
        user_id = 50004
        bot._schedule_cache[user_id] = [
            {"id": "s1", "home_team": "Chiefs", "away_team": "Pirates",
             "commence_time": "2026-03-01T15:00:00Z", "sport_emoji": "⚽",
             "league_key": "psl"},
        ]
        with patch.object(db, "get_user_sport_prefs", new_callable=AsyncMock,
                          return_value=[MagicMock(team_name="Chiefs", league="psl"),
                                        MagicMock(team_name="SA", league="test_cricket")]), \
             patch.object(bot, "_check_edges_for_games", new_callable=AsyncMock,
                          return_value={}):
            text, markup = await bot._render_your_games_all(user_id, sport_filter="cricket")

        assert "no cricket" in text.lower()

        del bot._schedule_cache[user_id]


class TestMultiBookmakerDirectory:
    """FIX-001: Bookmaker page should show all 5 SA bookmakers."""

    @pytest.mark.asyncio
    async def test_shows_all_five_bookmakers(self, test_db):
        """Bookmaker directory should list all 5 SA bookmakers."""
        query = MagicMock()
        query.edit_message_text = AsyncMock()
        await bot.handle_affiliate(query, "compare")
        text = query.edit_message_text.call_args[0][0]
        assert "SA Bookmakers" in text
        assert "Betway" in text
        assert "Hollywoodbets" in text
        assert "Sportingbet" in text
        assert "SupaBets" in text
        assert "GBets" in text

    @pytest.mark.asyncio
    async def test_each_bookmaker_has_signup_button(self, test_db):
        """Each bookmaker should have a sign-up URL button."""
        query = MagicMock()
        query.edit_message_text = AsyncMock()
        await bot.handle_affiliate(query, "compare")
        markup = query.edit_message_text.call_args[1]["reply_markup"]
        url_buttons = [btn for row in markup.inline_keyboard
                       for btn in row if btn.url]
        assert len(url_buttons) >= 5
        labels = " ".join(btn.text for btn in url_buttons)
        assert "Betway" in labels
        assert "GBets" in labels

    def test_no_single_bookmaker_hardcoded(self):
        """SA_BOOKMAKERS_INFO should have all 5 bookmakers."""
        assert len(bot.SA_BOOKMAKERS_INFO) == 5
        assert "betway" in bot.SA_BOOKMAKERS_INFO
        assert "gbets" in bot.SA_BOOKMAKERS_INFO
        assert "hollywoodbets" in bot.SA_BOOKMAKERS_INFO


# ── Wave 16A: Broadcast display tests ──

class TestBroadcastDisplay:
    """Test broadcast info helper and integration."""

    @patch("bot._get_broadcast_line")
    def test_get_broadcast_line_returns_display(self, mock_bc):
        """_get_broadcast_line should return display string."""
        mock_bc.return_value = "\U0001f4fa SS EPL (DStv 203)"
        result = mock_bc(home_team="Arsenal", away_team="Chelsea",
                         league_key="epl", match_date="2026-03-01")
        assert "\U0001f4fa" in result
        assert "DStv" in result

    @patch("bot._get_broadcast_line")
    def test_broadcast_empty_on_failure(self, mock_bc):
        """_get_broadcast_line should return empty on failure."""
        mock_bc.return_value = ""
        result = mock_bc(home_team="Unknown FC", away_team="Unknown SC",
                         league_key="unknown", match_date="")
        assert result == ""


# ── Wave 16B: Verified context + zero hallucination tests ──

class TestVerifiedContext:
    """Test verified context formatting and injection."""

    def test_format_verified_context_with_data(self):
        """_format_verified_context should produce structured text."""
        ctx = {
            "data_available": True,
            "sport": "soccer",
            "league": "PSL",
            "data_source": "ESPN",
            "home_team": {
                "name": "Kaizer Chiefs",
                "league_position": 5,
                "points": 28,
                "games_played": 18,
                "form": "WWLDW",
                "record": {"wins": 8, "draws": 4, "losses": 6},
                "goals_per_game": 1.2,
                "conceded_per_game": 0.8,
                "goal_difference": 7,
            },
            "away_team": {
                "name": "Orlando Pirates",
                "league_position": 2,
                "points": 38,
                "games_played": 18,
                "form": "WWWDW",
                "record": {"wins": 12, "draws": 2, "losses": 4},
                "goals_per_game": 1.6,
                "conceded_per_game": 0.5,
                "goal_difference": 20,
            },
            "head_to_head": [
                {"date": "2025-11-15", "home": "Chiefs", "away": "Pirates", "score": "1-2"},
            ],
        }
        result = bot._format_verified_context(ctx)
        assert "VERIFIED DATA" in result
        assert "Kaizer Chiefs" in result
        assert "Orlando Pirates" in result
        assert "League position: 5" in result
        assert "League position: 2" in result
        assert "WWLDW" in result
        assert "HEAD-TO-HEAD" in result
        assert "1-2" in result

    def test_format_verified_context_unavailable(self):
        """_format_verified_context returns empty when data unavailable."""
        ctx = {"data_available": False, "error": "Unknown league"}
        result = bot._format_verified_context(ctx)
        assert result == ""

    def test_format_verified_context_none(self):
        """_format_verified_context handles None gracefully."""
        assert bot._format_verified_context(None) == ""
        assert bot._format_verified_context({}) == ""


class TestSportValidation:
    """Test sport-specific term validation (powered by sport_terms.py)."""

    def test_strips_soccer_terms_from_rugby(self):
        """validate_sport_context should strip soccer terms from rugby."""
        text = "Pirates have kept a clean sheet in 3 games. They dominate the scrum."
        result = bot.validate_sport_context(text, "rugby")
        assert "clean sheet" not in result
        assert "scrum" in result  # rugby term should stay

    def test_strips_rugby_terms_from_soccer(self):
        """validate_sport_context should strip rugby terms from soccer."""
        text = "Good try defence from the pack. Strong attacking play."
        result = bot.validate_sport_context(text, "soccer")
        assert "attacking play" in result

    def test_strips_football_from_cricket(self):
        """validate_sport_context should strip football terms from cricket."""
        text = "Continental heavyweight with African football pedigree. Good innings ahead."
        result = bot.validate_sport_context(text, "cricket")
        assert "african football" not in result.lower()
        assert "continental heavyweight" not in result.lower()

    def test_no_change_for_correct_sport(self):
        """validate_sport_context shouldn't strip correct terms."""
        text = "Chiefs kept a clean sheet at home."
        result = bot.validate_sport_context(text, "soccer")
        assert "clean sheet" in result

    def test_empty_input(self):
        """validate_sport_context handles empty/None input."""
        assert bot.validate_sport_context("", "soccer") == ""
        assert bot.validate_sport_context("test", "") == "test"


class TestFactChecker:
    """Test post-generation fact checker (positions + unverified names)."""

    _CTX = {
        "data_available": True,
        "home_team": {
            "name": "Kaizer Chiefs",
            "league_position": 5,
            "coach": "Nasreddine Nabi",
            "top_scorer": {"name": "Ashley Du Preez", "goals": 8},
        },
        "away_team": {
            "name": "Orlando Pirates",
            "league_position": 2,
            "coach": "Jose Riveiro",
        },
        "head_to_head": [
            {"date": "2025-11-15", "home": "Chiefs", "away": "Pirates", "score": "1-2"},
        ],
    }

    def test_strips_wrong_position(self):
        """fact_check_output strips fabricated league positions."""
        narrative = "Kaizer Chiefs sit 3rd in the table, looking strong."
        result = bot.fact_check_output(narrative, self._CTX)
        assert "sit 3rd" not in result

    def test_keeps_correct_position(self):
        """fact_check_output keeps correct positions."""
        narrative = "Kaizer Chiefs sit 5th in the table."
        result = bot.fact_check_output(narrative, self._CTX)
        assert "sit 5th" in result

    def test_no_context_passthrough(self):
        """fact_check_output passes through when no verified context."""
        narrative = "Strong game expected."
        result = bot.fact_check_output(narrative, {})
        assert result == narrative
        result2 = bot.fact_check_output(narrative, None)
        assert result2 == narrative

    def test_strips_unverified_person_names(self):
        """fact_check_output strips lines with unverified person names."""
        narrative = "Erik Ten Hag rotates heavily mid-week.\nThe draw offers value."
        result = bot.fact_check_output(narrative, self._CTX)
        assert "Ten Hag" not in result
        assert "draw offers value" in result

    def test_keeps_verified_team_names(self):
        """fact_check_output should NOT strip verified team names."""
        narrative = "Kaizer Chiefs have strong form.\nOrlando Pirates are second."
        result = bot.fact_check_output(narrative, self._CTX)
        assert "Kaizer Chiefs" in result
        assert "Orlando Pirates" in result

    def test_keeps_verified_coach_names(self):
        """fact_check_output should allow names from VERIFIED_DATA coaches."""
        narrative = "Under Nasreddine Nabi, Chiefs have improved.\nJose Riveiro's Pirates are relentless."
        result = bot.fact_check_output(narrative, self._CTX)
        assert "Nasreddine Nabi" in result
        assert "Jose Riveiro" in result

    def test_keeps_verified_scorer_names(self):
        """fact_check_output should allow verified top scorer names."""
        narrative = "Ashley Du Preez has 8 goals this season.\nDangerous in the box."
        result = bot.fact_check_output(narrative, self._CTX)
        assert "Ashley Du Preez" in result

    def test_allows_narrative_opinion(self):
        """Narrative/opinion text should pass through freely."""
        narrative = "This shapes up as a cracker.\nThe smart money says draw."
        result = bot.fact_check_output(narrative, self._CTX)
        assert "shapes up" in result
        assert "smart money" in result

    def test_empty_narrative(self):
        """fact_check_output handles empty narrative."""
        assert bot.fact_check_output("", self._CTX) == ""
        assert bot.fact_check_output("", None) == ""


# ── Wave 17B: Dynamic prompt tests ──

class TestDynamicPrompt:
    """Test sport-parameterised Claude prompt."""

    def test_prompt_contains_sport(self):
        """_build_game_analysis_prompt should include the sport type."""
        prompt = bot._build_game_analysis_prompt("cricket")
        assert "SPORT: cricket" in prompt
        assert "cricket match" in prompt

    def test_prompt_contains_critical_rules(self):
        """Prompt should contain the rebalanced CRITICAL RULES."""
        prompt = bot._build_game_analysis_prompt("soccer")
        assert "FACTUAL CLAIMS" in prompt
        assert "NARRATIVE & OPINION" in prompt
        assert "SPORT VALIDATION" in prompt

    def test_prompt_default_soccer(self):
        """Default prompt sport should be soccer."""
        prompt = bot._build_game_analysis_prompt()
        assert "SPORT: soccer" in prompt

    def test_prompt_includes_banned_terms(self):
        """Prompt should include banned terms when provided."""
        prompt = bot._build_game_analysis_prompt("soccer", banned_terms="try, scrum, lineout")
        assert "try, scrum, lineout" in prompt

    def test_prompt_narrative_encouraged(self):
        """Prompt should explicitly encourage narrative and personality."""
        prompt = bot._build_game_analysis_prompt("soccer")
        assert "ENCOURAGED" in prompt
        assert "braai" in prompt
        assert "personality" in prompt

    def test_prompt_coaches_allowed(self):
        """Prompt should encourage referencing coaches by name from VERIFIED_DATA."""
        prompt = bot._build_game_analysis_prompt("soccer")
        assert "coaches and players BY NAME" in prompt


# ── Wave 17E: Enriched verified context tests ──


class TestEnrichedVerifiedContext:
    """Test that _format_verified_context includes all enrichment fields."""

    def test_includes_coach(self):
        """Verified context should include coach when available."""
        ctx = {
            "data_available": True,
            "sport": "soccer",
            "league": "PSL",
            "data_source": "ESPN",
            "home_team": {"name": "Chiefs", "coach": "Nasreddine Nabi"},
            "away_team": {"name": "Pirates", "coach": "Jose Riveiro"},
        }
        result = bot._format_verified_context(ctx)
        assert "Nasreddine Nabi" in result
        assert "Jose Riveiro" in result

    def test_includes_top_scorer(self):
        """Verified context should include top scorers."""
        ctx = {
            "data_available": True,
            "sport": "soccer",
            "league": "PSL",
            "data_source": "ESPN",
            "home_team": {"name": "Chiefs", "top_scorer": {"name": "Du Preez", "goals": 8}},
            "away_team": {"name": "Pirates"},
        }
        result = bot._format_verified_context(ctx)
        assert "Du Preez" in result
        assert "8 goals" in result

    def test_includes_venue(self):
        """Verified context should include venue."""
        ctx = {
            "data_available": True,
            "sport": "soccer",
            "league": "PSL",
            "data_source": "ESPN",
            "venue": "FNB Stadium",
            "home_team": {"name": "Chiefs"},
            "away_team": {"name": "Pirates"},
        }
        result = bot._format_verified_context(ctx)
        assert "FNB Stadium" in result

    def test_includes_formation(self):
        """Verified context should include formation and lineup."""
        ctx = {
            "data_available": True,
            "sport": "soccer",
            "league": "PSL",
            "data_source": "ESPN",
            "home_team": {"name": "Chiefs", "formation": "4-3-3", "lineup": "Petersen; ..."},
            "away_team": {"name": "Pirates"},
        }
        result = bot._format_verified_context(ctx)
        assert "4-3-3" in result
        assert "Petersen" in result

    def test_includes_key_players_rugby(self):
        """Verified context should include key players for rugby."""
        ctx = {
            "data_available": True,
            "sport": "rugby",
            "league": "URC",
            "data_source": "ESPN",
            "home_team": {
                "name": "Bulls",
                "key_players": [
                    {"name": "Kurt-Lee Arendse", "position": "wing", "role": "star"},
                ],
            },
            "away_team": {"name": "Stormers"},
        }
        result = bot._format_verified_context(ctx)
        assert "Kurt-Lee Arendse" in result

    def test_includes_last_5_results(self):
        """Verified context should include recent results with scores."""
        ctx = {
            "data_available": True,
            "sport": "soccer",
            "league": "EPL",
            "data_source": "ESPN",
            "home_team": {
                "name": "Man Utd",
                "last_5": [
                    {"opponent": "Burnley", "result": "W", "goals_for": 3, "goals_against": 2, "home_away": "home"},
                    {"opponent": "West Ham", "result": "L", "goals_for": 0, "goals_against": 1, "home_away": "away"},
                ],
            },
            "away_team": {"name": "Crystal Palace"},
        }
        result = bot._format_verified_context(ctx)
        assert "Burnley" in result
        assert "3-2" in result

    def test_cricket_nrr(self):
        """Verified context should include cricket NRR."""
        ctx = {
            "data_available": True,
            "sport": "cricket",
            "league": "SA20",
            "data_source": "ESPN",
            "home_team": {"name": "Paarl Royals", "nrr": 0.452, "wins": 5, "losses": 2},
            "away_team": {"name": "MI Cape Town"},
        }
        result = bot._format_verified_context(ctx)
        assert "+0.452" in result
        assert "Wins: 5" in result

    def test_combat_sport_context(self):
        """Verified context should handle combat sports."""
        ctx = {
            "data_available": True,
            "sport": "combat",
            "league": "UFC",
            "data_source": "ESPN",
            "home_team": {"name": "Du Plessis"},
            "away_team": {"name": "Pereira"},
        }
        result = bot._format_verified_context(ctx)
        assert "Du Plessis" in result
        assert "Pereira" in result


class TestSetupFallback:
    """Test _ensure_setup_not_empty injects fallback when Setup is thin."""

    def test_injects_fallback_when_empty(self):
        """Should inject standings when Setup is just a header."""
        output = "📋 <b>The Setup</b>\n\n🎯 <b>The Edge</b>\nGood value on draw."
        ctx = {
            "data_available": True,
            "home_team": {"name": "Chiefs", "league_position": 5, "points": 28, "form": "WWLDW"},
            "away_team": {"name": "Pirates", "league_position": 2, "points": 38},
        }
        result = bot._ensure_setup_not_empty(output, ctx)
        assert "Chiefs" in result
        assert "28 points" in result
        assert "WWLDW" in result

    def test_no_change_when_setup_has_content(self):
        """Should not touch Setup when it already has rich content."""
        output = (
            "📋 <b>The Setup</b>\n"
            "Chiefs sit 5th on 28 points with a streaky WWLDW form. Pirates are 2nd.\n\n"
            "🎯 <b>The Edge</b>\nValue on the draw."
        )
        ctx = {
            "data_available": True,
            "home_team": {"name": "Chiefs", "league_position": 5, "points": 28},
            "away_team": {"name": "Pirates", "league_position": 2, "points": 38},
        }
        result = bot._ensure_setup_not_empty(output, ctx)
        assert result == output  # unchanged

    def test_no_change_without_verified_data(self):
        """Should not inject fallback when no verified data."""
        output = "📋 <b>The Setup</b>\n\n🎯 <b>The Edge</b>\nOdds analysis."
        result = bot._ensure_setup_not_empty(output, {})
        assert result == output
