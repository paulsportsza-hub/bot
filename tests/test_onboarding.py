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

    def test_get_ob_returns_same_state(self):
        bot._onboarding_state.clear()
        ob1 = bot._get_ob(99999)
        ob1["selected_sports"].append("epl")
        ob2 = bot._get_ob(99999)
        assert ob2["selected_sports"] == ["epl"]


class TestSportSelection:
    async def test_toggle_sport_on(self):
        bot._onboarding_state.clear()
        query = _make_query(user_id=10001)
        await bot.handle_ob_sport(query, "epl")

        ob = bot._get_ob(10001)
        assert "epl" in ob["selected_sports"]
        query.edit_message_text.assert_called_once()

    async def test_toggle_sport_off(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10002)
        ob["selected_sports"] = ["epl", "nba"]

        query = _make_query(user_id=10002)
        await bot.handle_ob_sport(query, "epl")

        assert "epl" not in ob["selected_sports"]
        assert "nba" in ob["selected_sports"]


class TestSportsDone:
    async def test_sports_done_no_selection(self):
        bot._onboarding_state.clear()
        bot._get_ob(10003)  # empty selection

        query = _make_query(user_id=10003)
        await bot.handle_ob_nav(query, "sports_done")

        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "select at least one" in text.lower()

    async def test_sports_done_moves_to_leagues(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10004)
        ob["selected_sports"] = ["epl"]

        query = _make_query(user_id=10004)
        await bot.handle_ob_nav(query, "sports_done")

        assert ob["step"] == "leagues"
        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "Step 3" in text


class TestLeagueSelection:
    async def test_toggle_league(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10005)
        ob["selected_sports"] = ["epl"]
        ob["step"] = "leagues"

        query = _make_query(user_id=10005)
        await bot.handle_ob_league(query, "epl:English Premier League")

        assert "English Premier League" in ob["selected_leagues"]["epl"]

    async def test_league_done_moves_to_teams(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10006)
        ob["selected_sports"] = ["epl"]
        ob["step"] = "leagues"
        ob["_league_idx"] = 0

        query = _make_query(user_id=10006)
        await bot.handle_ob_nav(query, "league_done:epl")

        assert ob["step"] == "teams"


class TestTeamSelection:
    async def test_team_skip(self):
        bot._onboarding_state.clear()
        ob = bot._get_ob(10007)
        ob["selected_sports"] = ["epl"]
        ob["step"] = "teams"
        ob["_team_idx"] = 0

        query = _make_query(user_id=10007)
        await bot.handle_ob_team_skip(query, "epl")

        # After skipping the only sport, should move to risk
        assert ob["step"] == "risk"


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
        ob["selected_sports"] = ["epl"]
        ob["risk"] = "moderate"

        query = _make_query(user_id=10009)
        await bot.handle_ob_notify(query, "18")

        assert ob["notify_hour"] == 18
        assert ob["step"] == "summary"


class TestOnboardingDone:
    async def test_done_persists_to_db(self, test_db):
        bot._onboarding_state.clear()
        user_id = 10010
        await db.upsert_user(user_id, "tester", "Tester")

        ob = bot._get_ob(user_id)
        ob["selected_sports"] = ["epl", "nba"]
        ob["selected_leagues"] = {"epl": ["English Premier League"], "nba": []}
        ob["teams"] = {"epl": "Arsenal"}
        ob["risk"] = "aggressive"
        ob["notify_hour"] = 21

        query = _make_query(user_id=user_id)
        await bot.handle_ob_done(query)

        # Check DB
        user = await db.get_user(user_id)
        assert user.onboarding_done is True
        assert user.risk_profile == "aggressive"
        assert user.notification_hour == 21

        prefs = await db.get_user_sport_prefs(user_id)
        assert len(prefs) >= 2
        epl_prefs = [p for p in prefs if p.sport_key == "epl"]
        assert len(epl_prefs) == 1
        assert epl_prefs[0].team_name == "Arsenal"
        assert epl_prefs[0].league == "English Premier League"

        # State should be cleaned up
        assert user_id not in bot._onboarding_state


class TestKeyboards:
    def test_kb_onboarding_sports_has_sa_header(self):
        kb = bot.kb_onboarding_sports()
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("South African" in t for t in texts)

    def test_kb_onboarding_sports_has_global_header(self):
        kb = bot.kb_onboarding_sports()
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("Global" in t for t in texts)

    def test_kb_onboarding_sports_shows_done_when_selected(self):
        kb = bot.kb_onboarding_sports(selected=["epl"])
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("Done" in t for t in texts)

    def test_kb_onboarding_sports_no_done_when_empty(self):
        kb = bot.kb_onboarding_sports(selected=[])
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert not any("Done" in t for t in texts)

    def test_kb_onboarding_risk(self):
        kb = bot.kb_onboarding_risk()
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert len(texts) == 3

    def test_kb_onboarding_notify(self):
        kb = bot.kb_onboarding_notify()
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert len(texts) == 4
