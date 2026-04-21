"""Settings and onboarding journey coverage."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import bot
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
    query.message.chat.send_message = AsyncMock()
    query.message.chat_id = user_id
    return query


async def test_start_new_user_triggers_onboarding(
    test_db, mock_update, mock_context
) -> None:
    user = MagicMock()
    user.id = 41001
    user.username = "newbie"
    user.first_name = "Newbie"
    mock_update.effective_user = user

    with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
        await bot.cmd_start(mock_update, mock_context)

    # Two card sends: welcome card then experience card
    assert mock_card.call_count == 2
    templates = [c.kwargs.get("template") or c.args[2] for c in mock_card.call_args_list]
    assert "onboarding_welcome.html" in templates
    assert "onboarding_experience.html" in templates


async def test_start_returning_user_reopens_main_flow(
    test_db, mock_update, mock_context
) -> None:
    await db.upsert_user(41002, "returning", "Returning")
    await db.set_onboarding_done(41002)
    user = MagicMock()
    user.id = 41002
    user.username = "returning"
    user.first_name = "Returning"
    mock_update.effective_user = user

    await bot.cmd_start(mock_update, mock_context)

    text = mock_update.message.reply_text.call_args.args[0]
    assert "Welcome back" in text


async def test_onboarding_sport_toggle_collects_preferences() -> None:
    bot._onboarding_state.clear()
    query = _make_query(user_id=41003)
    await bot.handle_ob_sport(query, "soccer")

    ob = bot._get_ob(41003)
    assert "soccer" in ob["selected_sports"]


async def test_onboarding_team_selection_collects_favourites() -> None:
    bot._onboarding_state.clear()
    ob = bot._get_ob(41004)
    ob["selected_sports"] = ["soccer"]
    ob["step"] = "favourites"
    query = _make_query(user_id=41004)

    await bot.handle_ob_fav(query, "soccer:0")

    assert ob["favourites"]["soccer"]


async def test_onboarding_manual_team_mode_prompts_for_input() -> None:
    bot._onboarding_state.clear()
    ob = bot._get_ob(41005)
    ob["selected_sports"] = ["soccer"]
    ob["step"] = "favourites"
    query = _make_query(user_id=41005)

    with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
        await bot.handle_ob_fav_manual(query, "soccer")

    mock_card.assert_called_once()
    assert mock_card.call_args.kwargs.get("template") == "onboarding_favourites_manual.html"
    # State should be set for manual input mode
    assert ob.get("_fav_manual") is True
    assert ob.get("_fav_manual_sport") == "soccer"


async def test_settings_home_is_accessible(test_db) -> None:
    await db.upsert_user(41006, "settings", "Settings")
    query = _make_query(user_id=41006)

    await bot.handle_settings(query, "home")

    text = query.edit_message_text.call_args.args[0]
    assert "Profile" in text or "Settings" in text


async def test_settings_sports_screen_shows_saved_sport(test_db) -> None:
    await db.upsert_user(41007, "sports", "Sports")
    await db.save_sport_pref(41007, "soccer")
    query = _make_query(user_id=41007)

    await bot.handle_settings(query, "sports")

    text = query.edit_message_text.call_args.args[0]
    assert "My Sports" in text
    assert "Soccer" in text or "football" in text.lower()


async def test_settings_sports_done_persists_selection(test_db) -> None:
    await db.upsert_user(41008, "done", "Done")
    bot._settings_sports_state[41008] = {
        "selected_sports": ["soccer"],
        "original_prefs": [],
    }
    query = _make_query(user_id=41008)

    await bot.handle_settings(query, "sports_done")

    prefs = await db.get_user_sport_prefs(41008)
    assert any(pref.sport_key == "soccer" for pref in prefs)


async def test_notification_toggle_works(test_db) -> None:
    await db.upsert_user(41009, "notify", "Notify")
    query = _make_query(user_id=41009)

    await bot.handle_settings(query, "toggle_notify:daily_picks")

    user = await db.get_user(41009)
    prefs = db.get_notification_prefs(user)
    assert prefs["daily_picks"] is False


async def test_notification_time_setting_works(test_db) -> None:
    await db.upsert_user(41010, "notifyhour", "NotifyHour")
    query = _make_query(user_id=41010)

    await bot.handle_settings(query, "set_notify:18")

    user = await db.get_user(41010)
    assert user.notification_hour == 18


async def test_bankroll_setting_works(test_db) -> None:
    await db.upsert_user(41011, "bankroll", "Bankroll")
    query = _make_query(user_id=41011)

    await bot.handle_settings(query, "set_bankroll:500")

    user = await db.get_user(41011)
    assert user.bankroll == 500


async def test_my_teams_editor_lists_saved_team_counts(test_db) -> None:
    await db.upsert_user(41012, "teams", "Teams")
    await db.save_sport_pref(41012, "soccer", league="epl", team_name="Arsenal")

    text, markup = await bot._render_settings_team_editor(41012, "soccer")

    assert "Arsenal" in text
    assert any(
        btn.callback_data == "settings:sports"
        for row in markup.inline_keyboard
        for btn in row
    )


async def test_settings_reset_shows_restart_onboarding_prompt(test_db) -> None:
    await db.upsert_user(41013, "reset", "Reset")
    query = _make_query(user_id=41013)

    with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
        await bot.handle_settings(query, "reset")

    mock_card.assert_called_once()
    assert mock_card.call_args.kwargs.get("template") == "onboarding_restart.html"


async def test_handle_ob_restart_returns_to_experience_step() -> None:
    query = _make_query(user_id=41014)

    with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
        await bot.handle_ob_restart(query)

    mock_card.assert_called_once()
    assert mock_card.call_args.kwargs.get("template") == "onboarding_experience.html"


async def test_help_command_shows_help_text(mock_update, mock_context) -> None:
    await bot.cmd_help(mock_update, mock_context)
    text = mock_update.message.reply_text.call_args.args[0]
    assert "/start" in text
    assert "Top Edge Picks" in text


async def test_settings_notifications_screen_has_back_button(test_db) -> None:
    await db.upsert_user(41015, "notifyscreen", "NotifyScreen")
    query = _make_query(user_id=41015)

    await bot.handle_settings(query, "notify")

    markup = query.edit_message_text.call_args.kwargs["reply_markup"]
    callbacks = [
        btn.callback_data
        for row in markup.inline_keyboard
        for btn in row
        if btn.callback_data
    ]
    assert "settings:home" in callbacks
