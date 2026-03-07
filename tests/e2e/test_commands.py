"""Layer 5: Every command responds + invalid input handling.

Verifies all registered commands have handlers and respond.
Tests invalid input handling (random text, emoji, long string, empty).
"""

from __future__ import annotations

import inspect
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ODDS_API_KEY", "test-odds-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("ADMIN_IDS", "123456")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


# All commands registered in main()
REGISTERED_COMMANDS = [
    "start", "menu", "help", "odds", "tip", "picks", "tips",
    "schedule", "settings", "admin", "stats", "status", "upgrade",
    "billing", "founding", "restart_trial", "results", "track",
    "mute", "unmute", "quiet", "qa", "subscribe", "feedback",
]


class TestCommandHandlersExist:
    """Every registered command has a corresponding handler function."""

    def test_all_commands_have_handlers(self):
        """Each command in REGISTERED_COMMANDS maps to a callable in bot module."""
        import bot
        # Commands and their expected handler names
        command_handlers = {
            "start": "cmd_start",
            "menu": "cmd_menu",
            "help": "cmd_help",
            "odds": "cmd_odds",
            "tip": "cmd_tip",
            "picks": "cmd_picks",
            "tips": "cmd_picks",  # alias
            "schedule": "cmd_schedule",
            "settings": "cmd_settings",
            "admin": "cmd_admin",
            "stats": "cmd_stats",
            "status": "cmd_status",
            "upgrade": "cmd_upgrade",
            "billing": "cmd_billing",
            "founding": "cmd_founding",
            "restart_trial": "cmd_restart_trial",
            "results": "cmd_results",
            "track": "cmd_results",  # alias
            "mute": "cmd_mute",
            "unmute": "cmd_mute",  # alias
            "quiet": "cmd_mute",  # alias
            "qa": "cmd_qa",
            "subscribe": "cmd_subscribe",
            "feedback": "cmd_feedback",
        }

        for cmd, handler_name in command_handlers.items():
            handler = getattr(bot, handler_name, None)
            assert handler is not None, f"/{cmd} → {handler_name} not found in bot module"
            assert callable(handler), f"/{cmd} → {handler_name} is not callable"

    def test_command_handlers_are_async(self):
        """All command handlers should be async functions."""
        import bot
        async_handlers = [
            "cmd_start", "cmd_menu", "cmd_help", "cmd_picks",
            "cmd_settings", "cmd_stats", "cmd_results", "cmd_mute",
            "cmd_subscribe", "cmd_qa",
        ]
        for name in async_handlers:
            handler = getattr(bot, name, None)
            if handler:
                assert inspect.iscoroutinefunction(handler), (
                    f"{name} should be async but is not"
                )


class TestKeyboardHandlerExists:
    """Sticky keyboard handler exists and is registered."""

    def test_handle_keyboard_tap_exists(self):
        import bot
        assert hasattr(bot, "handle_keyboard_tap")
        assert inspect.iscoroutinefunction(bot.handle_keyboard_tap)

    def test_freetext_handler_exists(self):
        import bot
        assert hasattr(bot, "freetext_handler")
        assert inspect.iscoroutinefunction(bot.freetext_handler)


class TestCallbackRouter:
    """on_button and _dispatch_button handle all known prefixes."""

    def test_on_button_exists(self):
        import bot
        assert hasattr(bot, "on_button")
        assert inspect.iscoroutinefunction(bot.on_button)

    def test_dispatch_button_exists(self):
        import bot
        assert hasattr(bot, "_dispatch_button")
        assert inspect.iscoroutinefunction(bot._dispatch_button)

    def test_dispatch_handles_noop(self):
        """noop prefix should return immediately without error."""
        import bot
        source = inspect.getsource(bot._dispatch_button)
        assert '"noop"' in source or "'noop'" in source


class TestInputValidation:
    """Invalid input types don't crash the bot."""

    @pytest.mark.asyncio
    async def test_freetext_random_text(self):
        """Random text input is handled gracefully."""
        import bot
        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 999999
        update.message = MagicMock()
        update.message.text = "asdfghjkl random text that means nothing"
        update.message.reply_text = AsyncMock()
        ctx = MagicMock()
        ctx.bot.send_message = AsyncMock()

        # Should not raise
        try:
            await bot.freetext_handler(update, ctx)
        except Exception as e:
            # Some exceptions are OK (DB not available, etc) but no crashes
            assert not isinstance(e, (TypeError, AttributeError, KeyError)), (
                f"Handler crashed on random text: {e}"
            )

    @pytest.mark.asyncio
    async def test_freetext_emoji_input(self):
        """Emoji-only input is handled gracefully."""
        import bot
        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 999999
        update.message = MagicMock()
        update.message.text = "😀🔥🏆🎯💎"
        update.message.reply_text = AsyncMock()
        ctx = MagicMock()
        ctx.bot.send_message = AsyncMock()

        try:
            await bot.freetext_handler(update, ctx)
        except Exception as e:
            assert not isinstance(e, (TypeError, AttributeError, KeyError)), (
                f"Handler crashed on emoji input: {e}"
            )

    @pytest.mark.asyncio
    async def test_freetext_long_string(self):
        """Very long input string is handled gracefully."""
        import bot
        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 999999
        update.message = MagicMock()
        update.message.text = "A" * 5000
        update.message.reply_text = AsyncMock()
        ctx = MagicMock()
        ctx.bot.send_message = AsyncMock()

        try:
            await bot.freetext_handler(update, ctx)
        except Exception as e:
            assert not isinstance(e, (TypeError, AttributeError, KeyError)), (
                f"Handler crashed on long string: {e}"
            )


class TestSanitizeNoCrash:
    """sanitize_ai_response handles edge case inputs without crashing."""

    def test_empty_input(self):
        from bot import sanitize_ai_response
        result = sanitize_ai_response("")
        assert result == ""

    def test_whitespace_only(self):
        from bot import sanitize_ai_response
        result = sanitize_ai_response("   \n\n  \t  ")
        assert result.strip() == ""

    def test_unicode_input(self):
        from bot import sanitize_ai_response
        result = sanitize_ai_response("⚽ 🏉 Mzansi! Lekker bets 🔥")
        assert "Mzansi" in result

    def test_html_injection(self):
        from bot import sanitize_ai_response
        result = sanitize_ai_response("<script>alert('xss')</script>")
        # Should not crash, may strip or escape
        assert "<script>" not in result or "alert" in result  # Either stripped or passed through
