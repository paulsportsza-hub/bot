"""FIX-PROFILE-CARD-SPAM-01 — regression guard.

Profile card sends (profile_home.html) must only reach DM chats (chat_id > 0).
Three send sites guarded:
  1. _show_profile()       — sticky keyboard tap
  2. on_button profile:home — inline callback
  3. handle_settings settings:home — settings inline callback

Handler registration: handle_keyboard_tap must use filters.ChatType.PRIVATE.

Tests:
  AC-1  handler registration includes ChatType.PRIVATE filter
  AC-2  _show_profile returns early when chat_id <= 0
  AC-3  profile:home on_button returns early when chat_id <= 0
  AC-4  settings:home returns early when chat_id <= 0
  AC-5  _show_profile does NOT call send_card_or_fallback for negative chat_id
  AC-6  profile:home does NOT call send_card_or_fallback for negative chat_id
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BOT_DIR))


# ── helpers ──────────────────────────────────────────────────────────────────

def _bot_source() -> str:
    return (BOT_DIR / "bot.py").read_text(encoding="utf-8")


# ── AC-1: handler registration ────────────────────────────────────────────────

class TestHandlerRegistration:
    def test_keyboard_tap_handler_includes_chattype_private(self):
        src = _bot_source()
        # Look for the add_handler call for handle_keyboard_tap that also includes ChatType.PRIVATE
        # The line is: app.add_handler(MessageHandler(filters.Regex(_kb_pattern) & filters.ChatType.PRIVATE, handle_keyboard_tap))
        pattern = re.compile(
            r"MessageHandler\(.*?_kb_pattern.*?ChatType\.PRIVATE.*?handle_keyboard_tap",
            re.DOTALL,
        )
        assert pattern.search(src), (
            "handle_keyboard_tap MessageHandler must include filters.ChatType.PRIVATE"
        )

    def test_chattype_private_is_anded_not_ored(self):
        src = _bot_source()
        # Confirm it's `... & filters.ChatType.PRIVATE` not just mentioned somewhere
        assert "filters.ChatType.PRIVATE" in src, (
            "filters.ChatType.PRIVATE must appear in bot.py"
        )
        # The pattern should be: Regex(...) & filters.ChatType.PRIVATE
        assert re.search(r"Regex\(_kb_pattern\)\s*&\s*filters\.ChatType\.PRIVATE", src), (
            "ChatType.PRIVATE must be ANDed with Regex(_kb_pattern) for handle_keyboard_tap"
        )


# ── AC-2, AC-5: _show_profile guard ──────────────────────────────────────────

class TestShowProfileGuard:
    def test_show_profile_guard_present_in_source(self):
        src = _bot_source()
        assert "FIX-PROFILE-CARD-SPAM-01" in src, "Guard log marker must appear in bot.py"

    @pytest.mark.asyncio
    async def test_show_profile_returns_early_for_group_chat(self):
        """_show_profile must not call send_card_or_fallback when chat_id <= 0."""
        import importlib
        import types

        # Build a minimal fake update with a negative chat_id
        fake_chat = MagicMock()
        fake_chat.id = -1002987429381  # community group (negative)
        fake_update = MagicMock()
        fake_update.effective_chat = fake_chat
        fake_bot = AsyncMock()
        fake_update.get_bot.return_value = fake_bot

        with (
            patch("bot._collect_profile_card_data", new_callable=AsyncMock) as mock_collect,
            patch("bot._build_profile_buttons", new_callable=AsyncMock) as mock_buttons,
            patch("bot._render_profile_home_surface", new_callable=AsyncMock, return_value=("", None)),
            patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_send,
            patch("bot._EDGEOPS_CHAT_ID", -1003877525865),
        ):
            import bot as bot_module
            await bot_module._show_profile(fake_update, user_id=123456)

        mock_collect.assert_not_called()
        mock_buttons.assert_not_called()
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_show_profile_proceeds_for_dm_chat(self):
        """_show_profile must proceed normally when chat_id > 0."""
        fake_chat = MagicMock()
        fake_chat.id = 123456  # positive = DM
        fake_update = MagicMock()
        fake_update.effective_chat = fake_chat
        fake_bot = AsyncMock()
        fake_update.get_bot.return_value = fake_bot

        with (
            patch("bot._collect_profile_card_data", new_callable=AsyncMock, return_value={}),
            patch("bot._build_profile_buttons", new_callable=AsyncMock, return_value=None),
            patch("bot._render_profile_home_surface", new_callable=AsyncMock, return_value=("", None)),
            patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_send,
        ):
            import bot as bot_module
            await bot_module._show_profile(fake_update, user_id=123456)

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1] if mock_send.call_args[1] else mock_send.call_args[0]
        # chat_id passed must be positive
        if isinstance(call_kwargs, dict):
            sent_chat_id = call_kwargs.get("chat_id")
        else:
            sent_chat_id = call_kwargs[1] if len(call_kwargs) > 1 else None
        assert sent_chat_id is None or sent_chat_id > 0


# ── AC-3, AC-4, AC-6: source-level guard patterns ────────────────────────────

class TestGuardPatternsInSource:
    def test_profile_home_callback_has_chat_id_guard(self):
        src = _bot_source()
        # Within the profile:home callback block there must be a chat_id <= 0 guard
        profile_home_idx = src.find('prefix == "profile"')
        assert profile_home_idx != -1, "profile:home callback must exist"
        snippet = src[profile_home_idx: profile_home_idx + 2000]
        assert "_ph_chat_id" in snippet and "_ph_chat_id <= 0" in snippet, (
            "profile:home callback must guard against non-DM chat_id"
        )

    def test_settings_home_has_chat_id_guard(self):
        src = _bot_source()
        # settings:home guard uses _sh_chat_id
        assert "_sh_chat_id" in src and "_sh_chat_id <= 0" in src, (
            "settings:home must guard against non-DM chat_id"
        )

    def test_all_three_guards_emit_edgeops_warning(self):
        src = _bot_source()
        # Each guard must send a warning to EdgeOps
        occurrences = src.count("FIX-PROFILE-CARD-SPAM-01: profile")
        assert occurrences >= 3, (
            f"Expected at least 3 guard log messages for FIX-PROFILE-CARD-SPAM-01, found {occurrences}"
        )

    def test_no_profile_home_send_with_unchecked_chat_id(self):
        src = _bot_source()
        # After the fix, every send_card_or_fallback call for profile_home.html
        # should use a local variable (_sf_chat_id / _ph_chat_id / _sh_chat_id), not
        # raw update.effective_chat.id or query.message.chat_id directly.
        # Check that raw patterns no longer appear alongside profile_home template name.
        template_hits = [m.start() for m in re.finditer(r'profile_home\.html', src)]
        assert len(template_hits) >= 3, "Should have at least 3 profile_home.html send sites"
        for idx in template_hits:
            snippet = src[max(0, idx - 400): idx + 200]
            # Must NOT see raw effective_chat.id as the chat_id arg in the same snippet
            assert "effective_chat.id," not in snippet, (
                f"profile_home.html send site at offset {idx} uses raw effective_chat.id — "
                "it must use the guarded local variable instead"
            )
