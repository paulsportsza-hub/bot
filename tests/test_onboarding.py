"""Tests for the onboarding quiz flow state machine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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

    def test_no_league_keys_in_state(self):
        """Phase 0D: onboarding state should not have league-related keys."""
        bot._onboarding_state.clear()
        ob = bot._get_ob(99999)
        assert "selected_leagues" not in ob
        assert "_league_idx" not in ob
        assert "_team_input_league" not in ob
        assert "_fav_league_queue" not in ob


class TestSportSelection:
    async def test_toggle_sport_on(self):
        bot._onboarding_state.clear()
        query = _make_query(user_id=10001)
        with patch("bot.send_card_or_fallback", new_callable=AsyncMock):
            await bot.handle_ob_sport(query, "soccer")

        ob = bot._get_ob(10001)
        assert "soccer" in ob["selected_sports"]

    async def test_toggle_sport_off(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10002)
        ob["selected_sports"] = ["soccer", "combat"]

        query = _make_query(user_id=10002)
        await bot.handle_ob_sport(query, "soccer")

        assert "soccer" not in ob["selected_sports"]
        assert "combat" in ob["selected_sports"]


class TestSportsDone:
    async def test_sports_done_no_selection(self):
        bot._onboarding_state.clear()
        bot._get_ob(10003)  # empty selection

        query = _make_query(user_id=10003)
        await bot.handle_ob_nav(query, "sports_done")

        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "select at least one" in text.lower()

    async def test_sports_done_goes_to_teams(self):
        """Phase 0D: sports_done should go directly to favourites (teams), not leagues."""
        bot._onboarding_state.clear()
        ob = bot._get_ob(10004)
        ob["selected_sports"] = ["soccer"]

        query = _make_query(user_id=10004)
        with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
            await bot.handle_ob_nav(query, "sports_done")

        assert ob["step"] == "favourites"
        mock_card.assert_called_once()
        text_fb = mock_card.call_args.kwargs.get("text_fallback", "")
        assert "Step 3" in text_fb

    async def test_sports_done_combat_goes_to_teams(self):
        """Phase 0D: combat sports should go to team prompt, not league selection."""
        bot._onboarding_state.clear()
        ob = bot._get_ob(10014)
        ob["selected_sports"] = ["combat"]

        query = _make_query(user_id=10014)
        await bot.handle_ob_nav(query, "sports_done")

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
        ob["selected_sports"] = ["combat"]  # only 1 sport
        ob["step"] = "favourites"
        ob["_fav_idx"] = 0

        query = _make_query(user_id=10018)
        await bot.handle_ob_fav_done(query, "combat")

        # Should move to edge explainer after the only sport (then risk)
        assert ob["step"] == "edge_explainer"


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
        match, suggestions = bot.fuzzy_match_team("dricus", "combat")
        assert match == "Dricus Du Plessis"

    def test_combat_alias(self):
        match, suggestions = bot.fuzzy_match_team("canelo", "combat")
        assert match == "Canelo Alvarez"


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
    @pytest.mark.skip(reason="handle_ob_risk removed (BUILD-SETTINGS-CLEANUP-01)")
    async def test_risk_sets_profile(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10008)
        ob["step"] = "risk"

        query = _make_query(user_id=10008)
        await bot.handle_ob_risk(query, "moderate")

        assert ob["risk"] == "moderate"
        assert ob["step"] == "bankroll"


class TestNotifySelection:
    async def test_notify_sets_hour(self):
        pytest.skip("handle_ob_notify removed in FIX-ONBOARDING-OB-NAV-01")


class TestPreferencesCombinedStep:
    @pytest.mark.skip(reason="handle_ob_risk removed (BUILD-SETTINGS-CLEANUP-01)")
    async def test_risk_goes_to_bankroll(self):
        """Phase 0D: Risk should show Step 4/5 and go to bankroll."""
        bot._onboarding_state.clear()
        ob = bot._get_ob(10050)
        ob["step"] = "risk"

        query = _make_query(user_id=10050)
        with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
            await bot.handle_ob_risk(query, "moderate")

        assert ob["step"] == "bankroll"
        mock_card.assert_called_once()
        text_fb = mock_card.call_args.kwargs.get("text_fallback", "")
        assert "Step 4/5" in text_fb

    async def test_no_league_step(self):
        """Phase 0D: sports_done goes to favourites, not leagues."""
        bot._onboarding_state.clear()
        ob = bot._get_ob(10051)
        ob["selected_sports"] = ["soccer"]

        query = _make_query(user_id=10051)
        await bot.handle_ob_nav(query, "sports_done")

        assert ob["step"] == "favourites"
        # Should NOT be "leagues"
        assert ob["step"] != "leagues"


class TestSummaryAndEdit:
    async def test_summary_shows_sports(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10023)
        ob["selected_sports"] = ["soccer"]
        ob["favourites"] = {"soccer": ["Arsenal"]}
        ob["risk"] = "moderate"
        ob["notify_hour"] = 18

        query = _make_query(user_id=10023)
        with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
            await bot._show_summary(query, ob)

        mock_card.assert_called_once()
        text_fb = mock_card.call_args.kwargs.get("text_fallback", "")
        assert "Step 4/5" in text_fb
        assert "Arsenal" in text_fb
        kb = mock_card.call_args.kwargs.get("markup")
        btn_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("Edit Sports & Teams" in t for t in btn_texts)
        assert any("Choose Plan" in t or "Next" in t for t in btn_texts)

    async def test_edit_sports_shows_list(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10024)
        ob["selected_sports"] = ["soccer", "combat"]

        query = _make_query(user_id=10024)
        await bot.handle_ob_edit(query, "sports")

        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "Edit which sport" in text

    @pytest.mark.skip(reason="ob_edit:risk removed (BUILD-SETTINGS-CLEANUP-01)")
    async def test_edit_risk_shows_risk_kb(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10025)
        ob["step"] = "summary"

        query = _make_query(user_id=10025)
        with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
            await bot.handle_ob_edit(query, "risk")

        assert ob["_editing"] == "risk"
        mock_card.assert_called_once()
        text_fb = mock_card.call_args.kwargs.get("text_fallback", "")
        assert "Risk" in text_fb

    async def test_back_to_summary(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10026)
        ob["_editing"] = "sports"
        ob["step"] = "favourites"
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
        ob["selected_sports"] = ["soccer", "combat"]
        ob["favourites"] = {"soccer": ["Arsenal"]}
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
        assert len(soccer_prefs) >= 1
        assert any(p.team_name == "Arsenal" for p in soccer_prefs)
        # Arsenal should be auto-inferred to epl league
        arsenal_prefs = [p for p in soccer_prefs if p.team_name == "Arsenal"]
        assert arsenal_prefs[0].league == "epl"

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

    @pytest.mark.skip(reason="kb_onboarding_risk removed (BUILD-SETTINGS-CLEANUP-01)")
    def test_kb_onboarding_risk(self):
        kb = bot.kb_onboarding_risk()
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert len(texts) == 5  # 3 risk options + back + start again
        assert any("↩️" in t for t in texts)

    def test_kb_onboarding_notify(self):
        pytest.skip("kb_onboarding_notify removed in FIX-ONBOARDING-OB-NAV-01")

    def test_kb_settings_has_reset(self):
        kb = bot.kb_settings()
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "settings:reset" in callbacks

    @pytest.mark.skip(reason="kb_onboarding_risk removed (BUILD-SETTINGS-CLEANUP-01)")
    def test_kb_onboarding_risk_has_start_again(self):
        """Risk keyboard has Start Again button."""
        kb = bot.kb_onboarding_risk()
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("Start Again" in t for t in texts)
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "ob_nav:restart" in callbacks

    def test_kb_onboarding_notify_has_start_again(self):
        pytest.skip("kb_onboarding_notify removed in FIX-ONBOARDING-OB-NAV-01")

    @pytest.mark.skip(reason="kb_onboarding_bankroll removed (BUILD-SETTINGS-CLEANUP-01)")
    def test_kb_onboarding_bankroll_has_start_again(self):
        """Bankroll keyboard has Start Again button."""
        kb = bot.kb_onboarding_bankroll()
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("Start Again" in t for t in texts)

    @pytest.mark.skip(reason="Alert Preferences button removed from kb_settings (BUILD-SETTINGS-CLEANUP-01)")
    def test_kb_settings_has_single_notifications_entry(self):
        """Settings keyboard exposes one consolidated alert preferences entry."""
        kb = bot.kb_settings()
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert texts.count("📊 Alert Preferences") == 1
        assert not any("Notifications" in t for t in texts)
        assert not any("🔔" in t for t in texts)
