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

    mock_update.message.reply_text.assert_called_once()
    call_args = mock_update.message.reply_text.call_args
    text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
    assert "Welcome" in text
    assert "Step 1" in text


async def test_cmd_start_returning_user(test_db, mock_update, mock_context):
    """Returning user with onboarding done should get main menu."""
    await db.upsert_user(22222, "veteran", "Veteran")
    await db.set_onboarding_done(22222)

    mock_user = MagicMock()
    mock_user.id = 22222
    mock_user.username = "veteran"
    mock_user.first_name = "Veteran"
    mock_update.effective_user = mock_user

    await bot.cmd_start(mock_update, mock_context)

    call_args = mock_update.message.reply_text.call_args
    text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
    assert "Welcome back" in text


async def test_cmd_menu(mock_update, mock_context):
    """The /menu command should show main menu."""
    mock_user = MagicMock()
    mock_user.first_name = "User"
    mock_update.effective_user = mock_user

    await bot.cmd_menu(mock_update, mock_context)

    call_args = mock_update.message.reply_text.call_args
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
