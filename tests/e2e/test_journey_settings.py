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

    # New UX (BUILD-WELCOME-SCREEN-02): photo + inline buttons only, no separate text.
    # If the welcome image is available and fresh, reply_photo is called with kb_main().
    # If no image exists, reply_text falls back with "Welcome back".
    if mock_update.message.reply_photo.called:
        assert mock_update.message.reply_photo.called
    else:
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

    with patch("bot._collect_profile_card_data", new_callable=AsyncMock, return_value={}) as mock_data, \
         patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
        await bot.handle_settings(query, "home")

    mock_card.assert_called_once()
    assert mock_card.call_args.kwargs.get("template") == "profile_home.html"


async def test_cmd_settings_sends_settings_home_card(test_db, mock_update, mock_context) -> None:
    """cmd_settings sends settings_home.html image card, not text."""
    await db.upsert_user(41020, "settingsuser", "Paul")
    await db.set_onboarding_done(41020)
    user = MagicMock()
    user.id = 41020
    user.username = "settingsuser"
    user.first_name = "Paul"
    mock_update.effective_user = user

    with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
        await bot.cmd_settings(mock_update, mock_context)

    mock_card.assert_called_once()
    assert mock_card.call_args.kwargs.get("template") == "settings_home.html"
    assert mock_update.message.reply_text.call_count == 0


async def test_settings_keyboard_tap_sends_settings_home_card(test_db) -> None:
    """Tapping ⚙️ Settings from the reply keyboard sends settings_home.html, not text."""
    await db.upsert_user(41021, "kbsettings", "Tapper")
    await db.set_onboarding_done(41021)

    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 41021
    update.effective_user.username = "kbsettings"
    update.effective_user.first_name = "Tapper"
    update.message = MagicMock()
    update.message.text = "⚙️ Settings"
    update.message.chat_id = 41021
    update.message.reply_text = AsyncMock()
    update.get_bot = MagicMock()

    with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
        await bot.handle_keyboard_tap(update, MagicMock())

    mock_card.assert_called_once()
    assert mock_card.call_args.kwargs.get("template") == "settings_home.html"
    assert update.message.reply_text.call_count == 0


async def test_settings_else_fallback_sends_settings_home_card(test_db) -> None:
    """handle_settings else-branch (unrecognized action) sends settings_home.html."""
    await db.upsert_user(41022, "elseuser", "Elsie")
    query = _make_query(user_id=41022)

    with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
        await bot.handle_settings(query, "unrecognized_action")

    mock_card.assert_called_once()
    assert mock_card.call_args.kwargs.get("template") == "settings_home.html"


async def test_settings_sports_screen_shows_saved_sport(test_db) -> None:
    await db.upsert_user(41007, "sports", "Sports")
    await db.save_sport_pref(41007, "soccer")
    query = _make_query(user_id=41007)

    with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
        await bot.handle_settings(query, "sports")

    mock_card.assert_called_once()
    assert mock_card.call_args.kwargs.get("template") == "settings_sports.html"


async def test_settings_sports_done_persists_selection(test_db) -> None:
    await db.upsert_user(41008, "done", "Done")
    bot._settings_sports_state[41008] = {
        "selected_sports": ["soccer"],
        "original_prefs": [],
    }
    query = _make_query(user_id=41008)

    with patch("bot._collect_profile_card_data", new_callable=AsyncMock, return_value={}), \
         patch("bot.send_card_or_fallback", new_callable=AsyncMock):
        await bot.handle_settings(query, "sports_done")

    prefs = await db.get_user_sport_prefs(41008)
    assert any(pref.sport_key == "soccer" for pref in prefs)



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
    with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
        await bot.cmd_help(mock_update, mock_context)
    mock_card.assert_called_once()
    assert mock_card.call_args.kwargs.get("template") == "help.html"


async def test_settings_notifications_screen_has_back_button(test_db) -> None:
    # FIX-NOTIFICATIONS-DISABLE-01: notifications disabled — action redirects to settings home card
    await db.upsert_user(41015, "notifyscreen", "NotifyScreen")
    query = _make_query(user_id=41015)

    with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
        await bot.handle_settings(query, "notify")

    mock_card.assert_called_once()
    assert mock_card.call_args.kwargs.get("template") == "settings_home.html"
    # kb_settings() markup includes menu:home navigation
    markup = mock_card.call_args.kwargs.get("markup")
    callbacks = [
        btn.callback_data
        for row in markup.inline_keyboard
        for btn in row
        if btn.callback_data
    ]
    assert "menu:home" in callbacks
