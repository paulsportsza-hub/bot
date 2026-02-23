"""Tests for the onboarding quiz flow state machine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import bot
import config
import db


pytestmark = pytest.mark.asyncio


def _make_query(user_id: int = 55555, data: str = "") -> MagicMock:
    query = MagicMock()
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.from_user = MagicMock()
    query.from_user.id = user_id
    query.from_user.first_name = "Tester"
    query.from_user.username = "tester"
    query.data = data
    return query


class TestOnboardingState:
    def test_get_ob_creates_fresh_state(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(99999)
        assert ob["step"] == "experience"
        assert ob["experience"] is None
        assert ob["selected_sports"] == []
        assert ob["favourites"] == {}

    def test_get_ob_returns_same_state(self):
        bot._onboarding_state.clear()
        ob1 = bot._get_ob(99999)
        ob1["selected_sports"].append("soccer")
        ob2 = bot._get_ob(99999)
        assert ob2["selected_sports"] == ["soccer"]


class TestSportSelection:
    async def test_toggle_sport_on(self):
        bot._onboarding_state.clear()
        query = _make_query(user_id=10001)
        await bot.handle_ob_sport(query, "soccer")

        ob = bot._get_ob(10001)
        assert "soccer" in ob["selected_sports"]
        query.edit_message_text.assert_called_once()

    async def test_toggle_sport_off(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10002)
        ob["selected_sports"] = ["soccer", "basketball"]

        query = _make_query(user_id=10002)
        await bot.handle_ob_sport(query, "soccer")

        assert "soccer" not in ob["selected_sports"]
        assert "basketball" in ob["selected_sports"]


class TestSportsDone:
    async def test_sports_done_no_selection(self):
        bot._onboarding_state.clear()
        bot._get_ob(10003)  # empty selection

        query = _make_query(user_id=10003)
        await bot.handle_ob_nav(query, "sports_done")

        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "select at least one" in text.lower()

    async def test_sports_done_single_league_auto_select(self):
        """Single-league sport should auto-select its league."""
        bot._onboarding_state.clear()
        ob = bot._get_ob(10004)
        ob["selected_sports"] = ["american_football"]  # NFL only

        query = _make_query(user_id=10004)
        await bot.handle_ob_nav(query, "sports_done")

        # Should auto-select NFL and move past leagues
        assert "nfl" in ob["selected_leagues"].get("american_football", [])

    async def test_sports_done_multi_league_shows_selection(self):
        """Multi-league sport should show league selection."""
        bot._onboarding_state.clear()
        ob = bot._get_ob(10014)
        ob["selected_sports"] = ["soccer"]

        query = _make_query(user_id=10014)
        await bot.handle_ob_nav(query, "sports_done")

        assert ob["step"] == "leagues"
        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "Step 3" in text


class TestLeagueSelection:
    async def test_toggle_league(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10005)
        ob["selected_sports"] = ["soccer"]
        ob["step"] = "leagues"

        query = _make_query(user_id=10005)
        await bot.handle_ob_league(query, "soccer:epl")

        assert "epl" in ob["selected_leagues"]["soccer"]

    async def test_toggle_league_off(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10015)
        ob["selected_sports"] = ["soccer"]
        ob["step"] = "leagues"
        ob["selected_leagues"]["soccer"] = ["epl", "la_liga"]

        query = _make_query(user_id=10015)
        await bot.handle_ob_league(query, "soccer:epl")

        assert "epl" not in ob["selected_leagues"]["soccer"]
        assert "la_liga" in ob["selected_leagues"]["soccer"]

    async def test_league_done_advances(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10006)
        ob["selected_sports"] = ["soccer"]
        ob["step"] = "leagues"
        ob["_league_idx"] = 0

        query = _make_query(user_id=10006)
        await bot.handle_ob_nav(query, "league_done:soccer")

        # Should move to favourites since there's only 1 sport
        assert ob["step"] == "favourites"


class TestFavouriteSelection:
    async def test_toggle_favourite_on(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10016)
        ob["selected_sports"] = ["soccer"]
        ob["step"] = "favourites"

        query = _make_query(user_id=10016)
        # Index 0 should be the first team in soccer's combined list
        await bot.handle_ob_fav(query, "soccer:0")

        teams = bot._get_all_teams_for_sport("soccer")
        assert teams[0] in ob["favourites"].get("soccer", [])

    async def test_toggle_favourite_off(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10017)
        ob["selected_sports"] = ["soccer"]
        ob["step"] = "favourites"
        teams = bot._get_all_teams_for_sport("soccer")
        ob["favourites"]["soccer"] = [teams[0]]

        query = _make_query(user_id=10017)
        await bot.handle_ob_fav(query, "soccer:0")

        assert teams[0] not in ob["favourites"].get("soccer", [])

    async def test_fav_done_advances(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10018)
        ob["selected_sports"] = ["american_football"]  # only 1 sport
        ob["step"] = "favourites"
        ob["_fav_idx"] = 0

        query = _make_query(user_id=10018)
        await bot.handle_ob_fav_done(query, "american_football")

        # Should move to risk after the only sport
        assert ob["step"] == "risk"

    async def test_horse_racing_skips_favourites(self):
        """Horse racing (fav_type=skip) should skip favourite step."""
        bot._onboarding_state.clear()
        ob = bot._get_ob(10019)
        ob["selected_sports"] = ["horse_racing"]
        ob["step"] = "favourites"
        ob["_fav_idx"] = 0

        query = _make_query(user_id=10019)
        # Simulate _show_fav_step being called
        await bot._show_fav_step(query, ob)

        # Should skip to risk since horse_racing has fav_type="skip"
        assert ob["step"] == "risk"


class TestFavManualInput:
    async def test_manual_mode_sets_flags(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10020)
        ob["selected_sports"] = ["soccer"]
        ob["step"] = "favourites"

        query = _make_query(user_id=10020)
        await bot.handle_ob_fav_manual(query, "soccer")

        assert ob["_fav_manual"] is True
        assert ob["_fav_manual_sport"] == "soccer"

    async def test_fav_back_clears_manual(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10021)
        ob["selected_sports"] = ["soccer"]
        ob["step"] = "favourites"
        ob["_fav_manual"] = True
        ob["_fav_manual_sport"] = "soccer"

        query = _make_query(user_id=10021)
        await bot.handle_ob_fav_back(query, "soccer")

        assert ob["_fav_manual"] is False
        assert ob["_fav_manual_sport"] is None


class TestFuzzyMatching:
    def test_exact_alias(self):
        match, suggestions = bot.fuzzy_match_team("chiefs", "soccer")
        assert match == "Kaizer Chiefs"
        assert suggestions == []

    def test_case_insensitive_match(self):
        match, suggestions = bot.fuzzy_match_team("ARSENAL", "soccer")
        assert match == "Arsenal"

    def test_partial_match_unique(self):
        match, suggestions = bot.fuzzy_match_team("Mamelodi", "soccer")
        assert match == "Mamelodi Sundowns"

    def test_fuzzy_close_match(self):
        match, suggestions = bot.fuzzy_match_team("Arsnal", "soccer")
        # Should suggest Arsenal
        if match:
            assert match == "Arsenal"
        else:
            assert "Arsenal" in suggestions

    def test_no_match(self):
        match, suggestions = bot.fuzzy_match_team("zzzznotateam", "soccer")
        assert match is None
        assert suggestions == []

    def test_mma_alias(self):
        match, suggestions = bot.fuzzy_match_team("dricus", "mma")
        assert match == "Dricus Du Plessis"

    def test_f1_alias(self):
        match, suggestions = bot.fuzzy_match_team("max", "motorsport")
        assert match == "Max Verstappen"


class TestFavSuggestHandler:
    async def test_accept_suggestion(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10022)
        ob["selected_sports"] = ["soccer"]
        ob["step"] = "favourites"
        ob["_suggestions"] = ["Arsenal", "Aston Villa"]

        query = _make_query(user_id=10022)
        await bot.handle_ob_fav_suggest(query, "soccer:0")

        assert "Arsenal" in ob["favourites"].get("soccer", [])
        assert ob["_suggestions"] == []


class TestRiskSelection:
    async def test_risk_sets_profile(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10008)
        ob["step"] = "risk"

        query = _make_query(user_id=10008)
        await bot.handle_ob_risk(query, "moderate")

        assert ob["risk"] == "moderate"
        assert ob["step"] == "notify"


class TestNotifySelection:
    async def test_notify_sets_hour(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10009)
        ob["step"] = "notify"
        ob["selected_sports"] = ["soccer"]
        ob["risk"] = "moderate"

        query = _make_query(user_id=10009)
        await bot.handle_ob_notify(query, "18")

        assert ob["notify_hour"] == 18
        assert ob["step"] == "summary"


class TestSummaryAndEdit:
    async def test_summary_shows_sports(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10023)
        ob["selected_sports"] = ["soccer"]
        ob["selected_leagues"] = {"soccer": ["epl"]}
        ob["favourites"] = {"soccer": {"epl": ["Arsenal"]}}
        ob["risk"] = "moderate"
        ob["notify_hour"] = 18

        query = _make_query(user_id=10023)
        await bot._show_summary(query, ob)

        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "Step 7/7" in text
        assert "Arsenal" in text
        # Edit buttons are in the keyboard markup
        kb = call_args[1].get("reply_markup")
        btn_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("Edit Sports" in t for t in btn_texts)
        assert any("Edit Risk" in t for t in btn_texts)

    async def test_edit_sports_shows_list(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10024)
        ob["selected_sports"] = ["soccer", "basketball"]

        query = _make_query(user_id=10024)
        await bot.handle_ob_edit(query, "sports")

        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "Edit which sport" in text

    async def test_edit_risk_shows_risk_kb(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10025)
        ob["step"] = "summary"

        query = _make_query(user_id=10025)
        await bot.handle_ob_edit(query, "risk")

        assert ob["_editing"] == "risk"
        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "Risk" in text

    async def test_back_to_summary(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10026)
        ob["_editing"] = "sports"
        ob["step"] = "leagues"
        ob["selected_sports"] = ["soccer"]
        ob["risk"] = "moderate"
        ob["notify_hour"] = 18

        query = _make_query(user_id=10026)
        await bot.handle_ob_summary(query, "show")

        assert ob["_editing"] is None
        assert ob["step"] == "summary"


class TestOnboardingDone:
    async def test_done_persists_to_db(self, test_db):
        bot._onboarding_state.clear()
        user_id = 10010
        await db.upsert_user(user_id, "tester", "Tester")

        ob = bot._get_ob(user_id)
        ob["selected_sports"] = ["soccer", "basketball"]
        ob["selected_leagues"] = {"soccer": ["epl"], "basketball": ["nba"]}
        ob["favourites"] = {"soccer": {"epl": ["Arsenal"]}}
        ob["risk"] = "aggressive"
        ob["notify_hour"] = 21

        query = _make_query(user_id=user_id)
        mock_ctx = MagicMock()
        mock_ctx.bot = MagicMock()
        mock_ctx.bot.send_message = AsyncMock()
        await bot.handle_ob_done(query, mock_ctx)

        # Check DB
        user = await db.get_user(user_id)
        assert user.onboarding_done is True
        assert user.risk_profile == "aggressive"
        assert user.notification_hour == 21

        prefs = await db.get_user_sport_prefs(user_id)
        assert len(prefs) >= 2
        soccer_prefs = [p for p in prefs if p.sport_key == "soccer" and p.team_name]
        assert len(soccer_prefs) == 1
        assert soccer_prefs[0].team_name == "Arsenal"
        assert soccer_prefs[0].league == "epl"

        # State should be cleaned up
        assert user_id not in bot._onboarding_state


class TestKeyboards:
    def test_kb_onboarding_sports_has_categories(self):
        kb = bot.kb_onboarding_sports()
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("Soccer" in t for t in texts)
        assert any("Rugby" in t for t in texts)

    def test_kb_onboarding_sports_shows_done_when_selected(self):
        kb = bot.kb_onboarding_sports(selected=["soccer"])
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("Done" in t for t in texts)

    def test_kb_onboarding_sports_no_done_when_empty(self):
        kb = bot.kb_onboarding_sports(selected=[])
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert not any("Done" in t for t in texts)

    def test_kb_onboarding_sports_max_2_per_row(self):
        kb = bot.kb_onboarding_sports()
        for row in kb.inline_keyboard:
            # Done button row has 1
            assert len(row) <= 2

    def test_kb_onboarding_leagues_has_back_next(self):
        kb = bot.kb_onboarding_leagues("soccer")
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert any("back_sports" in c for c in callbacks)
        assert any("league_done" in c for c in callbacks)

    def test_kb_onboarding_favourites_has_manual(self):
        kb = bot.kb_onboarding_favourites("soccer")
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert any("ob_fav_manual" in c for c in callbacks)

    def test_kb_onboarding_favourites_has_skip(self):
        kb = bot.kb_onboarding_favourites("soccer")
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("Skip" in t for t in texts)

    def test_kb_onboarding_favourites_shows_next_when_selected(self):
        kb = bot.kb_onboarding_favourites("soccer", selected=["Arsenal"])
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("Next" in t for t in texts)

    def test_kb_onboarding_risk(self):
        kb = bot.kb_onboarding_risk()
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert len(texts) == 3

    def test_kb_onboarding_notify(self):
        kb = bot.kb_onboarding_notify()
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert len(texts) == 4

    def test_kb_settings_has_reset(self):
        kb = bot.kb_settings()
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "settings:reset" in callbacks
