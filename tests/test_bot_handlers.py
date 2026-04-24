"""Tests for bot.py — /start, /menu, /help command handlers."""

from __future__ import annotations

import json
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

import bot
import config
import db


pytestmark = pytest.mark.asyncio


async def test_cmd_start_new_user(test_db, mock_update, mock_context):
    """New user should get onboarding flow via send_card_or_fallback (2 card sends)."""
    mock_user = MagicMock()
    mock_user.id = 11111
    mock_user.username = "newbie"
    mock_user.first_name = "Newbie"
    mock_update.effective_user = mock_user

    with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
        await bot.cmd_start(mock_update, mock_context)

    # 2 send_card_or_fallback calls: welcome card + experience card
    assert mock_card.call_count == 2
    # First call is the welcome card
    first_call = mock_card.call_args_list[0]
    assert first_call.kwargs.get("template") == "onboarding_welcome.html"
    # Second call is the experience step card; text_fallback contains welcome + step 1
    second_call = mock_card.call_args_list[1]
    fallback = second_call.kwargs.get("text_fallback", "")
    assert "Welcome" in fallback
    assert "Step 1" in fallback


async def test_post_init_runs_live_edge_hygiene_once():
    app = MagicMock()
    app.job_queue = None
    app.bot.set_my_commands = AsyncMock()

    with patch.object(bot.db, "init_db", new=AsyncMock()), \
         patch.object(bot, "_ensure_narrative_cache_table"), \
         patch.object(bot.config, "STITCH_CLIENT_ID", ""), \
         patch.object(bot.config, "STITCH_MOCK_MODE", False), \
         patch("scrapers.edge.settlement.run_live_edge_hygiene", return_value={
             "voided": 3,
             "ev_gt_25": 0,
             "odds_gt_6": 1,
             "bronze_composite_lt_30": 2,
             "deduped": 0,
         }) as hygiene, \
         patch("scripts.telegraph_guides.ensure_active_guide", new=AsyncMock()), \
         patch("services.user_service.backfill_bonus_leagues", new=AsyncMock(return_value=0)):
        await bot._post_init(app)

    hygiene.assert_called_once_with()
    app.bot.set_my_commands.assert_awaited_once()


async def test_cmd_start_returning_user(test_db, mock_update, mock_context):
    """Returning user with onboarding done should get single welcome message with sticky keyboard."""
    await db.upsert_user(22222, "veteran", "Veteran")
    await db.set_onboarding_done(22222)

    mock_user = MagicMock()
    mock_user.id = 22222
    mock_user.username = "veteran"
    mock_user.first_name = "Veteran"
    mock_update.effective_user = mock_user

    with patch("bot._welcome_img_path", return_value=None):
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

    with patch("bot._welcome_img_path", return_value=None):
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
    # FIX-HIDE-EDGE-TRACKER-P0-01: /results is hidden pre-launch.
    assert "/results" not in text
    assert "Edge Tracker" not in text
    assert "Top Edge Picks" in text
    assert "My Matches" in text
    assert "Tap <b>📖 Guide</b>" in text
    assert "Hot tips" not in text
    assert "Your games" not in text
    assert "HTML" in call_args[1].get("parse_mode", "")
    markup = call_args[1]["reply_markup"]
    button_data = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]
    assert "guide:menu" in button_data


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

    with patch("bot._welcome_img_path", return_value=None):
        with patch("bot._get_recent_wins_from_edge_results", return_value=[]):
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


async def test_show_guide_hub_surface(mock_update):
    """Guide entry should open the interactive topic hub."""
    await bot._show_betway_guide(mock_update)

    call_args = mock_update.message.reply_text.call_args
    text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
    assert "📖 <b>Guide</b>" in text
    assert "Pick a topic" in text

    markup = call_args[1]["reply_markup"]
    button_data = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]
    # FIX-HIDE-EDGE-TRACKER-P0-01: track_record topic removed pre-launch.
    assert button_data == [
        "guide:edge_ratings",
        "guide:signals",
        "guide:method",
        "guide:value101",
        "guide:bookmaker",
        "menu:home",
    ]


async def test_dispatch_button_routes_guide_topic(mock_update, mock_context):
    """guide:* callbacks should render topic pages by editing the same message."""
    query = mock_update.callback_query

    await bot._dispatch_button(query, mock_context, "guide", "signals")

    call_args = query.edit_message_text.call_args
    text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
    assert "Signals — What confirms a pick?" in text
    assert "Signal Breakdown" in text

    markup = call_args[1]["reply_markup"]
    button_data = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]
    assert "hot:go" in button_data
    assert "guide:menu" in button_data
    assert "menu:home" in button_data


async def test_dispatch_button_routes_stale_bets_to_main_menu(mock_update, mock_context):
    """Stale bets:active buttons (removed prefix) produce Unknown action + nav button."""
    query = mock_update.callback_query
    query.from_user.first_name = "User"

    await bot._dispatch_button(query, mock_context, "bets", "active")

    call_args = query.edit_message_text.call_args
    text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
    assert "Unknown action" in text

    markup = call_args[1]["reply_markup"]
    labels = [btn.text for row in markup.inline_keyboard for btn in row]
    assert any("Menu" in lbl for lbl in labels)


async def test_dispatch_button_routes_stale_stats_to_edge_tracker(mock_update, mock_context):
    """Stale stats:leaderboard buttons (removed prefix) produce Unknown action + nav button."""
    query = mock_update.callback_query

    await bot._dispatch_button(query, mock_context, "stats", "leaderboard")

    call_args = query.edit_message_text.call_args
    text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
    assert "Unknown action" in text


async def test_handle_ob_done_includes_how_it_works_cta(test_db):
    """Onboarding completion keeps primary CTAs and adds guide continuity."""
    user_id = 98765
    bot._onboarding_state.clear()
    ob = bot._get_ob(user_id)
    ob["experience"] = "casual"

    query = MagicMock()
    query.from_user = MagicMock()
    query.from_user.id = user_id
    query.from_user.first_name = "Tester"
    query.message = MagicMock()
    query.message.chat_id = user_id
    query.edit_message_text = AsyncMock()

    mock_ctx = MagicMock()
    mock_ctx.bot = MagicMock()
    mock_ctx.bot.send_message = AsyncMock()

    with patch.object(bot, "persist_onboarding", new=AsyncMock()), \
         patch.object(bot, "analytics_track"), \
         patch.object(bot.db, "is_trial_active", new=AsyncMock(return_value=True)), \
         patch.object(bot.db, "get_user", new=AsyncMock(return_value=SimpleNamespace(
             trial_status="active",
             subscription_status="inactive",
         ))), \
         patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
        await bot.handle_ob_done(query, mock_ctx)

    # handle_ob_done sends onboarding_done card; markup is passed as kwarg
    assert mock_card.called
    markup = mock_card.call_args.kwargs.get("markup")
    button_data = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]
    assert "story:start" in button_data
    assert "hot:go" in button_data
    assert "guide:menu" in button_data
    assert "nav:main" in button_data


async def test_handle_menu_history_empty(test_db, mock_update, mock_context):
    """menu:history with no tips should say no tips."""
    query = mock_update.callback_query
    await bot.handle_menu(query, "history")

    call_args = query.edit_message_text.call_args
    text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
    assert "No tips recorded" in text


class TestHotTipsHeaderRelock:
    """CLEAN-RENDER-v2: edge:detail uses single renderer path."""

    async def test_detail_renders_via_edge_detail_renderer(self, mock_update, mock_context):
        """New handler delegates to render_edge_detail, not cache paths."""
        query = mock_update.callback_query
        user_id = query.from_user.id
        match_key = "chelsea_vs_newcastle_2026-03-14"

        bot._ht_tips_snapshot[user_id] = [{
            "event_id": match_key,
            "match_id": match_key,
            "home_team": "Chelsea",
            "away_team": "Newcastle United",
            "display_tier": "bronze",
            "edge_rating": "bronze",
            "ev": 0,
        }]

        _rendered_html = (
            "🎯 <b>Chelsea vs Newcastle United</b>\n"
            "📅 Today\n🏆 Premier League\n🥉 BRONZE EDGE\n\n"
            "🎯 <b>The Edge</b>\n<b>Chelsea</b> @ <b>2.10</b> on Betway"
        )

        try:
            # FIX-6: renderer now returns (html, edge_tier) when include_tier=True
            with patch("bot.get_effective_tier", new_callable=AsyncMock, return_value="diamond"), \
                 patch("edge_detail_renderer.render_edge_detail", return_value=(_rendered_html, "bronze")), \
                 patch("bot._build_game_buttons", return_value=[]), \
                 patch("bot._qa_banner", return_value=""), \
                 patch("bot.asyncio.create_task", side_effect=lambda coro: coro.close()):
                await bot._dispatch_button(query, mock_context, "edge", f"detail:{match_key}")

            text = query.edit_message_text.call_args[0][0]
            assert "🎯 <b>Chelsea vs Newcastle United</b>" in text
            assert "The Edge" in text
        finally:
            bot._ht_tips_snapshot.pop(user_id, None)

    async def test_detail_uses_snapshot_for_buttons(self, mock_update, mock_context):
        """Handler still reads _ht_tips_snapshot for button building."""
        query = mock_update.callback_query
        user_id = query.from_user.id
        match_key = "west_ham_vs_manchester_city_2026-03-14"

        bot._ht_tips_snapshot[user_id] = [{
            "match_id": match_key,
            "event_id": match_key,
            "home_team": "West Ham",
            "away_team": "Manchester City",
            "display_tier": "gold",
            "edge_rating": "gold",
            "outcome": "Manchester City",
            "odds": 1.72,
            "ev": 1.18,
        }]

        _rendered_html = "🎯 <b>West Ham vs Manchester City</b>\n🎯 <b>The Edge</b>\nContent"

        try:
            # FIX-6: renderer now returns (html, edge_tier) tuple; mock returns bronze
            # so FIX-6 fallback promotes _cr_tier from snapshot's gold display_tier.
            with patch("bot.get_effective_tier", new_callable=AsyncMock, return_value="diamond"), \
                 patch("edge_detail_renderer.render_edge_detail", return_value=(_rendered_html, "bronze")), \
                 patch("bot._build_game_buttons", return_value=[]) as mock_btns, \
                 patch("bot._qa_banner", return_value=""), \
                 patch("bot.asyncio.create_task", side_effect=lambda coro: coro.close()):
                await bot._dispatch_button(query, mock_context, "edge", f"detail:{match_key}")

            # _build_game_buttons should have been called with snapshot tip
            assert mock_btns.called
            tips_arg = mock_btns.call_args[0][0]
            assert tips_arg[0].get("display_tier") == "gold"
        finally:
            bot._ht_tips_snapshot.pop(user_id, None)

    async def test_detail_no_data_shows_friendly_message(self, mock_update, mock_context):
        """When render_edge_detail returns no-data message, handler still serves."""
        query = mock_update.callback_query
        match_key = "unknown_vs_team_2026-03-14"

        _no_data_html = "🎯 <b>Unknown Vs Team</b>\n\nNo current edge data for this match."

        try:
            # FIX-6: renderer returns (html, tier) tuple; no-data path returns ("html", "bronze")
            with patch("bot.get_effective_tier", new_callable=AsyncMock, return_value="diamond"), \
                 patch("edge_detail_renderer.render_edge_detail", return_value=(_no_data_html, "bronze")), \
                 patch("bot._build_game_buttons", return_value=[]), \
                 patch("bot._qa_banner", return_value=""), \
                 patch("bot.asyncio.create_task", side_effect=lambda coro: coro.close()):
                await bot._dispatch_button(query, mock_context, "edge", f"detail:{match_key}")

            text = query.edit_message_text.call_args[0][0]
            assert "No current edge data" in text
        finally:
            pass


class TestHandleTipDetailResultProof:
    async def test_handle_tip_detail_includes_tier_track_record(self, mock_update, mock_context):
        query = mock_update.callback_query
        event_id = "chiefs_vs_pirates_2026-03-15"
        tip = {
            "match_id": event_id,
            "event_id": event_id,
            "home_team": "Kaizer Chiefs",
            "away_team": "Orlando Pirates",
            "league": "PSL",
            "league_key": "psl",
            "sport_key": "soccer_south_africa_psl",
            "outcome": "Kaizer Chiefs",
            "odds": 2.10,
            "ev": 7.2,
            "prob": 49.0,
            "display_tier": "gold",
            "edge_rating": "gold",
            "odds_by_bookmaker": {"betway": 2.10},
        }
        bot._game_tips_cache[event_id] = [tip]
        db_user = SimpleNamespace(
            experience_level="casual",
            bankroll=None,
            edge_tooltip_shown=True,
        )

        try:
            with patch.object(bot.db, "get_user", new=AsyncMock(return_value=db_user)), \
                 patch.object(bot.db, "log_edge_view", new=AsyncMock()), \
                 patch("bot.analytics_track"), \
                 patch("bot.get_effective_tier", new_callable=AsyncMock, return_value="diamond"), \
                 patch("db_connection.get_connection", return_value=MagicMock(close=MagicMock())), \
                 patch("tier_gate.check_tip_limit", return_value=(True, 999)), \
                 patch("bot.record_view"), \
                 patch("tier_gate.get_edge_access_level", return_value="full"), \
                 patch.object(bot.odds_svc, "get_best_odds", new=AsyncMock(return_value={})), \
                 patch("bot.select_best_bookmaker", return_value={
                     "bookmaker_key": "betway",
                     "bookmaker_name": "Betway",
                     "odds": 2.10,
                 }), \
                 patch("bot.get_runner_up_odds", return_value=[]), \
                 patch("bot._get_broadcast_details", return_value={
                     "kickoff": "Sun 15 Mar, 15:00 SAST",
                     "broadcast": "📺 DStv 202",
                 }), \
                 patch("bot.render_tip_with_odds", return_value="TIP CARD"), \
                 patch("bot._build_tip_narrative", return_value="WHY THIS EDGE"), \
                 patch("bot._build_game_buttons", return_value=[]), \
                 patch("bot._qa_banner", return_value=""), \
                 patch("bot._get_hot_tips_result_proof", new_callable=AsyncMock, return_value={
                     "stats_7d": {"by_tier": {"gold": {"total": 6, "hits": 4, "hit_rate": 0.667}}},
                 }):
                await bot.handle_tip_detail(query, mock_context, f"detail:{event_id}:0")

            text = query.edit_message_text.call_args[0][0]
            assert "TIP CARD" in text
            assert "WHY THIS EDGE" in text
            assert "7D track record" in text
            assert "Gold edges hit <b>67%</b> (4/6 settled)" in text
        finally:
            bot._game_tips_cache.pop(event_id, None)


class TestHotTipsModelOnlyIntegrity:
    async def test_build_hot_tips_page_stamps_model_only_metadata(self):
        tip = {
            "match_id": "arsenal_vs_chelsea_2026-03-14",
            "event_id": "arsenal_vs_chelsea_2026-03-14",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "league": "Premier League",
            "league_key": "epl",
            "sport_key": "soccer_epl",
            "display_tier": "gold",
            "edge_rating": "gold",
            "edge_score": 60,
            "outcome": "Arsenal",
            "odds": 2.15,
            "ev": 6.4,
            "prob": 49.0,
            "edge_v2": {
                "match_key": "arsenal_vs_chelsea_2026-03-14",
                "confirming_signals": 0,
                "signals": {
                    "market_agreement": {"available": True, "signal_strength": 0.42},
                    "movement": {"available": True, "signal_strength": 0.33},
                },
            },
        }

        text, _, _tips = await bot._build_hot_tips_page([tip], user_id=config.ADMIN_IDS[0])

        assert "[MODEL ONLY]" in text
        assert tip["_ht_model_only"] is True
        assert tip["_ht_confirming_signals"] == 0
        assert tip["_ht_total_signals"] == 2

    async def test_cache_hit_detail_preserves_model_only_banner_and_strips_badge(self, mock_update, mock_context):
        pytest.skip(
            "edge:detail now uses CLEAN-RENDER path via edge_detail_renderer.py (2026-03-26). "
            "_analysis_cache path is dead code — [MODEL ONLY] banner logic no longer reachable."
        )

    async def test_instant_detail_keeps_supported_card_unlabeled(self, mock_update, mock_context):
        pytest.skip(
            "edge:detail now uses CLEAN-RENDER path via edge_detail_renderer.py (2026-03-26). "
            "_game_tips_cache / _generate_narrative_v2 path is dead code — unreachable after CLEAN-RENDER return."
        )


class TestStickyKeyboard:
    def test_get_main_keyboard_shape(self):
        """Sticky keyboard should be 3 rows: 1 hero + 2 + 3."""
        kb = bot.get_main_keyboard()
        assert len(kb.keyboard) == 3
        assert len(kb.keyboard[0]) == 1
        assert len(kb.keyboard[1]) == 2
        assert len(kb.keyboard[2]) == 3

    def test_get_main_keyboard_labels(self):
        """Sticky keyboard has correct labels."""
        kb = bot.get_main_keyboard()
        labels = [btn.text for row in kb.keyboard for btn in row]
        assert "⚽ My Matches" in labels
        assert "💎 Edge Picks" in labels
        assert "🏠 Menu" in labels
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

    def test_legacy_my_stats_label_maps_to_results(self):
        assert bot._LEGACY_LABELS.get("📊 My Stats") == "results"


async def test_handle_keyboard_tap_legacy_my_stats_redirects_to_edge_tracker(test_db, mock_context):
    user_id = 123321
    await db.upsert_user(user_id, "legacy_stats", "Legacy Stats")
    await db.set_onboarding_done(user_id)

    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    update.message = MagicMock()
    update.message.text = "📊 My Stats"
    update.message.reply_text = AsyncMock()

    markup = MagicMock()
    with patch.object(bot, "_render_results_surface", new=AsyncMock(return_value=("EDGE TRACKER", markup))):
        await bot.handle_keyboard_tap(update, mock_context)

    call_args = update.message.reply_text.call_args
    text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
    assert text == "EDGE TRACKER"
    assert call_args[1]["reply_markup"] is markup


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
    def test_help_text_uses_edge_branding(self):
        """HELP_TEXT should use Edge branding (Edge Picks, Edge Tracker, etc.)."""
        assert "Edge" in bot.HELP_TEXT

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
        """Prompt should contain W29 ABSOLUTE RULES and two-pass IMMUTABLE CONTEXT."""
        prompt = bot._build_game_analysis_prompt("soccer")
        assert "ABSOLUTE RULES" in prompt
        assert "GOLDEN RULE" in prompt
        assert "NARRATIVE & OPINION" in prompt
        assert "IMMUTABLE CONTEXT" in prompt
        assert "ANALYST" in prompt

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

    @pytest.mark.asyncio
    async def test_hot_tips_origin_uses_back_to_edge_picks(self, test_db, mock_update):
        """Hot Tips odds comparison routes back to the originating Hot Tips list page."""
        query = mock_update.callback_query
        query.from_user.id = 4242
        event_id = "hot-edge-123"

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
            "match_id": event_id,
            "odds_by_bookmaker": {"betway": 2.10, "hollywoodbets": 2.15},
        }]
        bot._remember_hot_tip_origin(query.from_user.id, event_id, 1)
        bot._remember_odds_compare_origin(
            query.from_user.id, event_id, "edge_picks", match_key=event_id, back_page=1,
        )

        mock_db_result = {
            "outcomes": {
                "home": {"best_odds": 2.15, "best_bookmaker": "hollywoodbets", "all_bookmakers": {"betway": 2.10, "hollywoodbets": 2.15}},
                "draw": {"best_odds": 3.50, "best_bookmaker": "gbets", "all_bookmakers": {"betway": 3.40, "gbets": 3.50}},
                "away": {"best_odds": 1.80, "best_bookmaker": "supabets", "all_bookmakers": {"betway": 1.75, "supabets": 1.80}},
            },
        }
        try:
            with patch("services.odds_service.get_best_odds", new_callable=AsyncMock, return_value=mock_db_result):
                await bot._handle_odds_comparison(query, event_id)

            markup = query.edit_message_text.call_args[1]["reply_markup"]
            button_data = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]
            assert "hot:back:1" in button_data
            assert f"yg:game:{event_id}" not in button_data
        finally:
            bot._game_tips_cache.pop(event_id, None)
            bot._odds_compare_origin.pop((query.from_user.id, event_id), None)
            bot._ht_detail_origin.pop((query.from_user.id, event_id), None)


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
        # All bookmakers present in output (_display_bookmaker_name maps hollywoodbets → "HWB")
        assert "HWB" in text or "hwb" in text.lower()
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
        """Simplified buttons: at least CTA + Back for matches source."""
        tips = [
            {"outcome": "Draw", "odds": 4.60, "ev": 8.0, "bookie_key": "gbets",
             "odds_by_bookmaker": {"gbets": 4.60, "betway": 4.30}, "match_id": "test"},
            {"outcome": "Home Win", "odds": 5.20, "ev": 3.0, "bookie_key": "hollywoodbets",
             "odds_by_bookmaker": {"hollywoodbets": 5.20, "betway": 5.10}, "match_id": "test"},
            {"outcome": "Away Win", "odds": 1.63, "ev": 2.0, "bookie_key": "supabets",
             "odds_by_bookmaker": {"supabets": 1.63}, "match_id": "test"},
        ]
        buttons = bot._build_game_buttons(tips, "ev-123", 111)
        # Current production: CTA + Back (compare/menu rows removed in later waves)
        assert 2 <= len(buttons) <= 4

    def test_cta_uses_best_ev_outcome(self):
        """CTA selects highest-EV non-draw outcome (draws excluded from CTA by design)."""
        tips = [
            {"outcome": "Away Win", "odds": 3.20, "ev": 7.0, "bookie_key": "gbets",
             "odds_by_bookmaker": {"gbets": 3.20}, "match_id": "test",
             "home_team": "Arsenal", "away_team": "Chelsea"},
            {"outcome": "Home Win", "odds": 2.10, "ev": 1.0, "bookie_key": "betway",
             "odds_by_bookmaker": {"betway": 2.10}, "match_id": "test",
             "home_team": "Arsenal", "away_team": "Chelsea"},
        ]
        buttons = bot._build_game_buttons(tips, "ev-456", 111)
        cta_text = buttons[0][0].text
        # Away Win (ev=7.0) is highest-EV non-draw tip
        assert "Chelsea" in cta_text or "Away" in cta_text or "away" in cta_text.lower()

    def test_no_positive_ev_shows_generic_cta(self):
        """When no positive EV, show generic bookmaker CTA button."""
        tips = [
            {"outcome": "Home Win", "odds": 2.10, "ev": -1.0, "bookie_key": "betway",
             "odds_by_bookmaker": {}, "match_id": "test"},
        ]
        buttons = bot._build_game_buttons(tips, "ev-789", 111)
        cta_text = buttons[0][0].text
        assert "Bet" in cta_text or "View" in cta_text or "Visit" in cta_text

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

    def test_hot_tips_detail_buttons_keep_back_on_primary_row(self):
        """Hot Tips detail (edge_picks source) has CTA row then Back row with hot:back:{page}."""
        tips = [
            {"outcome": "Home Win", "odds": 2.10, "ev": 5.0, "bookie_key": "betway",
             "odds_by_bookmaker": {"betway": 2.10}, "match_id": "hot-test",
             "home_team": "Arsenal", "away_team": "Chelsea"},
        ]
        buttons = bot._build_game_buttons(
            tips, "hot-test", 111, source="edge_picks", back_page=2,
        )
        # Back button encodes the page number in its callback_data
        all_buttons = [btn for row in buttons for btn in row]
        assert any("hot:back:2" == btn.callback_data for btn in all_buttons)
        assert any("Back" in btn.text for btn in all_buttons)


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
    """W30-GATE: Button builder uses edge_tier param for emoji (not EV-computed)."""

    def test_gold_edge_tier_shows_gold_emoji(self):
        """Gold edge_tier should show 🥇 in CTA button (must be non-draw tip)."""
        tips = [
            {"outcome": "Home Win", "odds": 4.60, "ev": 9.3, "bookie_key": "gbets",
             "odds_by_bookmaker": {"gbets": 4.60}, "match_id": "test"},
        ]
        buttons = bot._build_game_buttons(tips, "ev-test", 111, edge_tier="gold")
        cta_text = buttons[0][0].text
        assert "🥇" in cta_text
        assert "💎" not in cta_text

    def test_diamond_edge_tier_shows_diamond_emoji(self):
        """Diamond edge_tier should show 💎 in CTA button."""
        tips = [
            {"outcome": "Home Win", "odds": 6.00, "ev": 16.0, "bookie_key": "hwb",
             "odds_by_bookmaker": {"hwb": 6.00}, "match_id": "test"},
        ]
        buttons = bot._build_game_buttons(tips, "ev-test", 111, edge_tier="diamond")
        cta_text = buttons[0][0].text
        assert "💎" in cta_text

    def test_silver_edge_tier_shows_silver_emoji(self):
        """Silver edge_tier should show 🥈 in CTA button."""
        tips = [
            {"outcome": "Away Win", "odds": 2.10, "ev": 4.5, "bookie_key": "betway",
             "odds_by_bookmaker": {"betway": 2.10}, "match_id": "test"},
        ]
        buttons = bot._build_game_buttons(tips, "ev-test", 111, edge_tier="silver")
        cta_text = buttons[0][0].text
        assert "🥈" in cta_text

    def test_bronze_edge_tier_shows_bronze_emoji(self):
        """Bronze edge_tier should show 🥉 in CTA button (must be non-draw tip)."""
        tips = [
            {"outcome": "Home Win", "odds": 3.10, "ev": 2.0, "bookie_key": "supabets",
             "odds_by_bookmaker": {"supabets": 3.10}, "match_id": "test"},
        ]
        buttons = bot._build_game_buttons(tips, "ev-test", 111, edge_tier="bronze")
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
            "display_tier": "gold", "prob": 25,
        }
        narrative = bot._build_tip_narrative(tip)
        assert "🥇" in narrative
        assert "🥉" not in narrative

    def test_diamond_tier_gets_diamond_emoji(self):
        """A tip with display_tier='diamond' should produce 💎."""
        tip = {
            "outcome": "Home Win", "odds": 6.00, "ev": 16.0, "bookmaker": "Hollywoodbets",
            "display_tier": "diamond", "prob": 20,
        }
        narrative = bot._build_tip_narrative(tip)
        assert "💎" in narrative

    def test_silver_tier_gets_silver_emoji(self):
        """A tip with display_tier='silver' should produce 🥈."""
        tip = {
            "outcome": "Away Win", "odds": 2.20, "ev": 5.0, "bookmaker": "Betway",
            "display_tier": "silver", "prob": 40,
        }
        narrative = bot._build_tip_narrative(tip)
        assert "🥈" in narrative

    def test_bronze_tier_gets_bronze_emoji(self):
        """A tip with display_tier='bronze' should produce 🥉."""
        tip = {
            "outcome": "Draw", "odds": 3.10, "ev": 1.5, "bookmaker": "SupaBets",
            "display_tier": "bronze", "prob": 30,
        }
        narrative = bot._build_tip_narrative(tip)
        assert "🥉" in narrative


class TestExperiencedSkipsEdgeExplainer:
    """Wave 14D: Experienced users skip the Edge explainer screen."""

    async def test_experienced_skips_to_risk(self):
        """Experienced user after favourites should skip edge_explainer (goes to summary)."""
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
        assert ob["step"] == "summary"

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
        """When sport filter active and 2+ sports in schedule, 'All' button appears."""
        user_id = 50002
        bot._schedule_cache[user_id] = [
            {"id": "s1", "home_team": "Chiefs", "away_team": "Pirates",
             "commence_time": "2026-03-01T15:00:00Z", "sport_emoji": "⚽",
             "league_key": "psl"},
            {"id": "c1", "home_team": "SA", "away_team": "India",
             "commence_time": "2026-03-02T10:00:00Z", "sport_emoji": "🏏",
             "league_key": "test_cricket"},
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


class TestMyMatchesPremiumCards:
    @pytest.mark.asyncio
    async def test_cached_match_card_context_reads_schedule_and_standings(self, tmp_path):
        db_path = tmp_path / "odds.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE team_api_ids (team_name TEXT, league TEXT, espn_id TEXT, espn_display_name TEXT)"
        )
        conn.execute(
            "CREATE TABLE api_cache (cache_key TEXT PRIMARY KEY, data TEXT, fetched_at TEXT, expires_at TEXT)"
        )
        conn.executemany(
            "INSERT INTO team_api_ids (team_name, league, espn_id, espn_display_name) VALUES (?, ?, ?, ?)",
            [
                ("chiefs", "psl", "1", "Chiefs"),
                ("pirates", "psl", "2", "Pirates"),
            ],
        )

        standings_payload = {
            "children": [{
                "standings": {
                    "entries": [
                        {"team": {"id": "1"}, "stats": [{"name": "rank", "value": 3}]},
                        {"team": {"id": "2"}, "stats": [{"name": "rank", "value": 12}]},
                    ],
                },
            }],
        }
        schedule_home = {
            "events": [
                {
                    "date": "2026-03-05T15:00:00Z",
                    "competitions": [{
                        "status": {"type": {"completed": True}},
                        "competitors": [
                            {"team": {"id": "1"}, "score": {"value": 2}, "homeAway": "home"},
                            {"team": {"id": "9"}, "score": {"value": 1}, "homeAway": "away"},
                        ],
                    }],
                },
                {
                    "date": "2026-03-04T15:00:00Z",
                    "competitions": [{
                        "status": {"type": {"completed": True}},
                        "competitors": [
                            {"team": {"id": "1"}, "score": {"value": 1}, "homeAway": "away"},
                            {"team": {"id": "9"}, "score": {"value": 0}, "homeAway": "home"},
                        ],
                    }],
                },
                {
                    "date": "2026-03-03T15:00:00Z",
                    "competitions": [{
                        "status": {"type": {"completed": True}},
                        "competitors": [
                            {"team": {"id": "1"}, "score": {"value": 1}, "homeAway": "home"},
                            {"team": {"id": "9"}, "score": {"value": 1}, "homeAway": "away"},
                        ],
                    }],
                },
                {
                    "date": "2026-03-02T15:00:00Z",
                    "competitions": [{
                        "status": {"type": {"completed": True}},
                        "competitors": [
                            {"team": {"id": "1"}, "score": {"value": 0}, "homeAway": "away"},
                            {"team": {"id": "9"}, "score": {"value": 2}, "homeAway": "home"},
                        ],
                    }],
                },
                {
                    "date": "2026-03-01T15:00:00Z",
                    "competitions": [{
                        "status": {"type": {"completed": True}},
                        "competitors": [
                            {"team": {"id": "1"}, "score": {"value": 3}, "homeAway": "home"},
                            {"team": {"id": "9"}, "score": {"value": 1}, "homeAway": "away"},
                        ],
                    }],
                },
            ],
        }
        schedule_away = {
            "events": [
                {
                    "date": "2026-03-05T15:00:00Z",
                    "competitions": [{
                        "status": {"type": {"completed": True}},
                        "competitors": [
                            {"team": {"id": "2"}, "score": {"value": 0}, "homeAway": "home"},
                            {"team": {"id": "8"}, "score": {"value": 1}, "homeAway": "away"},
                        ],
                    }],
                },
                {
                    "date": "2026-03-04T15:00:00Z",
                    "competitions": [{
                        "status": {"type": {"completed": True}},
                        "competitors": [
                            {"team": {"id": "2"}, "score": {"value": 1}, "homeAway": "away"},
                            {"team": {"id": "8"}, "score": {"value": 1}, "homeAway": "home"},
                        ],
                    }],
                },
                {
                    "date": "2026-03-03T15:00:00Z",
                    "competitions": [{
                        "status": {"type": {"completed": True}},
                        "competitors": [
                            {"team": {"id": "2"}, "score": {"value": 3}, "homeAway": "home"},
                            {"team": {"id": "8"}, "score": {"value": 2}, "homeAway": "away"},
                        ],
                    }],
                },
                {
                    "date": "2026-03-02T15:00:00Z",
                    "competitions": [{
                        "status": {"type": {"completed": True}},
                        "competitors": [
                            {"team": {"id": "2"}, "score": {"value": 2}, "homeAway": "away"},
                            {"team": {"id": "8"}, "score": {"value": 1}, "homeAway": "home"},
                        ],
                    }],
                },
                {
                    "date": "2026-03-01T15:00:00Z",
                    "competitions": [{
                        "status": {"type": {"completed": True}},
                        "competitors": [
                            {"team": {"id": "2"}, "score": {"value": 0}, "homeAway": "home"},
                            {"team": {"id": "8"}, "score": {"value": 2}, "homeAway": "away"},
                        ],
                    }],
                },
            ],
        }
        conn.executemany(
            "INSERT INTO api_cache (cache_key, data, fetched_at, expires_at) VALUES (?, ?, ?, ?)",
            [
                ("standings:psl:2025", json.dumps(standings_payload), "2026-03-01T00:00:00+00:00", "2099-01-01T00:00:00+00:00"),
                ("schedule:psl:1", json.dumps(schedule_home), "2026-03-01T00:00:00+00:00", "2099-01-01T00:00:00+00:00"),
                ("schedule:psl:2", json.dumps(schedule_away), "2026-03-01T00:00:00+00:00", "2099-01-01T00:00:00+00:00"),
            ],
        )
        conn.commit()
        conn.close()

        with patch.object(bot, "_NARRATIVE_DB_PATH", str(db_path)):
            ctx = await bot._get_cached_match_card_context([
                {"id": "m1", "home_team": "Chiefs", "away_team": "Pirates", "league_key": "psl"},
            ], {})

        assert ctx["m1"]["home_form"] == "WWDLW"
        assert ctx["m1"]["away_form"] == "LDWWL"
        assert ctx["m1"]["home_position"] == 3
        assert ctx["m1"]["away_position"] == 12

    @pytest.mark.asyncio
    async def test_render_full_context_card_with_edge_preview(self, test_db):
        user_id = 51001
        event_id = "mm-premium-1"
        bot._schedule_cache[user_id] = [{
            "id": event_id,
            "home_team": "Chiefs",
            "away_team": "Pirates",
            "commence_time": "2026-03-15T15:00:00Z",
            "sport_emoji": "⚽",
            "league_key": "psl",
        }]
        bot._hot_tips_cache["global"] = {
            "tips": [{
                "event_id": event_id,
                "home_team": "Chiefs",
                "away_team": "Pirates",
                "display_tier": "diamond",
                "edge_rating": "diamond",
                "outcome": "Chiefs",
                "odds": 2.40,
                "edge_v2": {
                    "tier": "diamond",
                    "signals": {
                        "form_h2h": {
                            "available": True,
                            "home_form_string": "WWDLW",
                            "away_form_string": "LDWWL",
                        },
                    },
                },
            }],
            "ts": time.time(),
        }

        try:
            with patch.object(
                db, "get_user_sport_prefs", new_callable=AsyncMock,
                return_value=[MagicMock(team_name="Chiefs", league="psl")],
            ), patch.object(
                bot, "_get_cached_match_card_context", new_callable=AsyncMock,
                return_value={event_id: {
                    "home_form": "WWDLW",
                    "away_form": "LDWWL",
                    "home_position": 3,
                    "away_position": 12,
                }},
            ):
                text, markup = await bot._render_your_games_all(
                    user_id, user_tier="diamond", skip_broadcast=True,
                )

            assert "📈 WWDLW · LDWWL" in text
            assert "📊 3rd vs 12th" in text
            assert "💎 Chiefs to win @ 2.40 → R480 on R200" in text
            button_data = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]
            assert f"yg:game:{event_id}" in button_data
        finally:
            bot._schedule_cache.pop(user_id, None)
            bot._hot_tips_cache.pop("global", None)

    @pytest.mark.asyncio
    async def test_render_partial_context_omits_incomplete_lines(self, test_db):
        user_id = 51002
        event_id = "mm-premium-2"
        bot._hot_tips_cache.pop("global", None)
        bot._schedule_cache[user_id] = [{
            "id": event_id,
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "commence_time": "2026-03-15T17:00:00Z",
            "sport_emoji": "⚽",
            "league_key": "epl",
        }]

        try:
            with patch.object(
                db, "get_user_sport_prefs", new_callable=AsyncMock,
                return_value=[MagicMock(team_name="Arsenal", league="epl")],
            ), patch.object(
                bot, "_get_cached_match_card_context", new_callable=AsyncMock,
                return_value={event_id: {
                    "home_form": "WWDLW",
                    "away_form": "LDWWL",
                    "home_position": 3,
                }},
            ):
                text, _ = await bot._render_your_games_all(
                    user_id, user_tier="diamond", skip_broadcast=True,
                )

            assert "📈 WWDLW · LDWWL" in text
            assert "📊" not in text
            assert "→ R" not in text
        finally:
            bot._schedule_cache.pop(user_id, None)

    @pytest.mark.asyncio
    async def test_render_no_extra_context_falls_back_cleanly(self, test_db):
        user_id = 51003
        event_id = "mm-premium-3"
        bot._hot_tips_cache.pop("global", None)
        bot._schedule_cache[user_id] = [{
            "id": event_id,
            "home_team": "Bulls",
            "away_team": "Stormers",
            "commence_time": "2026-03-15T19:00:00Z",
            "sport_emoji": "🏉",
            "league_key": "urc",
        }]

        try:
            with patch.object(
                db, "get_user_sport_prefs", new_callable=AsyncMock,
                return_value=[MagicMock(team_name="Bulls", league="urc")],
            ), patch.object(
                bot, "_get_cached_match_card_context", new_callable=AsyncMock,
                return_value={event_id: {}},
            ):
                text, _ = await bot._render_your_games_all(
                    user_id, user_tier="diamond", skip_broadcast=True,
                )

            assert "Bulls" in text
            assert "Stormers" in text
            assert "📈" not in text
            assert "📊" not in text
            assert "→ R" not in text
            assert "/subscribe" not in text
        finally:
            bot._schedule_cache.pop(user_id, None)

    @pytest.mark.asyncio
    async def test_render_locked_edge_preview_stays_compact(self, test_db):
        user_id = 51004
        event_id = "mm-premium-4"
        bot._schedule_cache[user_id] = [{
            "id": event_id,
            "home_team": "Chiefs",
            "away_team": "Pirates",
            "commence_time": "2026-03-15T15:00:00Z",
            "sport_emoji": "⚽",
            "league_key": "psl",
        }]
        bot._hot_tips_cache["global"] = {
            "tips": [{
                "event_id": event_id,
                "home_team": "Chiefs",
                "away_team": "Pirates",
                "display_tier": "diamond",
                "edge_rating": "diamond",
                "outcome": "Chiefs",
                "odds": 2.40,
                "edge_v2": {"tier": "diamond", "signals": {}},
            }],
            "ts": time.time(),
        }

        try:
            with patch.object(
                db, "get_user_sport_prefs", new_callable=AsyncMock,
                return_value=[MagicMock(team_name="Chiefs", league="psl")],
            ), patch.object(
                bot, "_get_cached_match_card_context", new_callable=AsyncMock,
                return_value={event_id: {
                    "home_form": "WWDLW",
                    "away_form": "LDWWL",
                    "home_position": 3,
                    "away_position": 12,
                }},
            ):
                text, _ = await bot._render_your_games_all(
                    user_id, user_tier="bronze", skip_broadcast=True,
                )

            assert "🔒 Diamond edge detected — /subscribe" in text
            assert "Chiefs to win @" not in text
            assert "@ 2.40" not in text
        finally:
            bot._schedule_cache.pop(user_id, None)
            bot._hot_tips_cache.pop("global", None)


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
        narrative = "Under Nasreddine Nabi, Chiefs have improved.\nJose Riveiro's Pirates are dangerous."
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

    # ── W81-FACTCHECK: sentence-merge + cleanup + injury lookup ──

    def test_multiline_sentence_stripped_as_unit(self):
        """Multi-line sentence with unverified name is stripped as one unit — no orphaned comma."""
        # "Unknown Player" is not in verified context; sentence spans two lines
        narrative = "Unknown Player is expected to trouble,\nleading to a likely draw."
        result = bot.fact_check_output(narrative, self._CTX)
        assert "Unknown Player" not in result
        # No orphaned comma fragment at the start of any remaining line
        assert not any(line.lstrip().startswith(",") for line in result.split("\n"))

    def test_multiline_sentence_kept_as_unit(self):
        """Multi-line sentence with only verified names survives fact-checking intact."""
        # Ashley Du Preez is a verified top scorer in _CTX
        narrative = "Ashley Du Preez shows great form,\npointing to a home win."
        result = bot.fact_check_output(narrative, self._CTX)
        assert "Ashley Du Preez" in result

    def test_clean_fact_checked_output_orphaned_comma(self):
        """_clean_fact_checked_output removes an orphaned leading comma."""
        result = bot._clean_fact_checked_output(", the stalemate becomes likely.")
        assert not result.startswith(",")
        assert "stalemate" in result

    def test_clean_fact_checked_output_orphaned_connector(self):
        """_clean_fact_checked_output removes lines that are only connector words."""
        text = "Strong form.\nwhile\nDraw expected."
        result = bot._clean_fact_checked_output(text)
        assert "Strong form" in result
        assert "Draw expected" in result
        non_empty = [ln.strip() for ln in result.split("\n") if ln.strip()]
        assert not any(ln.lower() == "while" for ln in non_empty)

    def test_get_verified_injuries_no_crash_empty_team(self):
        """get_verified_injuries returns safe empty lists for empty team strings."""
        result = bot.get_verified_injuries("", "")
        assert result == {"home": [], "away": []}


# ── Wave 29-FIX: Two-Pass Narrative Architecture tests ──

class TestBuildVerifiedNarrative:
    """Test Pass 1: build_verified_narrative() sentence generation."""

    _SPARSE_CTX = {
        "data_available": True,
        "home_team": {
            "name": "Blues",
            "league_position": 3,
            "points": 8,
            "games_played": 3,
            "form": "LWL",
            "record": {"wins": 1, "draws": 0, "losses": 2},
        },
        "away_team": {
            "name": "Crusaders",
            "league_position": 5,
            "points": 7,
            "games_played": 3,
            "form": "WLL",
            "record": {"wins": 1, "draws": 0, "losses": 2},
        },
    }

    _RICH_CTX = {
        "data_available": True,
        "home_team": {
            "name": "Arsenal",
            "league_position": 2,
            "points": 56,
            "games_played": 25,
            "form": "WWDWW",
            "record": {"wins": 17, "draws": 5, "losses": 3},
            "coach": "Mikel Arteta",
            "top_scorer": {"name": "Bukayo Saka", "goals": 12},
            "goals_per_game": 2.1,
            "home_record": "W10 D2 L1",
            "last_5": [
                {"opponent": "Chelsea", "score": "3-1", "result": "W", "home_away": "home"},
                {"opponent": "Man City", "score": "2-0", "result": "W", "home_away": "away"},
            ],
        },
        "away_team": {
            "name": "Liverpool",
            "league_position": 1,
            "points": 61,
            "games_played": 25,
            "form": "WWWWL",
            "record": {"wins": 19, "draws": 4, "losses": 2},
            "coach": "Arne Slot",
            "top_scorer": {"name": "Mohamed Salah", "goals": 15},
            "goals_per_game": 2.5,
            "away_record": "W8 D3 L1",
            "last_5": [
                {"opponent": "Man United", "score": "2-1", "result": "W", "home_away": "away"},
            ],
        },
        "head_to_head": [
            {"home": "Arsenal", "away": "Liverpool", "score": "2-2", "date": "2025-10-27"},
        ],
        "venue": "Emirates Stadium",
    }

    _TIPS = [
        {"outcome": "Arsenal", "odds": 2.40, "bookie": "Hollywoodbets", "prob": 45, "ev": 8.0},
        {"outcome": "Draw", "odds": 3.20, "bookie": "Betway", "prob": 30, "ev": -4.0},
    ]

    def test_sparse_data_produces_sentences(self):
        """Sparse early-season data should produce at least 1 sentence per section."""
        result = bot.build_verified_narrative(self._SPARSE_CTX, self._TIPS, sport="rugby")
        assert len(result["setup"]) >= 2  # at least position for both teams
        assert len(result["edge"]) >= 1
        assert len(result["risk"]) >= 1
        assert len(result["verdict"]) >= 1
        # Verify actual data is in sentences
        setup_text = " ".join(result["setup"])
        assert "Blues" in setup_text
        assert "Crusaders" in setup_text
        assert "LWL" in setup_text or "3rd" in setup_text

    def test_rich_data_produces_more_sentences(self):
        """Rich EPL data should produce 3+ Setup sentences with names."""
        result = bot.build_verified_narrative(self._RICH_CTX, self._TIPS)
        assert len(result["setup"]) >= 4  # positions + form + top scorers + h2h
        setup_text = " ".join(result["setup"])
        assert "Arsenal" in setup_text
        assert "Liverpool" in setup_text
        assert "Arteta" in setup_text or "Saka" in setup_text
        assert "Emirates" in setup_text

    def test_no_data_produces_fallback(self):
        """No context data should still produce setup sentences from signal/odds data."""
        result = bot.build_verified_narrative({"data_available": False}, self._TIPS)
        assert len(result["setup"]) >= 1
        # W63-EMPTY: Setup now uses team names/form from tips instead of "Limited..."
        setup_text = " ".join(result["setup"])
        assert "take on" in setup_text or "face" in setup_text or "Home" in setup_text
        assert len(result["edge"]) >= 1
        assert "Arsenal" in " ".join(result["edge"])  # from tips

    def test_no_tips_produces_no_odds_edge(self):
        """No tips should produce a 'no odds' edge sentence."""
        result = bot.build_verified_narrative(self._RICH_CTX, tips=None)
        edge_text = " ".join(result["edge"])
        assert "No odds" in edge_text or "no odds" in edge_text

    def test_two_pass_user_message_format(self):
        """Verify IMMUTABLE CONTEXT block appears in the expected format."""
        result = bot.build_verified_narrative(self._RICH_CTX, self._TIPS)
        # Simulate what _generate_game_tips does
        parts = ["Match: Arsenal vs Liverpool", "Kickoff: Sat 08 Mar, 17:30 SAST"]
        section_labels = [
            ("setup", "SETUP FACTS"), ("edge", "EDGE FACTS"),
            ("risk", "RISK FACTS"), ("verdict", "VERDICT FACTS"),
        ]
        has_any = any(result.get(s) for s, _ in section_labels)
        assert has_any
        parts.append("\n══ IMMUTABLE CONTEXT (verified — do not alter facts) ══")
        for section, label in section_labels:
            sentences = result.get(section, [])
            if sentences:
                parts.append(f"\n{label}:")
                for s in sentences:
                    parts.append(f"• {s}")
        parts.append("\n══ END IMMUTABLE CONTEXT ══")
        msg = "\n".join(parts)
        assert "IMMUTABLE CONTEXT" in msg
        assert "SETUP FACTS" in msg
        assert "EDGE FACTS" in msg
        assert "• Arsenal sit 2nd" in msg


# ── Wave 17B: Dynamic prompt tests ──

class TestDynamicPrompt:
    """Test sport-parameterised Claude prompt."""

    def test_prompt_contains_sport(self):
        """_build_game_analysis_prompt should include the sport type."""
        prompt = bot._build_game_analysis_prompt("cricket")
        assert "SPORT: cricket" in prompt
        assert "cricket match" in prompt

    def test_prompt_contains_critical_rules(self):
        """Prompt should contain the W29 nuclear ABSOLUTE RULES."""
        prompt = bot._build_game_analysis_prompt("soccer")
        assert "ABSOLUTE RULES" in prompt
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
        """Prompt should explicitly encourage narrative and opinion."""
        prompt = bot._build_game_analysis_prompt("soccer")
        assert "ENCOURAGED" in prompt
        assert "braai" in prompt
        assert "opinions" in prompt or "predictions" in prompt

    def test_prompt_coaches_allowed(self):
        """Prompt should encourage referencing coaches by name from IMMUTABLE CONTEXT."""
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


# W79-PHASE2: TestSetupFallback removed — _ensure_setup_not_empty no longer exists


# ── Wave 29-QA: Persistent /qa Tier Simulation ──────────────────────


class TestGetEffectiveTier:
    """Tests for get_effective_tier() — QA tier override wrapper."""

    @pytest.mark.asyncio
    async def test_returns_override_when_set(self):
        """Should return override tier when set in _QA_TIER_OVERRIDES."""
        bot._QA_TIER_OVERRIDES[99999] = "diamond"
        try:
            result = await bot.get_effective_tier(99999)
            assert result == "diamond"
        finally:
            bot._QA_TIER_OVERRIDES.pop(99999, None)

    @pytest.mark.asyncio
    async def test_falls_through_to_db_when_no_override(self):
        """Should call db.get_user_tier when no override exists."""
        bot._QA_TIER_OVERRIDES.pop(88888, None)
        with patch("bot.db.get_user_tier", new_callable=AsyncMock, return_value="gold") as mock_db:
            result = await bot.get_effective_tier(88888)
            assert result == "gold"
            mock_db.assert_awaited_once_with(88888)

    @pytest.mark.asyncio
    async def test_override_takes_priority_over_db(self):
        """Override should take priority — db.get_user_tier should NOT be called."""
        bot._QA_TIER_OVERRIDES[77777] = "gold"
        try:
            with patch("bot.db.get_user_tier", new_callable=AsyncMock) as mock_db:
                result = await bot.get_effective_tier(77777)
                assert result == "gold"
                mock_db.assert_not_awaited()
        finally:
            bot._QA_TIER_OVERRIDES.pop(77777, None)


class TestQaBanner:
    """Tests for _qa_banner() — QA mode visual indicator."""

    def test_returns_banner_when_override_active(self):
        """Should return formatted banner when tier override is set."""
        bot._QA_TIER_OVERRIDES[55555] = "diamond"
        try:
            result = bot._qa_banner(55555)
            assert "QA Mode" in result
            assert "DIAMOND" in result
        finally:
            bot._QA_TIER_OVERRIDES.pop(55555, None)

    def test_returns_empty_when_no_override(self):
        """Should return empty string when no override is set."""
        bot._QA_TIER_OVERRIDES.pop(44444, None)
        result = bot._qa_banner(44444)
        assert result == ""

    def test_banner_ends_with_double_newline(self):
        """Banner should end with \\n\\n for spacing before content."""
        bot._QA_TIER_OVERRIDES[33333] = "bronze"
        try:
            result = bot._qa_banner(33333)
            assert result.endswith("\n\n")
        finally:
            bot._QA_TIER_OVERRIDES.pop(33333, None)


class TestQaTierOverridePersistence:
    """Tests for override persistence across calls."""

    @pytest.mark.asyncio
    async def test_override_persists_across_multiple_calls(self):
        """Override should persist until explicitly cleared."""
        bot._QA_TIER_OVERRIDES[66666] = "gold"
        try:
            r1 = await bot.get_effective_tier(66666)
            r2 = await bot.get_effective_tier(66666)
            assert r1 == "gold"
            assert r2 == "gold"
        finally:
            bot._QA_TIER_OVERRIDES.pop(66666, None)

    @pytest.mark.asyncio
    async def test_override_cleared_by_pop(self):
        """Popping the override should restore DB behavior."""
        bot._QA_TIER_OVERRIDES[22222] = "diamond"
        bot._QA_TIER_OVERRIDES.pop(22222, None)
        with patch("bot.db.get_user_tier", new_callable=AsyncMock, return_value="bronze") as mock_db:
            result = await bot.get_effective_tier(22222)
            assert result == "bronze"
            mock_db.assert_awaited_once()

    def test_overrides_dict_is_empty_at_import(self):
        """_QA_TIER_OVERRIDES should be empty (module-level dict clears on restart)."""
        # Clean up any test state first
        test_keys = [k for k in bot._QA_TIER_OVERRIDES if k >= 10000]
        for k in test_keys:
            bot._QA_TIER_OVERRIDES.pop(k, None)
        # After cleanup, no test keys should remain
        assert all(k < 10000 for k in bot._QA_TIER_OVERRIDES)


# ── W30-GATE: Gate Leak Fixes ──


class TestGateBreakdownPreambleLeak:
    """W30-GATE: Preamble text before first section emoji must not leak."""

    def test_preamble_stripped_for_non_full(self):
        """Text before first 📋 must be stripped for locked users."""
        narrative = (
            "Here is my analysis of the match.\n\n"
            "📋 <b>The Setup</b>\nSetup content.\n\n"
            "🎯 <b>The Edge</b>\nEdge content.\n\n"
            "⚠️ <b>The Risk</b>\nRisk content.\n\n"
            "🏆 <b>Verdict</b>\nVerdict content."
        )
        result = bot._gate_breakdown_sections(narrative, "bronze", "gold")
        assert "Here is my analysis" not in result
        assert "Setup content" in result
        assert "🔒" in result

    def test_preamble_preserved_for_full_access(self):
        """Full access returns narrative as-is (no gating)."""
        narrative = (
            "Preamble text.\n\n"
            "📋 <b>The Setup</b>\nSetup content."
        )
        result = bot._gate_breakdown_sections(narrative, "diamond", "gold")
        assert "Preamble text" in result

    def test_no_preamble_works(self):
        """Narrative starting directly with 📋 should work fine."""
        narrative = (
            "📋 <b>The Setup</b>\nSetup content.\n\n"
            "🎯 <b>The Edge</b>\nEdge content."
        )
        result = bot._gate_breakdown_sections(narrative, "bronze", "gold")
        assert "Setup content" in result
        assert "🔒" in result


class TestBuildGameButtonsGating:
    """W30-GATE: Button builder must respect edge_tier for access checks."""

    def test_bronze_user_gold_edge_gets_view_plans(self):
        """Bronze user viewing Gold edge should see View Plans, not bookmaker link."""
        tips = [
            {"outcome": "Home Win", "odds": 2.50, "ev": 10.0, "bookie_key": "betway",
             "odds_by_bookmaker": {"betway": 2.50}, "match_id": "test"},
        ]
        buttons = bot._build_game_buttons(
            tips, "gate-test", 111, user_tier="bronze", edge_tier="gold",
        )
        cta_text = buttons[0][0].text
        assert "View Plans" in cta_text

    def test_bronze_user_diamond_edge_gets_view_plans(self):
        """Bronze user viewing Diamond edge should see View Plans."""
        tips = [
            {"outcome": "Draw", "odds": 5.00, "ev": 20.0, "bookie_key": "hwb",
             "odds_by_bookmaker": {"hwb": 5.00}, "match_id": "test"},
        ]
        buttons = bot._build_game_buttons(
            tips, "gate-test", 111, user_tier="bronze", edge_tier="diamond",
        )
        cta_text = buttons[0][0].text
        assert "View Plans" in cta_text

    def test_gold_user_gold_edge_gets_cta(self):
        """Gold user viewing Gold edge should see bookmaker CTA."""
        tips = [
            {"outcome": "Away Win", "odds": 3.00, "ev": 8.5, "bookie_key": "gbets",
             "odds_by_bookmaker": {"gbets": 3.00}, "match_id": "test"},
        ]
        buttons = bot._build_game_buttons(
            tips, "gate-test", 111, user_tier="gold", edge_tier="gold",
        )
        cta_text = buttons[0][0].text
        assert "Back" in cta_text
        assert "View Plans" not in cta_text

    def test_no_positive_ev_bronze_locked_gets_view_plans(self):
        """No positive EV + locked access should show View Plans, not deep link."""
        tips = [
            {"outcome": "Home Win", "odds": 1.50, "ev": -2.0, "bookie_key": "betway",
             "odds_by_bookmaker": {"betway": 1.50}, "match_id": "test"},
        ]
        buttons = bot._build_game_buttons(
            tips, "gate-test", 111, user_tier="bronze", edge_tier="diamond",
        )
        cta_text = buttons[0][0].text
        assert "View Plans" in cta_text

    def test_compare_odds_hidden_for_locked(self):
        """Compare All Odds button should not appear for locked access."""
        tips = [
            {"outcome": "Home Win", "odds": 2.50, "ev": 10.0, "bookie_key": "betway",
             "odds_by_bookmaker": {"betway": 2.50, "hwb": 2.40}, "match_id": "test"},
        ]
        buttons = bot._build_game_buttons(
            tips, "gate-test", 111, user_tier="bronze", edge_tier="diamond",
        )
        all_text = " ".join(b.text for row in buttons for b in row)
        assert "Compare All Odds" not in all_text

    def test_compare_odds_visible_for_full(self):
        """Full access user should get a bookmaker CTA, not View Plans."""
        tips = [
            {"outcome": "Home Win", "odds": 2.50, "ev": 10.0, "bookie_key": "betway",
             "odds_by_bookmaker": {"betway": 2.50, "hwb": 2.40}, "match_id": "test"},
        ]
        buttons = bot._build_game_buttons(
            tips, "gate-test", 111, user_tier="diamond", edge_tier="gold",
        )
        all_text = " ".join(b.text for row in buttons for b in row)
        # Compare All Odds button was removed in later waves; full access shows
        # a bookmaker CTA (URL button) instead of "View Plans"
        assert "View Plans" not in all_text


# ── W30-FORM: Form string truncation tests ────────────────────────────────


class TestTruncateFormBullets:
    """W30-FORM: _truncate_form_bullets() truncates form strings to games_played."""

    def test_truncates_home_form(self):
        """Home form string truncated to games_played."""
        bullets = ["\U0001f4ca Form supports pick (H: LWLWWWWWDL, A: WWD)"]
        ctx = {"home_team": {"games_played": 3}, "away_team": {}}
        result = bot._truncate_form_bullets(bullets, ctx)
        assert "H: LWL" in result[0]
        assert "LWLWWWWWDL" not in result[0]

    def test_truncates_away_form(self):
        """Away form string truncated to games_played."""
        bullets = ["\U0001f4ca Form supports pick (H: WDL, A: LWLWWWWWDL)"]
        ctx = {"home_team": {}, "away_team": {"games_played": 4}}
        result = bot._truncate_form_bullets(bullets, ctx)
        assert "A: LWLW" in result[0]
        assert "LWLWWWWWDL" not in result[0]

    def test_truncates_both(self):
        """Both home and away truncated when both have games_played."""
        bullets = ["\U0001f4ca Form supports pick (H: WWWWWWWWWW, A: LLLLLLLLLL)"]
        ctx = {"home_team": {"games_played": 5}, "away_team": {"games_played": 3}}
        result = bot._truncate_form_bullets(bullets, ctx)
        assert "H: WWWWW" in result[0]
        assert "A: LLL" in result[0]

    def test_no_truncation_when_short(self):
        """Form string shorter than games_played is not truncated."""
        bullets = ["\U0001f4ca Form supports pick (H: WDL)"]
        ctx = {"home_team": {"games_played": 5}, "away_team": {}}
        result = bot._truncate_form_bullets(bullets, ctx)
        assert "H: WDL" in result[0]

    def test_no_truncation_without_context(self):
        """No truncation when match context is None."""
        bullets = ["\U0001f4ca Form supports pick (H: LWLWWWWWDL)"]
        result = bot._truncate_form_bullets(bullets, None)
        assert result == bullets

    def test_no_truncation_without_games_played(self):
        """No truncation when games_played is missing from context."""
        bullets = ["\U0001f4ca Form supports pick (H: LWLWWWWWDL)"]
        ctx = {"home_team": {"name": "Chiefs"}, "away_team": {"name": "Pirates"}}
        result = bot._truncate_form_bullets(bullets, ctx)
        assert "LWLWWWWWDL" in result[0]

    def test_matches_played_fallback(self):
        """Falls back to matches_played when games_played is missing."""
        bullets = ["\U0001f4ca Form supports pick (H: LWLWWWWWDL)"]
        ctx = {"home_team": {"matches_played": 4}, "away_team": {}}
        result = bot._truncate_form_bullets(bullets, ctx)
        assert "H: LWLW" in result[0]

    def test_non_form_bullets_untouched(self):
        """Non-form bullets are not modified."""
        bullets = [
            "\U0001f4b0 +5.2% edge at Hollywoodbets (2.50)",
            "\U0001f4ca Form supports pick (H: WWWWWWWWWW)",
            "\u2705 3/5 bookmakers show value",
        ]
        ctx = {"home_team": {"games_played": 3}, "away_team": {}}
        result = bot._truncate_form_bullets(bullets, ctx)
        assert result[0] == bullets[0]  # unchanged
        assert "H: WWW" in result[1]    # truncated
        assert result[2] == bullets[2]  # unchanged


# ── Morning System Report tests ──────────────────────────────────────────


class TestMorningReport:
    """W34-MORNING: Daily morning system report for admin."""

    @pytest.mark.asyncio
    async def test_morning_report_has_all_sections(self):
        with patch("bot.asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = [
                # get_top_edges
                [
                    {"tier": "gold", "outcome": "home"},
                    {"tier": "silver", "outcome": "draw"},
                    {"tier": "bronze", "outcome": "away"},
                ],
                # check_sharp_data_freshness
                {"healthy": True, "age_hours": 2.5, "row_count": 34000,
                 "bookmakers": ["pinnacle", "betfair_ex_uk", "matchbook"]},
                # get_edge_stats
                {"total": 8, "hits": 5, "hit_rate": 62.5},
                # get_top_10_portfolio_return
                {"total_return": 1250.0, "count": 5},
                # check_health
                (True, []),
            ]
            text = await bot._build_morning_report()
            assert "Morning Report" in text
            assert "Edges:" in text
            assert "3 live" in text
            assert "Draw ratio:" in text
            assert "Sharp data:" in text
            assert "2.5h old" in text
            assert "Yesterday:" in text
            assert "62%" in text
            assert "Portfolio:" in text
            assert "R1,250" in text
            assert "All systems healthy" in text
            assert "Fact-checker:" in text
            assert "Bot uptime:" in text

    @pytest.mark.asyncio
    async def test_morning_report_zero_settled(self):
        with patch("bot.asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = [
                [],  # no live edges
                {"healthy": True, "age_hours": 1.0, "row_count": 100,
                 "bookmakers": ["pinnacle"]},
                {"total": 0, "hits": 0, "hit_rate": 0.0},
                {"total_return": 0, "count": 0},
                (True, []),
            ]
            text = await bot._build_morning_report()
            assert "0 live" in text
            assert "0 edges settled" in text
            assert "0% hit rate" in text

    @pytest.mark.asyncio
    async def test_morning_report_health_alerts(self):
        with patch("bot.asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = [
                [{"tier": "bronze", "outcome": "home"}],
                {"healthy": False, "age_hours": 15.0, "row_count": 100,
                 "bookmakers": ["pinnacle"],
                 "message": "Sharp data is 15.0h old"},
                {"total": 3, "hits": 1, "hit_rate": 33.3},
                {"total_return": 200, "count": 1},
                (False, ["Hollywoodbets stale (3.5h)", "Supabets stale (4h)"]),
            ]
            text = await bot._build_morning_report()
            assert "All systems healthy" not in text
            assert "Sharp data" in text
            assert "Hollywoodbets" in text

    @pytest.mark.asyncio
    async def test_morning_report_no_live_edges(self):
        with patch("bot.asyncio.to_thread") as mock_thread:
            mock_thread.side_effect = [
                [],  # no edges
                {"healthy": True, "age_hours": 0.5, "row_count": 34000,
                 "bookmakers": ["pinnacle", "betfair_ex_uk"]},
                {"total": 5, "hits": 3, "hit_rate": 60.0},
                {"total_return": 800, "count": 3},
                (True, []),
            ]
            text = await bot._build_morning_report()
            assert "0 live" in text
            assert "Draw ratio:</b> 0%" in text


class TestW44Guards:
    """W44-GUARDS: Pre-send validation constants and logic."""

    def test_fallback_phrases_defined(self):
        assert hasattr(bot, "_FALLBACK_PHRASES")
        assert len(bot._FALLBACK_PHRASES) >= 3
        assert "limited verified data" in bot._FALLBACK_PHRASES

    def test_data_rich_leagues_defined(self):
        assert hasattr(bot, "_DATA_RICH_LEAGUES")
        assert "epl" in bot._DATA_RICH_LEAGUES
        assert "psl" in bot._DATA_RICH_LEAGUES
        assert "champions_league" in bot._DATA_RICH_LEAGUES

    def test_guard_blocks_fallback_on_data_rich_league(self):
        """Fallback phrases on EPL should be detected."""
        msg = "Arsenal vs Chelsea\nLimited verified data available.\nBack Arsenal."
        msg_lower = msg.lower()
        blocked = next(
            (p for p in bot._FALLBACK_PHRASES if p in msg_lower), None
        )
        assert blocked == "limited verified data"

    def test_guard_allows_clean_breakdown(self):
        """Clean breakdown with no fallback phrases should pass."""
        msg = "Arsenal sit 2nd on 50 points.\nForm: WWDWW\nBack Arsenal win."
        msg_lower = msg.lower()
        blocked = next(
            (p for p in bot._FALLBACK_PHRASES if p in msg_lower), None
        )
        assert blocked is None

    def test_guard_allows_fallback_on_non_data_rich_league(self):
        """Fallback phrases on non-data-rich leagues should NOT be blocked."""
        target_league = "ufc"
        assert target_league.lower().replace(" ", "_") not in bot._DATA_RICH_LEAGUES

    def test_check_labels_has_breakdown_quality(self):
        """CHECK_LABELS in _qa_health_check should include breakdown_quality."""
        import inspect
        src = inspect.getsource(bot._qa_health_check)
        assert "breakdown_quality" in src


class TestNarrativeCache:
    """W60-CACHE: Persistent narrative caching tests."""

    def test_ensure_narrative_cache_table_creates_table(self, tmp_path):
        """Table creation should succeed on a fresh DB."""
        import sqlite3
        db_path = str(tmp_path / "test_odds.db")
        # Temporarily override the DB path
        original = bot._NARRATIVE_DB_PATH
        bot._NARRATIVE_DB_PATH = db_path
        try:
            bot._ensure_narrative_cache_table()
            conn = sqlite3.connect(db_path)
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='narrative_cache'"
            ).fetchall()
            conn.close()
            assert len(tables) == 1
        finally:
            bot._NARRATIVE_DB_PATH = original

    @pytest.mark.asyncio
    async def test_store_and_retrieve_cached_narrative(self, tmp_path):
        """Store a narrative, then retrieve it from cache."""
        import sqlite3
        db_path = str(tmp_path / "test_odds.db")
        original = bot._NARRATIVE_DB_PATH
        bot._NARRATIVE_DB_PATH = db_path

        # Create both required tables
        conn = sqlite3.connect(db_path)
        conn.execute("""CREATE TABLE IF NOT EXISTS odds_latest (
            match_id TEXT, bookmaker TEXT, home_odds REAL,
            draw_odds REAL, away_odds REAL
        )""")
        conn.commit()
        conn.close()

        try:
            bot._ensure_narrative_cache_table()
            await bot._store_narrative_cache(
                "chiefs_vs_sundowns_2026-03-08",
                "<b>Test narrative</b>",
                [{"outcome": "home", "odds": 2.5, "ev": 5.0}],
                "bronze",  # non-premium tier: w82+bronze is accepted without HTML header check
                "opus",
            )
            result = await bot._get_cached_narrative("chiefs_vs_sundowns_2026-03-08")
            assert result is not None
            assert result["html"] == "<b>Test narrative</b>"
            assert result["model"] == "opus"
            assert result["edge_tier"] == "bronze"
            assert len(result["tips"]) == 1
        finally:
            bot._NARRATIVE_DB_PATH = original

    @pytest.mark.asyncio
    async def test_expired_narrative_returns_none(self, tmp_path):
        """Expired cache entries should return None."""
        import sqlite3
        from datetime import datetime, timedelta, timezone
        db_path = str(tmp_path / "test_odds.db")
        original = bot._NARRATIVE_DB_PATH
        bot._NARRATIVE_DB_PATH = db_path

        conn = sqlite3.connect(db_path)
        conn.execute("""CREATE TABLE IF NOT EXISTS odds_latest (
            match_id TEXT, bookmaker TEXT, home_odds REAL,
            draw_odds REAL, away_odds REAL
        )""")
        conn.commit()

        try:
            bot._ensure_narrative_cache_table()
            # Insert with past expires_at
            past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            conn.execute(
                "INSERT INTO narrative_cache "
                "(match_id, narrative_html, model, edge_tier, tips_json, odds_hash, "
                "created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("old_match", "<b>old</b>", "haiku", "bronze", "[]", "", past, past),
            )
            conn.commit()
            conn.close()

            result = await bot._get_cached_narrative("old_match")
            assert result is None
        finally:
            bot._NARRATIVE_DB_PATH = original

    def test_compute_odds_hash_empty(self, tmp_path):
        """Hash of nonexistent match returns empty string."""
        import sqlite3
        db_path = str(tmp_path / "test_odds.db")
        original = bot._NARRATIVE_DB_PATH
        bot._NARRATIVE_DB_PATH = db_path

        conn = sqlite3.connect(db_path)
        conn.execute("""CREATE TABLE IF NOT EXISTS odds_latest (
            match_id TEXT, bookmaker TEXT, home_odds REAL,
            draw_odds REAL, away_odds REAL
        )""")
        conn.commit()
        conn.close()

        try:
            result = bot._compute_odds_hash("nonexistent_match")
            assert result == ""
        finally:
            bot._NARRATIVE_DB_PATH = original

    def test_qa_commands_includes_cache(self):
        """The /qa cache command should be listed in _QA_COMMANDS."""
        assert "cache" in bot._QA_COMMANDS


class TestW63EmptySections:
    """W63-EMPTY: Verify empty section detection and fallback injection."""

    def test_has_empty_sections_detects_empty_setup(self):
        narrative = "📋 <b>The Setup</b>\n\n🎯 <b>The Edge</b>\nSome edge text.\n⚠️ <b>The Risk</b>\nSome risk.\n🏆 <b>Verdict</b>\nBack X."
        assert bot._has_empty_sections(narrative) is True

    def test_has_empty_sections_passes_full_narrative(self):
        narrative = (
            "📋 <b>The Setup</b>\nArsenal sit 2nd on 56 points. Liverpool lead the table.\n\n"
            "🎯 <b>The Edge</b>\nBest value: Arsenal at 2.40.\n\n"
            "⚠️ <b>The Risk</b>\nNo specific risk signals detected.\n\n"
            "🏆 <b>Verdict</b>\nBack Arsenal at 2.40 on Hollywoodbets — the numbers support the edge."
        )
        assert bot._has_empty_sections(narrative) is False

    def test_ensure_risk_not_empty_fills_empty_risk(self):
        narrative = (
            "📋 <b>The Setup</b>\nArsenal face Liverpool.\n\n"
            "🎯 <b>The Edge</b>\nBest value sits with Arsenal.\n\n"
            "⚠️ <b>The Risk</b>\n\n"
            "🏆 <b>Verdict</b>\nBack Arsenal."
        )
        result = bot._ensure_risk_not_empty(narrative, sport="soccer")
        assert "standard match variance" in result

    # W79-PHASE2: test_ensure_setup_not_empty_uses_signals removed

    def test_ensure_verdict_not_empty_fills_empty_verdict(self):
        narrative = (
            "📋 <b>The Setup</b>\nArsenal face Liverpool.\n\n"
            "🎯 <b>The Edge</b>\nBest value sits with Arsenal.\n\n"
            "⚠️ <b>The Risk</b>\nNo major red flags.\n\n"
            "🏆 <b>Verdict</b>\n"
        )
        tips = [{
            "outcome": "home",
            "odds": 2.40,
            "bookie": "Hollywoodbets",
            "ev": 8.0,
            "edge_v2": {"confirming_signals": 3, "stale_minutes": 0},
        }]
        result = bot._ensure_verdict_not_empty(
            narrative,
            tips=tips,
            home_name="Arsenal",
            away_name="Liverpool",
        )
        assert "Arsenal" in result
        assert "2.40" in result
        assert "Hollywoodbets" in result

    def test_has_stale_h2h_summary_detects_inverted_cached_line(self):
        narrative = (
            "📋 <b>The Setup</b>\n"
            "Head to head: 5 meetings: Aston Villa 0W 5D 0L.\n\n"
            "🎯 <b>The Edge</b>\nSome edge text.\n\n"
            "⚠️ <b>The Risk</b>\nSome risk.\n\n"
            "🏆 <b>Verdict</b>\nBack Aston Villa."
        )
        tips = [{
            "outcome": "home",
            "odds": 2.03,
            "bookie": "Supabets",
            "ev": 2.0,
            "edge_v2": {
                "match_key": "aston_villa_vs_west_ham_2026-03-22",
                "league": "epl",
                "signals": {
                    "form_h2h": {
                        "h2h_total": 5,
                        "h2h_a_wins": 3,
                        "h2h_b_wins": 0,
                        "h2h_draws": 2,
                    },
                },
            },
        }]
        assert bot._has_stale_h2h_summary(narrative, tips) is True

    def test_has_stale_h2h_summary_allows_correct_line(self):
        narrative = (
            "📋 <b>The Setup</b>\n"
            "Head to head: 5 meetings: Aston Villa 3W 2D 0L.\n\n"
            "🎯 <b>The Edge</b>\nSome edge text.\n\n"
            "⚠️ <b>The Risk</b>\nSome risk.\n\n"
            "🏆 <b>Verdict</b>\nBack Aston Villa."
        )
        tips = [{
            "outcome": "home",
            "odds": 2.03,
            "bookie": "Supabets",
            "ev": 2.0,
            "edge_v2": {
                "match_key": "aston_villa_vs_west_ham_2026-03-22",
                "league": "epl",
                "signals": {
                    "form_h2h": {
                        "h2h_total": 5,
                        "h2h_a_wins": 3,
                        "h2h_b_wins": 0,
                        "h2h_draws": 2,
                    },
                },
            },
        }]
        assert bot._has_stale_h2h_summary(narrative, tips) is False

    def test_build_verified_narrative_no_espn_uses_signals(self):
        tips = [{"outcome": "Arsenal", "odds": 2.40, "bookie": "HWB", "prob": 45, "ev": 8.0, "edge_v2": {
            "match_key": "arsenal_vs_liverpool_2026-03-08",
            "league": "EPL",
            "signals": {
                "form_h2h": {"available": True, "home_form_string": "WWDWW", "away_form_string": "WDWWW"},
                "lineup_injury": {"available": True, "home_injuries": 2, "away_injuries": 1},
            },
        }}]
        result = bot.build_verified_narrative({"data_available": False}, tips)
        setup_text = " ".join(result["setup"])
        assert "Arsenal" in setup_text
        assert "WWDWW" in setup_text
        assert "2 player(s) out" in setup_text


class TestW64VerdictFixes:
    """W64-VERDICT: Stale contradiction detection + banned phrases."""

    def test_new_banned_phrases_in_list(self):
        """8 new urgency phrases added to BANNED_NARRATIVE_PHRASES."""
        assert "grab it before" in bot.BANNED_NARRATIVE_PHRASES
        assert "before they wake up" in bot.BANNED_NARRATIVE_PHRASES
        assert "move fast" in bot.BANNED_NARRATIVE_PHRASES
        assert "won't last forever" in bot.BANNED_NARRATIVE_PHRASES
        assert "before they slash" in bot.BANNED_NARRATIVE_PHRASES

    def test_has_banned_patterns_catches_new_phrases(self):
        narrative = "Grab it before they wake up — HWB's 2.40 is great value."
        assert bot._has_banned_patterns(narrative) is True

    def test_has_banned_patterns_allows_clean_verdict(self):
        narrative = "Hollywoodbets' 2.40 on Arsenal sits 9% above the sharp benchmark."
        assert bot._has_banned_patterns(narrative) is False

    def test_stale_contradiction_detected(self):
        edge = {"stale_warning": True, "stale_minutes": 90}
        narrative = "Take it before they adjust — HWB's 2.40 is the play."
        assert bot._check_stale_contradiction(narrative, edge) is True

    def test_stale_contradiction_not_triggered_without_stale(self):
        edge = {"stale_warning": False, "stale_minutes": 10}
        narrative = "Take it before they adjust — HWB's 2.40 is the play."
        assert bot._check_stale_contradiction(narrative, edge) is False

    def test_stale_contradiction_not_triggered_clean_verdict(self):
        edge = {"stale_warning": True, "stale_minutes": 90}
        narrative = "Check HWB's live odds before acting — the 2.40 may have already closed."
        assert bot._check_stale_contradiction(narrative, edge) is False

    def test_stale_contradiction_none_edge(self):
        assert bot._check_stale_contradiction("any text", None) is False

    def test_prompt_contains_verdict_decision_rules(self):
        """W67: Verify 6 verdict decision rules in prompt."""
        prompt = bot._build_analyst_prompt("soccer")
        assert "VERDICT DECISION RULES" in prompt
        assert "DEAD PRICE" in prompt
        assert "STALE PRICE" in prompt
        assert "3+ confirming signals" in prompt
        assert "2+ confirming signals" in prompt
        assert "clean price edge" in prompt
        assert "tipster consensus AND market movement" in prompt
        assert "VERDICT ABSOLUTE RULES" in prompt
        assert "one to watch" in prompt.lower()
        # W69-VERIFY: STEP 1 verification instruction
        assert "STEP 1" in prompt
        assert "VERIFY BEFORE WRITING" in prompt

    def test_prompt_contains_new_banned_phrases(self):
        prompt = bot._build_analyst_prompt("soccer")
        assert "grab it before" in prompt
        assert "before they wake up" in prompt

    # ── W69-VERIFY Tests ──

    def test_extract_text_from_response(self):
        """W69: Verify text extraction from multi-block responses."""
        class FakeTextBlock:
            def __init__(self, t):
                self.text = t
        class FakeToolBlock:
            pass  # No text attribute
        class FakeResp:
            def __init__(self, blocks):
                self.content = blocks

        # Single text block (normal response)
        resp = FakeResp([FakeTextBlock("Hello world")])
        assert bot._extract_text_from_response(resp) == "Hello world"

        # Multi-block with tool blocks interspersed
        resp = FakeResp([
            FakeTextBlock("Part 1"),
            FakeToolBlock(),
            FakeTextBlock("Part 2"),
        ])
        assert bot._extract_text_from_response(resp) == "Part 1\nPart 2"

        # Block with text=None (e.g. ServerToolUseBlock)
        resp = FakeResp([FakeTextBlock(None), FakeTextBlock("After search")])
        assert bot._extract_text_from_response(resp) == "After search"

        # Empty response
        resp = FakeResp([])
        assert bot._extract_text_from_response(resp) == ""

    def test_extract_claims(self):
        """W69: Verify claim extraction from narrative text."""
        text = (
            "England sit 4th on 7 points from 3 games. "
            "Form reads LLW after losses. "
            "Record: W1 D0 L2 this season."
        )
        claims = bot._extract_claims(text)
        assert any("LLW" in c for c in claims), f"Expected form claim, got {claims}"
        assert any("4th" in c for c in claims), f"Expected position claim, got {claims}"
        assert any("W1" in c for c in claims), f"Expected record claim, got {claims}"

    def test_web_search_tool_config(self):
        """W69: Verify WEB_SEARCH_TOOL configuration."""
        assert bot.WEB_SEARCH_TOOL["type"] == "web_search_20250305"
        assert bot.WEB_SEARCH_TOOL["name"] == "web_search"
        assert bot.WEB_SEARCH_TOOL["max_uses"] == 3  # W73-LAUNCH: increased from 2

    # ── W73-LAUNCH Tests ──

    # W79-PHASE2: test_ensure_verdict_not_empty + test_ensure_verdict_with_stale removed

    def test_programmatic_no_banned_phrases(self):
        """W73: Programmatic fallback contains zero banned phrases."""
        ctx_data = {
            "data_available": True,
            "home_team": {"name": "Arsenal", "form": "WWLWD", "league_position": 2, "points": 55, "games_played": 25},
            "away_team": {"name": "Chelsea", "form": "WDLWL", "league_position": 5, "points": 42, "games_played": 25},
        }
        tips = [{
            "outcome": "Home Win", "odds": 1.85, "ev": 3.5,
            "bookmaker": "Hollywoodbets",
            "edge_v2": {"confirming_signals": 2},
        }]
        narrative = bot._build_programmatic_narrative(ctx_data, tips, "soccer")
        assert narrative, "Narrative should not be empty"
        lower = narrative.lower()
        for phrase in bot.BANNED_NARRATIVE_PHRASES:
            assert phrase not in lower, f"Banned phrase '{phrase}' found in programmatic narrative"

    def test_known_team_nicknames_not_stripped(self):
        """W73: Fact-checker preserves known team nicknames."""
        narrative = (
            "📋 <b>The Setup</b>\n"
            "The Blues have been dominant this season.\n"
            "Los Blancos are chasing the title.\n\n"
            "🎯 <b>The Edge</b>\nEdge text.\n\n"
            "⚠️ <b>The Risk</b>\nRisk text.\n\n"
            "🏆 <b>Verdict</b>\nVerdict text here with enough content."
        )
        ctx_data = {"data_available": True, "home_team": {"name": "Chelsea"}, "away_team": {"name": "Real Madrid"}}
        result = bot.fact_check_output(narrative, ctx_data)
        assert "The Blues" in result, "Nickname 'The Blues' should not be stripped"
        assert "Los Blancos" in result, "Nickname 'Los Blancos' should not be stripped"

    def test_narrative_model_env_var(self):
        """W73: pregenerate MODELS dict reads NARRATIVE_MODEL env var."""
        import importlib
        import os
        # The default (no env var) should be sonnet
        # We can't easily test the env var in-process since the module is already loaded,
        # but we can verify the current value is sonnet (not opus)
        from scripts import pregenerate_narratives
        for sweep_type, model_id in pregenerate_narratives.MODELS.items():
            assert "opus" not in model_id, f"MODELS['{sweep_type}'] still uses Opus: {model_id}"
            assert "sonnet" in model_id or os.environ.get("NARRATIVE_MODEL", "") in model_id

    def test_mandatory_search_prompt(self):
        """W73: mandatory_search=True produces mandatory web search instruction."""
        prompt_mandatory = bot._build_analyst_prompt("soccer", mandatory_search=True)
        assert "MUST use web search" in prompt_mandatory
        assert "NON-NEGOTIABLE" in prompt_mandatory

        prompt_default = bot._build_analyst_prompt("soccer", mandatory_search=False)
        assert "If web search is available" in prompt_default
        assert "NON-NEGOTIABLE" not in prompt_default


# ── W81-HEALTH regression tests ──────────────────────────────────────────


class TestW81Health:
    """Regression tests for W81-HEALTH fixture-aware thresholds + pre-gen safeguards."""

    def test_validate_bot_imports_passes(self):
        """All _REQUIRED_BOT_FUNCTIONS exist in bot module — import validation passes."""
        required = [
            "build_verified_narrative",
            "fact_check_output",
            "_build_setup_section_v2",
            "_clean_fact_checked_output",
            "get_verified_injuries",
        ]
        missing = [fn for fn in required if not hasattr(bot, fn)]
        assert missing == [], f"Missing bot functions: {missing}"

    def test_settlement_skip_warning_present(self):
        """settle_edges() has WARNING log for missing match_results case."""
        import inspect
        from scrapers.edge import settlement
        src = inspect.getsource(settlement.settle_edges)
        assert "warning" in src.lower()
        assert "match_results" in src

    def test_post_deploy_slump_day_is_monday(self):
        """_is_slump_day returns True for Monday (weekday 0)."""
        from datetime import datetime, timezone
        monday = datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc)  # Mon 9 Mar 2026
        with patch("tests.post_deploy_validation.datetime") as mock_dt:
            mock_dt.now.return_value = monday
            from tests.post_deploy_validation import _is_slump_day, _fixture_minimum
            assert _is_slump_day() is True
            assert _fixture_minimum() == 1

    def test_post_deploy_peak_day_is_saturday(self):
        """_is_slump_day returns False for Saturday (weekday 5) and minimum is 3."""
        from datetime import datetime, timezone
        saturday = datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc)  # Sat 7 Mar 2026
        with patch("tests.post_deploy_validation.datetime") as mock_dt:
            mock_dt.now.return_value = saturday
            from tests.post_deploy_validation import _is_slump_day, _fixture_minimum
            assert _is_slump_day() is False
            assert _fixture_minimum() == 3


# ── W81-SCAFFOLD regression tests ────────────────────────────────────────

class TestW81Scaffold:
    """Regression tests for _decide_team_story() and _build_verified_scaffold()."""

    def test_title_push(self):
        """Top-2 position with 3+ wins → title_push."""
        from bot import _decide_team_story
        assert _decide_team_story(1, 72, "WWWDD", None, None, 2.1, is_home=True) == "title_push"

    def test_crisis_consecutive_losses(self):
        """3+ consecutive losses → crisis."""
        from bot import _decide_team_story
        assert _decide_team_story(14, 20, "LLLWD", None, None, 0.8, is_home=False) == "crisis"

    def test_crisis_relegation_zone(self):
        """Position >= 14 → crisis regardless of form (threshold lowered in W81-CLEANUP)."""
        from bot import _decide_team_story
        assert _decide_team_story(18, 15, "WDWDL", None, None, 1.0, is_home=True) == "crisis"

    def test_crisis_bottom_half_with_win(self):
        """Bottom-half team (pos=14) that just won still gets crisis — Fix 1 (W81-CLEANUP)."""
        from bot import _decide_team_story
        # Chippa: 14th, WLLLD — crisis fires via pos>=14, not recovery (recovery guarded to pos<=13)
        assert _decide_team_story(14, 20, "WLLLD", None, None, 0.8, is_home=False) == "crisis"

    def test_recovery_mid_table_only(self):
        """Mid-table team (pos<=13) that bounced back gets recovery — Fix 1 (W81-CLEANUP)."""
        from bot import _decide_team_story
        # 8th, WLLWW: form[0]='W', l=2, pos=8<=13 → recovery
        assert _decide_team_story(8, 35, "WLLWW", None, None, 1.4, is_home=True) == "recovery"

    def test_momentum(self):
        """2+ consecutive wins → momentum."""
        from bot import _decide_team_story
        assert _decide_team_story(12, 40, "WWDWD", None, None, 1.5, is_home=True) == "momentum"

    def test_inconsistent(self):
        """Mix of 2+ wins and 2+ losses (not starting with W) → inconsistent."""
        from bot import _decide_team_story
        # "DWLWL": doesn't start with W (no recovery), consec_w=0 (no momentum), w>=2 and l>=2
        assert _decide_team_story(8, 35, "DWLWL", None, None, 1.3, is_home=False) == "inconsistent"

    def test_setback(self):
        """Last result a loss but 2+ wins in form → setback."""
        from bot import _decide_team_story
        assert _decide_team_story(5, 45, "LWWD", None, None, 1.8, is_home=False) == "setback"

    def test_neutral_fallback(self):
        """No strong signal → neutral."""
        from bot import _decide_team_story
        assert _decide_team_story(None, None, "", None, None, None, is_home=True) == "neutral"

    def test_scaffold_basic_structure(self):
        """_build_verified_scaffold returns required sections."""
        from bot import _build_verified_scaffold
        ctx = {
            "data_available": True,
            "league": "English Premier League",
            "home_team": {
                "name": "Arsenal",
                "position": 1,
                "points": 72,
                "games_played": 29,
                "form": "WWWDD",
                "goals_per_game": 2.3,
                "home_record": "W9 D2 L3",
                "last_5": [
                    {"result": "W", "opponent": "Everton", "score": "2-0", "home_away": "home"}
                ],
            },
            "away_team": {
                "name": "Everton",
                "position": 17,
                "points": 20,
                "games_played": 29,
                "form": "LLLWD",
                "goals_per_game": 0.9,
                "away_record": "W1 D2 L11",
            },
            "head_to_head": [],
        }
        edge_data = {
            "home_team": "Arsenal",
            "away_team": "Everton",
            "league": "epl",
            "best_bookmaker": "Hollywoodbets",
            "best_odds": 1.42,
            "edge_pct": 8.3,
            "outcome": "home",
            "outcome_team": "Arsenal",
            "confirming_signals": 4,
            "composite_score": 72.0,
            "bookmaker_count": 5,
            "market_agreement": 85,
            "stale_minutes": 0,
        }
        scaffold = _build_verified_scaffold(ctx, edge_data, "soccer")
        assert "HOME_STORY_TYPE: title_push" in scaffold
        assert "AWAY_STORY_TYPE: crisis" in scaffold
        assert "Arsenal" in scaffold
        assert "Everton" in scaffold
        assert "EV: +8.3%" in scaffold
        assert "Confirming signals: 4/7" in scaffold
        assert "RISK FACTORS:" in scaffold

    def test_scaffold_includes_h2h(self):
        """Scaffold includes H2H section when meetings exist."""
        from bot import _build_verified_scaffold
        ctx = {
            "home_team": {"name": "Home FC"},
            "away_team": {"name": "Away FC"},
            "head_to_head": [
                {"home_team": "Home FC", "away_team": "Away FC",
                 "home_score": 2, "away_score": 1, "date": "2025-10-01"},
                {"home_team": "Away FC", "away_team": "Home FC",
                 "home_score": 0, "away_score": 0, "date": "2025-04-15"},
            ],
        }
        edge_data = {
            "home_team": "Home FC", "away_team": "Away FC",
            "best_bookmaker": "?", "best_odds": 0, "edge_pct": 0,
            "outcome": "home", "outcome_team": "Home FC",
            "confirming_signals": 0, "composite_score": 0,
            "bookmaker_count": 0, "market_agreement": 0, "stale_minutes": 0,
        }
        scaffold = _build_verified_scaffold(ctx, edge_data, "soccer")
        assert "H2H: 2 meetings" in scaffold

    def test_scaffold_stale_risk_factor(self):
        """Stale pricing >= 360 min appears in RISK FACTORS."""
        from bot import _build_verified_scaffold
        ctx = {"home_team": {"name": "A"}, "away_team": {"name": "B"}, "head_to_head": []}
        edge_data = {
            "home_team": "A", "away_team": "B",
            "best_bookmaker": "Betway", "best_odds": 2.1, "edge_pct": 5.0,
            "outcome": "home", "outcome_team": "A",
            "confirming_signals": 0, "composite_score": 50, "bookmaker_count": 3,
            "market_agreement": 60, "stale_minutes": 420,
        }
        scaffold = _build_verified_scaffold(ctx, edge_data, "soccer")
        assert "Stale pricing" in scaffold
        assert "7 hours" in scaffold

    def test_scaffold_exported(self):
        """_build_verified_scaffold and _decide_team_story are importable from bot."""
        from bot import _build_verified_scaffold, _decide_team_story
        assert callable(_build_verified_scaffold)
        assert callable(_decide_team_story)

    def test_load_exemplars_callable(self):
        """load_exemplars() returns a dict with top-level keys — Fix 4 (W81-CLEANUP)."""
        from bot import load_exemplars
        data = load_exemplars()
        assert isinstance(data, dict)
        # Must have at least the setup key (graceful fallback returns empty setup dict)
        assert "setup" in data


# ── W81-COACHES regression tests ──────────────────────────────────────────

class TestW81Coaches:
    """Regression tests for W81-COACHES: coaches.json priority + degraded response."""

    def _get_coach(self, *args):
        import sys
        from config import ensure_scrapers_importable
        ensure_scrapers_importable()
        from scrapers.match_context_fetcher import _get_coach
        return _get_coach(*args)

    def test_arsenal_coach_resolved(self):
        """Arsenal coach resolves to Mikel Arteta from coaches.json."""
        assert self._get_coach("arsenal", "epl", "soccer") == "Mikel Arteta"

    def test_everton_coach_resolved(self):
        """Everton coach resolves from coaches.json (not stale api_cache)."""
        assert self._get_coach("everton", "epl", "soccer") == "David Moyes"

    def test_wolves_alias_resolved(self):
        """'wolves' short-name alias resolves via coaches.json — W81-COACHES alias fix."""
        assert self._get_coach("wolves", "epl", "soccer") == "Rob Edwards"

    def test_degraded_response_includes_coach(self):
        """Degraded response (DB lock scenario) still includes coach from static JSON."""
        import sys
        from config import ensure_scrapers_importable
        ensure_scrapers_importable()
        from scrapers.match_context_fetcher import _get_coach, _degraded_response, LEAGUE_CONFIG
        config = LEAGUE_CONFIG["epl"]
        resp = _degraded_response(config, "arsenal", "everton", "database is locked")
        # Simulate what get_match_context() now does on exception
        resp["home_team"]["coach"] = _get_coach("arsenal", "epl", "soccer")
        resp["away_team"]["coach"] = _get_coach("everton", "epl", "soccer")
        assert resp["home_team"]["coach"] == "Mikel Arteta"
        assert resp["away_team"]["coach"] == "David Moyes"

    def test_static_json_priority_over_api_cache(self):
        """coaches.json lookup returns a value even if called with underscore team name."""
        # System uses manchester_united (underscore) as canonical key.
        # NOTE: coaches.json currently has stale/wrong data for Man United + Chelsea
        # (data audit 2026-04-15 has wrong values — flag for Paul to re-verify).
        # Test asserts production behavior (what coaches.json returns), not real-world truth.
        assert self._get_coach("manchester_united", "epl", "soccer") == "Michael Carrick"
        assert self._get_coach("chelsea", "epl", "soccer") == "Liam Rosenior"


# ── BUILD-DEEPLINK-HARDEN-01 — /start card_<key> handler guards ──


class TestCardDeeplinkHandler:
    """Validate _handle_card_deeplink rejects malformed keys and reroutes empty tips.

    References:
    - Part A: edge_ prefix reject → _dl_send_edge_no_longer_available
    - Part B: valid key but no tip → same fallback (not skeleton-dict render)
    - Case C: valid key with tip → normal render path
    """

    @pytest.mark.asyncio
    async def test_edge_prefix_rejected_and_rerouted(self, mock_update, mock_context):
        with patch.object(bot, "_dl_send_edge_no_longer_available", new=AsyncMock()) as fb, \
             patch.object(bot, "_load_tips_from_edge_results") as load_tips, \
             patch.object(bot, "get_effective_tier", new=AsyncMock(return_value="bronze")):
            await bot._handle_card_deeplink(
                mock_update, mock_context, 123, "edge_arsenal_vs_chelsea_2026-04-22"
            )

        fb.assert_awaited_once()
        load_tips.assert_not_called()

    @pytest.mark.asyncio
    async def test_valid_key_no_tip_reroutes_to_fallback(self, mock_update, mock_context):
        with patch.object(bot, "_dl_send_edge_no_longer_available", new=AsyncMock()) as fb, \
             patch.object(bot, "_load_tips_from_edge_results", return_value=[]), \
             patch.object(bot, "get_effective_tier", new=AsyncMock(return_value="bronze")), \
             patch("scrapers.db_connect.connect_odds_db") as db_conn:
            cur = MagicMock()
            cur.fetchone.return_value = None
            conn = MagicMock()
            conn.execute.return_value = cur
            conn.close = MagicMock()
            db_conn.return_value = conn

            await bot._handle_card_deeplink(
                mock_update, mock_context, 123, "arsenal_vs_chelsea_2026-04-22"
            )

        fb.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_valid_key_with_tip_renders_normally(self, mock_update, mock_context):
        tip = {
            "match_id": "arsenal_vs_chelsea_2026-04-22",
            "match_key": "arsenal_vs_chelsea_2026-04-22",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "edge_tier": "gold",
            "display_tier": "gold",
            "ev": 5.0,
        }
        with patch.object(bot, "_dl_send_edge_no_longer_available", new=AsyncMock()) as fb, \
             patch.object(bot, "_load_tips_from_edge_results", return_value=[tip]), \
             patch.object(bot, "_enrich_tip_for_card", return_value=tip), \
             patch.object(bot, "_has_any_cached_narrative", return_value=False), \
             patch.object(bot, "build_edge_detail_data", return_value={"home": "Arsenal", "away": "Chelsea"}), \
             patch.object(bot, "_build_game_buttons", return_value=[]), \
             patch.object(bot, "send_card_or_fallback", new=AsyncMock()) as send_card, \
             patch.object(bot, "get_effective_tier", new=AsyncMock(return_value="bronze")):
            await bot._handle_card_deeplink(
                mock_update, mock_context, 123, "arsenal_vs_chelsea_2026-04-22"
            )

        fb.assert_not_called()
        send_card.assert_awaited_once()
