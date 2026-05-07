"""Tests for Day 1 features: experience onboarding, persistent menu, adapted pick cards."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import bot
import config
import db
from scripts.odds_client import (
    ValueBet,
    format_pick_card,
)


# ── Helper ─────────────────────────────────────────────────

def _make_query(user_id: int = 55555, data: str = "") -> MagicMock:
    query = MagicMock()
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.from_user = MagicMock()
    query.from_user.id = user_id
    query.from_user.first_name = "Tester"
    query.from_user.username = "tester"
    query.data = data
    query.message.chat.send_message = AsyncMock()
    query.message.chat_id = user_id
    return query


SAMPLE_PICK = ValueBet(
    home="Arsenal", away="Chelsea", sport_key="soccer",
    outcome="Arsenal", best_price=2.30, bookmaker="Hollywoodbets",
    is_sa_book=True, fair_prob=0.45, ev_pct=3.5,
    kelly_stake=0.05, confidence="🟡 Medium",
)

NEWBIE_PICK = ValueBet(
    home="Liverpool", away="Everton", sport_key="soccer",
    outcome="Draw", best_price=3.50, bookmaker="Bet365",
    is_sa_book=False, fair_prob=0.30, ev_pct=5.0,
    kelly_stake=0.03, confidence="🟡 Medium",
)


pytestmark = pytest.mark.asyncio


# ── Priority 1: Experience-Level Onboarding ─────────────────

class TestExperienceOnboarding:
    def test_kb_experience_has_three_options(self):
        kb = bot.kb_onboarding_experience()
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        assert len(buttons) == 3
        labels = [b.text for b in buttons]
        assert any("regularly" in l for l in labels)
        assert any("few bets" in l for l in labels)
        assert any("new" in l.lower() for l in labels)

    def test_kb_experience_callback_data(self):
        kb = bot.kb_onboarding_experience()
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "ob_exp:experienced" in callbacks
        assert "ob_exp:casual" in callbacks
        assert "ob_exp:newbie" in callbacks

    async def test_handle_experience_sets_level(self):
        bot._onboarding_state.clear()
        bot._get_ob(20001)  # initialise

        query = _make_query(user_id=20001)
        await bot.handle_ob_experience(query, "experienced")

        ob = bot._get_ob(20001)
        assert ob["experience"] == "experienced"
        assert ob["step"] == "sports"

    async def test_handle_experience_moves_to_sports(self):
        bot._onboarding_state.clear()
        bot._get_ob(20002)

        query = _make_query(user_id=20002)
        # send_card_or_fallback is now used (IMAGE ONLY rule — no text fallback)
        with patch("bot.send_card_or_fallback", new=AsyncMock()):
            await bot.handle_ob_experience(query, "casual")

        ob = bot._get_ob(20002)
        assert ob["step"] == "sports"
        assert ob["experience"] == "casual"

    async def test_cmd_start_shows_experience_first(self, test_db):
        mock_update = MagicMock()
        mock_user = MagicMock()
        mock_user.id = 20003
        mock_user.username = "newuser"
        mock_user.first_name = "New"
        mock_update.effective_user = mock_user
        mock_update.message = MagicMock()
        mock_update.message.reply_text = AsyncMock()

        # cmd_start now uses send_card_or_fallback with onboarding_experience.html
        # (IMAGE ONLY rule — no text fallback). Patch to avoid browser dependency.
        with patch("bot.send_card_or_fallback", new=AsyncMock()):
            await bot.cmd_start(mock_update, MagicMock())

        ob = bot._get_ob(20003)
        assert ob["step"] == "experience"

    async def test_onboarding_done_saves_experience(self, test_db):
        bot._onboarding_state.clear()
        user_id = 20004
        await db.upsert_user(user_id, "tester", "Tester")

        ob = bot._get_ob(user_id)
        ob["experience"] = "newbie"
        ob["selected_sports"] = ["soccer"]

        ob["favourites"] = {}
        ob["risk"] = "conservative"
        ob["notify_hour"] = 7

        query = _make_query(user_id=user_id)
        mock_ctx = MagicMock()
        mock_ctx.bot = MagicMock()
        mock_ctx.bot.send_message = AsyncMock()
        await bot.handle_ob_done(query, mock_ctx)

        user = await db.get_user(user_id)
        assert user.experience_level == "newbie"
        assert user.onboarding_done is True

    async def test_onboarding_done_experienced_mentions_value(self, test_db):
        """Experienced users get the done card whose text_fallback mentions value bets."""
        bot._onboarding_state.clear()
        user_id = 20005
        await db.upsert_user(user_id, "pro", "Pro")

        ob = bot._get_ob(user_id)
        ob["experience"] = "experienced"
        ob["selected_sports"] = ["soccer"]

        ob["favourites"] = {}
        ob["risk"] = "aggressive"
        ob["notify_hour"] = 18

        query = _make_query(user_id=user_id)
        mock_ctx = MagicMock()
        mock_ctx.bot = MagicMock()
        mock_ctx.bot.send_message = AsyncMock()
        mock_scf = AsyncMock()
        # handle_ob_done now uses send_card_or_fallback — not edit_message_text
        with patch("bot.send_card_or_fallback", new=mock_scf):
            await bot.handle_ob_done(query, mock_ctx)

        mock_scf.assert_called_once()
        text_fb = mock_scf.call_args.kwargs.get("text_fallback", "")
        assert "value" in text_fb.lower()

    async def test_onboarding_done_newbie_shows_lesson(self, test_db):
        """Newbie users complete onboarding and get the done card (lesson screen removed)."""
        bot._onboarding_state.clear()
        user_id = 20006
        await db.upsert_user(user_id, "noob", "Noob")

        ob = bot._get_ob(user_id)
        ob["experience"] = "newbie"
        ob["selected_sports"] = ["soccer"]

        ob["favourites"] = {}
        ob["risk"] = "conservative"
        ob["notify_hour"] = 7

        query = _make_query(user_id=user_id)
        mock_ctx = MagicMock()
        mock_ctx.bot = MagicMock()
        mock_ctx.bot.send_message = AsyncMock()
        # The newbie lesson screen was removed; all users get the same done card.
        with patch("bot.send_card_or_fallback", new=AsyncMock()):
            await bot.handle_ob_done(query, mock_ctx)

        user = await db.get_user(user_id)
        assert user.onboarding_done is True


class TestDBExperience:
    async def test_update_user_experience(self, test_db):
        await db.upsert_user(30001, "exp_tester", "ExpTester")
        await db.update_user_experience(30001, "experienced")
        user = await db.get_user(30001)
        assert user.experience_level == "experienced"

    async def test_experience_default_none(self, test_db):
        await db.upsert_user(30002, "default_tester", "DefaultTester")
        user = await db.get_user(30002)
        assert user.experience_level is None

    async def test_education_stage_default(self, test_db):
        await db.upsert_user(30003, "edu_tester", "EduTester")
        user = await db.get_user(30003)
        assert user.education_stage == 0


class TestDBResetProfile:
    async def test_reset_clears_preferences(self, test_db):
        user_id = 30010
        await db.upsert_user(user_id, "resetter", "Resetter")
        await db.update_user_risk(user_id, "aggressive")
        await db.update_user_notification_hour(user_id, 21)
        await db.update_user_experience(user_id, "experienced")
        await db.set_onboarding_done(user_id)
        await db.save_sport_pref(user_id, "soccer", league="epl", team_name="Arsenal")

        await db.reset_user_profile(user_id)

        user = await db.get_user(user_id)
        assert user.onboarding_done is False
        assert user.risk_profile is None
        assert user.notification_hour is None
        assert user.experience_level is None
        assert user.education_stage == 0

        prefs = await db.get_user_sport_prefs(user_id)
        assert len(prefs) == 0


# ── Priority 2: Persistent Menu System ──────────────────────

class TestPersistentMenu:
    def test_kb_main_matches_premium_working_layout(self):
        kb = bot.kb_main()
        rows = [[btn.text for btn in row] for row in kb.inline_keyboard]
        # FIX-HIDE-EDGE-TRACKER-P0-01: 📊 Edge Tracker button removed pre-launch.
        assert rows == [
            ["💎 Edge Picks"],
            ["⚽ My Matches"],
            ["📖 Guide", "⚙️ Settings"],
            ["🏠 Community"],
        ]

    def test_kb_main_drops_retired_inline_surfaces(self):
        kb = bot.kb_main()
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "💰 My Bets" not in labels
        assert "🏟️ My Teams" not in labels
        assert "📈 Stats" not in labels
        assert "🎰 Bookmakers" not in labels

    def test_kb_main_has_settings(self):
        kb = bot.kb_main()
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("Settings" in l for l in labels)

    def test_kb_main_max_2_per_row(self):
        kb = bot.kb_main()
        for row in kb.inline_keyboard:
            assert len(row) <= 2

    def test_kb_nav_has_back_and_home(self):
        kb = bot.kb_nav()
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("Back" in l for l in labels)
        assert any("Main Menu" in l for l in labels)

    def test_kb_teams_has_navigation(self):
        kb = bot.kb_teams()
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "settings:home" in callbacks
        assert "menu:home" in callbacks

    def test_kb_bookmakers_has_navigation(self):
        kb = bot.kb_bookmakers()
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "menu:home" in callbacks

    def test_kb_settings_has_navigation(self):
        kb = bot.kb_settings()
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "menu:home" in callbacks

    def test_all_sub_menus_max_2_per_row(self):
        for kb_fn in (bot.kb_teams, bot.kb_bookmakers, bot.kb_settings):
            kb = kb_fn()
            for row in kb.inline_keyboard:
                assert len(row) <= 2, f"{kb_fn.__name__} has row with {len(row)} buttons"


class TestMenuHandlers:
    async def test_dispatch_button_routes_stale_bets_to_main_menu(self, test_db):
        # "bets" prefix was removed. Stale callbacks now show "Unknown action." with a Menu button.
        query = _make_query(user_id=40000)
        await bot._dispatch_button(query, MagicMock(), "bets", "history")
        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert text == "Unknown action."
        markup = call_args[1]["reply_markup"]
        labels = [btn.text for row in markup.inline_keyboard for btn in row]
        assert any("Menu" in l for l in labels)

    async def test_handle_bets_redirects_stale_callbacks_to_main_menu(self, test_db):
        # handle_bets was removed; stale "bets:active" callback now shows "Unknown action."
        query = _make_query(user_id=40001)
        await bot._dispatch_button(query, MagicMock(), "bets", "active")
        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert text == "Unknown action."

    async def test_handle_teams_view_no_teams(self, test_db):
        await db.upsert_user(40002, "no_teams", "NoTeams")
        query = _make_query(user_id=40002)
        await bot.handle_teams(query, "view")
        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "My Teams" in text

    async def test_handle_teams_view_with_teams(self, test_db):
        await db.upsert_user(40003, "team_fan", "TeamFan")
        await db.save_sport_pref(40003, "soccer", team_name="Arsenal")
        query = _make_query(user_id=40003)
        await bot.handle_teams(query, "view")
        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "Arsenal" in text

    async def test_handle_stats_overview_redirects_to_edge_tracker(self, test_db):
        # handle_stats_menu removed; stats are now served via results:7 (Edge Tracker).
        # Patch _serve_response to avoid photo/text message-type detection in test.
        query = _make_query(user_id=40004)
        markup = MagicMock()
        mock_serve = AsyncMock()
        with patch.object(bot, "_render_results_surface", new=AsyncMock(return_value=("EDGE TRACKER", markup))), \
             patch.object(bot, "_serve_response", new=mock_serve):
            await bot._dispatch_button(query, MagicMock(), "results", "7")
        mock_serve.assert_called_once()
        assert mock_serve.call_args[0][1] == "EDGE TRACKER"
        assert mock_serve.call_args[0][2] is markup

    async def test_dispatch_button_routes_stale_stats_to_edge_tracker(self, test_db):
        # "stats" prefix removed; use "results" prefix for Edge Tracker.
        query = _make_query(user_id=40008)
        markup = MagicMock()
        mock_serve = AsyncMock()
        with patch.object(bot, "_render_results_surface", new=AsyncMock(return_value=("EDGE TRACKER", markup))), \
             patch.object(bot, "_serve_response", new=mock_serve):
            await bot._dispatch_button(query, MagicMock(), "results", "30")
        mock_serve.assert_called_once()
        assert mock_serve.call_args[0][1] == "EDGE TRACKER"
        assert mock_serve.call_args[0][2] is markup

    async def test_legacy_my_stats_keyboard_tap_redirects_to_edge_tracker(self, test_db):
        user_id = 40009
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "📊 My Stats"
        update.message.reply_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.id = user_id
        update.effective_chat = MagicMock()
        update.effective_chat.id = user_id
        markup = MagicMock()

        with patch.object(bot.db, "update_last_active", new=AsyncMock()), \
             patch.object(bot.db, "get_user", new=AsyncMock(return_value=SimpleNamespace(onboarding_done=True))), \
             patch.object(bot, "_render_results_surface", new=AsyncMock(return_value=("EDGE TRACKER", markup))):
            await bot.handle_keyboard_tap(update, MagicMock())

        call_args = update.message.reply_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert text == "EDGE TRACKER"
        assert call_args[1]["reply_markup"] is markup

    async def test_handle_affiliate_sa(self, test_db):
        query = _make_query(user_id=40005)
        await bot.handle_affiliate(query, "sa")
        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        # Multi-bookmaker directory (Wave 15B)
        assert "SA Bookmakers" in text
        assert "Betway" in text
        assert "Hollywoodbets" in text
        assert "GBets" in text

    async def test_handle_affiliate_intl(self, test_db):
        """Intl action now shows the same multi-bookmaker directory."""
        query = _make_query(user_id=40006)
        await bot.handle_affiliate(query, "intl")
        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "SA Bookmakers" in text
        assert "Betway" in text

    async def test_handle_settings_home(self, test_db):
        await db.upsert_user(40007, "settings_user", "SettingsUser")
        await db.update_user_risk(40007, "moderate")
        query = _make_query(user_id=40007)
        await bot.handle_settings(query, "home")
        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "Profile" in text or "Settings" in text
        assert "Risk" in text or "risk" in text

    async def test_handle_settings_notify_is_consolidated(self, test_db):
        # FIX-NOTIFICATIONS-DISABLE-01: notifications page disabled — redirects to settings home.
        user_id = 40070
        await db.upsert_user(user_id, "notify_user", "NotifyUser")
        await db.update_user_notification_hour(user_id, 18)
        query = _make_query(user_id=user_id)

        await bot.handle_settings(query, "notify")

        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "Settings" in text
        # Settings nav options from kb_settings() are preserved in the home redirect
        callbacks = [
            btn.callback_data
            for row in call_args[1]["reply_markup"].inline_keyboard
            for btn in row
        ]
        assert "settings:sports" in callbacks

    async def test_handle_settings_sports_renders_inline_editor(self, test_db):
        user_id = 40071
        await db.upsert_user(user_id, "sports_user", "SportsUser")
        await db.save_sport_pref(user_id, "soccer", league="epl", team_name="Arsenal")
        query = _make_query(user_id=user_id)
        bot._settings_sports_state.clear()

        await bot.handle_settings(query, "sports")

        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "My Sports" in text
        assert "redo onboarding" not in text
        callbacks = [
            btn.callback_data
            for row in call_args[1]["reply_markup"].inline_keyboard
            for btn in row
        ]
        assert "settings:toggle_sport:soccer" in callbacks
        assert "settings:sports_done" in callbacks
        assert "settings:edit_teams:soccer" in callbacks

    async def test_handle_settings_sports_done_filters_selected_sports(self, test_db):
        user_id = 40072
        await db.upsert_user(user_id, "sports_done", "SportsDone")
        await db.save_sport_pref(user_id, "soccer", league="epl", team_name="Arsenal")
        await db.save_sport_pref(user_id, "rugby", league="urc", team_name="Bulls")
        query = _make_query(user_id=user_id)
        bot._settings_sports_state.clear()
        bot._team_edit_state.clear()

        await bot.handle_settings(query, "sports")
        await bot.handle_settings(query, "toggle_sport:rugby")
        await bot.handle_settings(query, "toggle_sport:cricket")
        await bot.handle_settings(query, "sports_done")

        prefs = await db.get_user_sport_prefs(user_id)
        sport_keys = [pref.sport_key for pref in prefs]
        assert "soccer" in sport_keys
        assert "cricket" in sport_keys
        assert "rugby" not in sport_keys
        assert any(pref.team_name == "Arsenal" for pref in prefs)
        assert any(pref.sport_key == "cricket" and pref.team_name is None for pref in prefs)

    async def test_handle_settings_edit_teams_stays_in_settings_context(self, test_db):
        user_id = 40073
        await db.upsert_user(user_id, "team_edit", "TeamEdit")
        await db.save_sport_pref(user_id, "soccer", league="epl", team_name="Arsenal")
        query = _make_query(user_id=user_id)
        bot._settings_sports_state.clear()

        await bot.handle_settings(query, "sports")
        await bot.handle_settings(query, "edit_teams:soccer")

        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "Arsenal" in text
        callbacks = [
            btn.callback_data
            for row in call_args[1]["reply_markup"].inline_keyboard
            for btn in row
        ]
        assert "settings:edit_league:soccer:epl" in callbacks
        assert "settings:sports" in callbacks

    async def test_handle_settings_home_discards_unsaved_sports_changes(self, test_db):
        user_id = 40074
        await db.upsert_user(user_id, "sports_back", "SportsBack")
        await db.save_sport_pref(user_id, "soccer", league="epl", team_name="Arsenal")
        query = _make_query(user_id=user_id)
        bot._settings_sports_state.clear()

        await bot.handle_settings(query, "sports")
        await db.save_sport_pref(user_id, "cricket", league="sa20", team_name="MI Cape Town")
        await bot.handle_settings(query, "home")

        prefs = await db.get_user_sport_prefs(user_id)
        sport_keys = {pref.sport_key for pref in prefs}
        assert sport_keys == {"soccer"}
        assert all(pref.team_name != "MI Cape Town" for pref in prefs)

    async def test_handle_settings_reset_shows_warning(self, test_db):
        await db.upsert_user(40008, "reset_user", "ResetUser")
        query = _make_query(user_id=40008)
        mock_scf = AsyncMock()
        # handle_settings("reset") uses send_card_or_fallback with onboarding_restart.html
        with patch("bot.send_card_or_fallback", new=mock_scf):
            await bot.handle_settings(query, "reset")
        mock_scf.assert_called_once()
        text = mock_scf.call_args.kwargs.get("text_fallback", "")
        assert "Reset" in text or "reset" in text.lower()
        assert "NOT" in text  # history not deleted

    async def test_handle_settings_reset_confirm(self, test_db):
        user_id = 40009
        await db.upsert_user(user_id, "reset_confirm", "ResetConfirm")
        await db.set_onboarding_done(user_id)
        await db.save_sport_pref(user_id, "soccer", league="epl")

        query = _make_query(user_id=user_id)
        query.message.edit_reply_markup = AsyncMock()
        query.message.edit_media = AsyncMock()
        query.message.photo = [object()]
        mock_gbot = MagicMock()
        mock_gbot.send_message = AsyncMock()
        mock_gbot.send_photo = AsyncMock()
        with (
            patch("bot._g_bot", mock_gbot),
            patch("bot.render_card_sync", return_value=b"png"),
        ):
            await bot.handle_settings(query, "reset:confirm")
        mock_gbot.send_message.assert_not_called()
        mock_gbot.send_photo.assert_not_called()
        query.message.edit_media.assert_awaited_once()
        query.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)

        user = await db.get_user(user_id)
        assert user.onboarding_done is False

        prefs = await db.get_user_sport_prefs(user_id)
        assert len(prefs) == 0

    async def test_handle_settings_reset_confirm_from_non_dm_sends_private_card(self, test_db):
        user_id = 40012
        await db.upsert_user(user_id, "reset_group", "ResetGroup")
        await db.set_onboarding_done(user_id)

        query = _make_query(user_id=user_id)
        query.message.chat_id = -100123
        query.message.edit_reply_markup = AsyncMock()
        query.message.delete = AsyncMock()
        mock_gbot = MagicMock()
        mock_gbot.send_photo = AsyncMock(return_value=MagicMock())
        with (
            patch("bot._g_bot", mock_gbot),
            patch("bot.render_card_sync", return_value=b"png"),
        ):
            await bot.handle_settings(query, "reset:confirm")

        query.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
        query.message.delete.assert_awaited_once()
        mock_gbot.send_photo.assert_awaited_once()
        assert mock_gbot.send_photo.call_args.kwargs.get("chat_id") == user_id
        assert mock_gbot.send_photo.call_args.kwargs.get("photo") == b"png"

    async def test_handle_settings_reset_confirm_edit_media_fail_deletes_prompt_and_sends_card(self, test_db):
        user_id = 40018
        await db.upsert_user(user_id, "reset_edit_fallback", "ResetEditFallback")
        await db.set_onboarding_done(user_id)
        await db.save_sport_pref(user_id, "soccer", league="epl")

        query = _make_query(user_id=user_id)
        query.message.edit_reply_markup = AsyncMock()
        query.message.edit_media = AsyncMock(side_effect=RuntimeError("edit failed"))
        query.message.delete = AsyncMock()
        query.message.photo = [object()]
        mock_gbot = MagicMock()
        mock_gbot.send_photo = AsyncMock(return_value=MagicMock())
        with (
            patch("bot._g_bot", mock_gbot),
            patch("bot.render_card_sync", return_value=b"png"),
        ):
            await bot.handle_settings(query, "reset:confirm")

        query.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
        query.message.edit_media.assert_awaited_once()
        query.message.delete.assert_awaited_once()
        mock_gbot.send_photo.assert_awaited_once()
        user = await db.get_user(user_id)
        assert user.onboarding_done is False
        prefs = await db.get_user_sport_prefs(user_id)
        assert len(prefs) == 0

    async def test_handle_settings_reset_confirm_from_non_dm_disable_fail_aborts_reset(self, test_db):
        user_id = 40013
        await db.upsert_user(user_id, "reset_group_fail", "ResetGroupFail")
        await db.set_onboarding_done(user_id)
        await db.save_sport_pref(user_id, "soccer", league="epl")

        query = _make_query(user_id=user_id)
        query.message.chat_id = -100123
        query.message.edit_reply_markup = AsyncMock(side_effect=RuntimeError("cannot edit"))
        mock_gbot = MagicMock()
        mock_gbot.send_photo = AsyncMock()
        with (
            patch("bot._g_bot", mock_gbot),
            patch("bot.render_card_sync", return_value=b"png"),
        ):
            await bot.handle_settings(query, "reset:confirm")

        query.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
        mock_gbot.send_photo.assert_not_called()
        user = await db.get_user(user_id)
        assert user.onboarding_done is True
        prefs = await db.get_user_sport_prefs(user_id)
        assert len(prefs) == 1

    async def test_handle_settings_reset_confirm_concurrent_double_tap_serialized(self, test_db):
        user_id = 40017
        await db.upsert_user(user_id, "reset_double_tap", "ResetDoubleTap")
        await db.set_onboarding_done(user_id)
        await db.save_sport_pref(user_id, "soccer", league="epl")

        query_one = _make_query(user_id=user_id)
        query_one.message.edit_reply_markup = AsyncMock()
        query_one.message.edit_media = AsyncMock()
        query_one.message.photo = [object()]
        query_two = _make_query(user_id=user_id)
        query_two.message.edit_reply_markup = AsyncMock()
        query_two.message.edit_media = AsyncMock()
        query_two.message.photo = [object()]

        reset_started = asyncio.Event()
        release_reset = asyncio.Event()
        reset_calls = 0

        async def slow_reset(_user_id: int) -> None:
            nonlocal reset_calls
            reset_calls += 1
            reset_started.set()
            await release_reset.wait()

        mock_gbot = MagicMock()
        mock_gbot.send_photo = AsyncMock()
        with (
            patch("bot._g_bot", mock_gbot),
            patch("bot.render_card_sync", return_value=b"png"),
            patch("bot.db.reset_user_profile", new=slow_reset),
        ):
            first = asyncio.create_task(bot.handle_settings(query_one, "reset:confirm"))
            await asyncio.wait_for(reset_started.wait(), timeout=1.0)
            await bot.handle_settings(query_two, "reset:confirm")
            release_reset.set()
            await first

        assert reset_calls == 1
        query_two.answer.assert_awaited_once_with("Reset already in progress.", show_alert=False)
        query_two.message.edit_reply_markup.assert_not_awaited()
        query_one.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)

    async def test_handle_settings_reset_confirm_delivery_exception_leaves_reset_applied(self, test_db):
        user_id = 40014
        await db.upsert_user(user_id, "reset_delivery_fail", "ResetDeliveryFail")
        await db.set_onboarding_done(user_id)
        await db.save_sport_pref(user_id, "soccer", league="epl")

        query = _make_query(user_id=user_id)
        query.message.chat_id = -100123
        query.message.edit_reply_markup = AsyncMock()
        query.message.delete = AsyncMock()
        mock_gbot = MagicMock()
        mock_gbot.send_photo = AsyncMock(side_effect=RuntimeError("blocked"))
        with (
            patch("bot._g_bot", mock_gbot),
            patch("bot.render_card_sync", return_value=b"png"),
        ):
            await bot.handle_settings(query, "reset:confirm")

        query.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
        query.message.delete.assert_awaited_once()
        mock_gbot.send_photo.assert_awaited_once()
        user = await db.get_user(user_id)
        assert user.onboarding_done is False
        prefs = await db.get_user_sport_prefs(user_id)
        assert len(prefs) == 0

    async def test_handle_settings_reset_confirm_reset_fail_does_not_deliver_success_card(self, test_db):
        user_id = 40015
        await db.upsert_user(user_id, "reset_db_fail", "ResetDbFail")
        await db.set_onboarding_done(user_id)
        await db.save_sport_pref(user_id, "soccer", league="epl")

        query = _make_query(user_id=user_id)
        query.message.edit_reply_markup = AsyncMock()
        query.message.edit_media = AsyncMock()
        query.message.photo = [object()]
        mock_gbot = MagicMock()
        mock_gbot.send_photo = AsyncMock()
        with (
            patch("bot._g_bot", mock_gbot),
            patch("bot.render_card_sync", return_value=b"png"),
            patch("bot.db.reset_user_profile", new_callable=AsyncMock, side_effect=RuntimeError("db down")),
        ):
            await bot.handle_settings(query, "reset:confirm")

        query.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
        query.message.edit_media.assert_not_awaited()
        mock_gbot.send_photo.assert_not_called()
        user = await db.get_user(user_id)
        assert user.onboarding_done is True
        prefs = await db.get_user_sport_prefs(user_id)
        assert len(prefs) == 1

    async def test_handle_settings_reset_confirm_partial_reset_fail_restores_profile(self, test_db):
        user_id = 40016
        await db.upsert_user(user_id, "reset_partial_fail", "ResetPartialFail")
        await db.set_onboarding_done(user_id)
        await db.save_sport_pref(user_id, "soccer", league="epl")

        query = _make_query(user_id=user_id)
        query.message.edit_reply_markup = AsyncMock()
        query.message.edit_media = AsyncMock()
        query.message.photo = [object()]
        mock_gbot = MagicMock()
        mock_gbot.send_photo = AsyncMock()
        with (
            patch("bot._g_bot", mock_gbot),
            patch("bot.render_card_sync", return_value=b"png"),
            patch("bot.db.clear_user_sport_prefs", new_callable=AsyncMock, side_effect=RuntimeError("clear failed")),
        ):
            await bot.handle_settings(query, "reset:confirm")

        query.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
        query.message.edit_media.assert_not_awaited()
        mock_gbot.send_photo.assert_not_called()
        user = await db.get_user(user_id)
        assert user.onboarding_done is True
        prefs = await db.get_user_sport_prefs(user_id)
        assert len(prefs) == 1

    async def test_handle_settings_reset_confirm_render_fail_aborts_reset(self, test_db):
        user_id = 40011
        await db.upsert_user(user_id, "reset_render_fail", "ResetFail")
        await db.set_onboarding_done(user_id)
        await db.save_sport_pref(user_id, "soccer", league="epl")

        query = _make_query(user_id=user_id)
        query.message.edit_reply_markup = AsyncMock()
        mock_gbot = MagicMock()
        mock_gbot.send_photo = AsyncMock()
        with (
            patch("bot._g_bot", mock_gbot),
            patch("bot.render_card_sync", side_effect=RuntimeError("render failed")),
        ):
            await bot.handle_settings(query, "reset:confirm")

        query.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
        mock_gbot.send_photo.assert_not_called()
        user = await db.get_user(user_id)
        assert user.onboarding_done is True
        prefs = await db.get_user_sport_prefs(user_id)
        assert len(prefs) == 1

    async def test_handle_ob_restart(self, test_db):
        bot._onboarding_state.clear()
        query = _make_query(user_id=40010)
        mock_scf = AsyncMock()
        # handle_ob_restart uses send_card_or_fallback; text_fallback says "Step 1/5"
        with patch("bot.send_card_or_fallback", new=mock_scf):
            await bot.handle_ob_restart(query)

        ob = bot._get_ob(40010)
        assert ob["step"] == "experience"
        mock_scf.assert_called_once()
        text = mock_scf.call_args.kwargs.get("text_fallback", "")
        assert "Step 1" in text


# ── Priority 3: Experience-Adapted Pick Cards ────────────────

class TestExperiencedPickCard:
    def test_experienced_has_kelly(self):
        card = format_pick_card(SAMPLE_PICK, experience="experienced")
        assert "Kelly" in card
        assert "EV" in card

    def test_experienced_has_ev_percent(self):
        card = format_pick_card(SAMPLE_PICK, experience="experienced")
        assert "3.5%" in card or "+3.5%" in card

    def test_experienced_has_bookmaker(self):
        card = format_pick_card(SAMPLE_PICK, experience="experienced")
        assert "Hollywoodbets" in card

    def test_experienced_bookmaker_display(self):
        card = format_pick_card(SAMPLE_PICK, experience="experienced")
        assert "Hollywoodbets" in card


class TestCasualPickCard:
    def test_casual_has_payout(self):
        card = format_pick_card(SAMPLE_PICK, experience="casual")
        assert "R300" in card
        assert "R690" in card  # 2.30 * 300

    def test_casual_has_stake_hint(self):
        card = format_pick_card(SAMPLE_PICK, experience="casual")
        assert "stake" in card.lower()

    def test_casual_has_edge(self):
        card = format_pick_card(SAMPLE_PICK, experience="casual")
        assert "Edge" in card or "edge" in card

    def test_casual_we_like(self):
        card = format_pick_card(SAMPLE_PICK, experience="casual")
        assert "We like" in card

    def test_casual_no_kelly(self):
        card = format_pick_card(SAMPLE_PICK, experience="casual")
        assert "Kelly" not in card


class TestNewbiePickCard:
    def test_newbie_has_rand_examples(self):
        card = format_pick_card(SAMPLE_PICK, experience="newbie")
        assert "R300" in card

    def test_newbie_has_payout_calc(self):
        card = format_pick_card(SAMPLE_PICK, experience="newbie")
        # 2.30 * 300 = 690
        assert "R690" in card

    def test_newbie_bet_type_draw(self):
        card = format_pick_card(NEWBIE_PICK, experience="newbie")
        assert "Draw" in card
        assert "neither team" in card.lower()

    def test_newbie_bet_type_home(self):
        card = format_pick_card(SAMPLE_PICK, experience="newbie")
        assert "home team" in card.lower()

    def test_newbie_bet_type_away(self):
        away_pick = ValueBet(
            home="Arsenal", away="Chelsea", sport_key="soccer",
            outcome="Chelsea", best_price=3.40, bookmaker="Bet365",
            is_sa_book=False, fair_prob=0.30, ev_pct=2.0,
            kelly_stake=0.02, confidence="🔴 Low",
        )
        card = format_pick_card(away_pick, experience="newbie")
        assert "away team" in card.lower()

    def test_newbie_start_small_advice(self):
        card = format_pick_card(SAMPLE_PICK, experience="newbie")
        assert "Start small" in card or "start small" in card

    def test_newbie_no_kelly(self):
        card = format_pick_card(SAMPLE_PICK, experience="newbie")
        assert "Kelly" not in card

    def test_newbie_confidence_explain(self):
        card = format_pick_card(SAMPLE_PICK, experience="newbie")
        # Medium confidence should have explanation
        assert "value" in card.lower() or "worth" in card.lower()


class TestDefaultExperienceCard:
    def test_default_is_experienced(self):
        """No experience param should default to experienced format."""
        default_card = format_pick_card(SAMPLE_PICK)
        experienced_card = format_pick_card(SAMPLE_PICK, experience="experienced")
        assert default_card == experienced_card


class TestChunkMessage:
    def test_short_message_single_chunk(self):
        chunks = bot._chunk_message("Hello world", 4000)
        assert len(chunks) == 1

    def test_long_message_splits(self):
        text = "\n".join([f"Line {i}" for i in range(500)])
        chunks = bot._chunk_message(text, 200)
        assert len(chunks) > 1
        # Reassembled text should match
        assert "\n".join(chunks) == text

    def test_empty_message(self):
        chunks = bot._chunk_message("", 4000)
        assert len(chunks) == 1
        assert chunks[0] == ""
