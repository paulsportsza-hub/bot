"""Tests for Day 1 features: experience onboarding, persistent menu, adapted pick cards."""

from __future__ import annotations

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
        await bot.handle_ob_experience(query, "casual")

        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "Step 2/5" in text
        assert "sports" in text.lower()

    async def test_cmd_start_shows_experience_first(self, test_db):
        mock_update = MagicMock()
        mock_user = MagicMock()
        mock_user.id = 20003
        mock_user.username = "newuser"
        mock_user.first_name = "New"
        mock_update.effective_user = mock_user
        mock_update.message = MagicMock()
        mock_update.message.reply_text = AsyncMock()

        await bot.cmd_start(mock_update, MagicMock())

        call_args = mock_update.message.reply_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "Step 1/5" in text
        assert "experience" in text.lower()

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
        """Experienced users should get a message mentioning value bets."""
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
        with patch("bot._do_picks_flow", new_callable=AsyncMock):
            await bot.handle_ob_done(query, mock_ctx)

        call_args = query.edit_message_text.call_args_list[0]
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "value" in text.lower()

    async def test_onboarding_done_newbie_shows_lesson(self, test_db):
        """Newbie users should get a mini-lesson about odds."""
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
        await bot.handle_ob_done(query, mock_ctx)

        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "Lesson" in text or "odds" in text.lower()


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
    def test_kb_main_has_your_games_and_hot_tips(self):
        kb = bot.kb_main()
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        labels = [b.text for b in buttons]
        assert any("My Matches" in l for l in labels)
        assert any("Top Edge Picks" in l for l in labels)

    def test_kb_main_has_my_bets(self):
        kb = bot.kb_main()
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("My Bets" in l for l in labels)

    def test_kb_main_has_my_teams(self):
        kb = bot.kb_main()
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("My Teams" in l for l in labels)

    def test_kb_main_has_stats(self):
        kb = bot.kb_main()
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("Stats" in l for l in labels)

    def test_kb_main_has_bookmakers(self):
        kb = bot.kb_main()
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("Bookmakers" in l for l in labels)

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

    def test_kb_bets_has_navigation(self):
        kb = bot.kb_bets()
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "menu:home" in callbacks

    def test_kb_teams_has_navigation(self):
        kb = bot.kb_teams()
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "menu:home" in callbacks

    def test_kb_stats_has_navigation(self):
        kb = bot.kb_stats()
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
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
        for kb_fn in (bot.kb_bets, bot.kb_teams, bot.kb_stats, bot.kb_bookmakers, bot.kb_settings):
            kb = kb_fn()
            for row in kb.inline_keyboard:
                assert len(row) <= 2, f"{kb_fn.__name__} has row with {len(row)} buttons"


class TestMenuHandlers:
    async def test_handle_bets_active(self, test_db):
        query = _make_query(user_id=40001)
        await bot.handle_bets(query, "active")
        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "My Bets" in text

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

    async def test_handle_stats_overview(self, test_db):
        query = _make_query(user_id=40004)
        await bot.handle_stats_menu(query, "overview")
        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "Stats" in text

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

    async def test_handle_settings_reset_shows_warning(self, test_db):
        await db.upsert_user(40008, "reset_user", "ResetUser")
        query = _make_query(user_id=40008)
        await bot.handle_settings(query, "reset")
        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "Reset" in text
        assert "NOT" in text  # history not deleted

    async def test_handle_settings_reset_confirm(self, test_db):
        user_id = 40009
        await db.upsert_user(user_id, "reset_confirm", "ResetConfirm")
        await db.set_onboarding_done(user_id)
        await db.save_sport_pref(user_id, "soccer", league="epl")

        query = _make_query(user_id=user_id)
        await bot.handle_settings(query, "reset:confirm")

        user = await db.get_user(user_id)
        assert user.onboarding_done is False

        prefs = await db.get_user_sport_prefs(user_id)
        assert len(prefs) == 0

    async def test_handle_ob_restart(self, test_db):
        bot._onboarding_state.clear()
        query = _make_query(user_id=40010)
        await bot.handle_ob_restart(query)

        ob = bot._get_ob(40010)
        assert ob["step"] == "experience"
        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "Step 1/5" in text


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
        assert "R100" in card
        assert "R230" in card  # 2.30 * 100

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
        assert "R20" in card
        assert "R50" in card

    def test_newbie_has_payout_calc(self):
        card = format_pick_card(SAMPLE_PICK, experience="newbie")
        # 2.30 * 20 = 46
        assert "R46" in card
        # 2.30 * 50 = 115
        assert "R115" in card

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
