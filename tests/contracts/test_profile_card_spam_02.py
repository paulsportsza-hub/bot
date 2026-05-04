"""FIX-PROFILE-CARD-SPAM-02 — regression guard.

Blanket DM guard in send_card_or_fallback (card_sender.py):
  When template == "profile_home.html" and chat_id <= 0, the function
  must return early without calling bot.send_photo or any render.

Tests:
  AC-1  FIX-PROFILE-CARD-SPAM-02 marker exists in card_sender.py
  AC-2  send_card_or_fallback blocks profile_home.html when chat_id <= 0
  AC-3  send_card_or_fallback does NOT call bot.send_photo for group chat
  AC-4  send_card_or_fallback proceeds normally when chat_id > 0
  AC-5  guard is template-specific: non-profile templates are NOT blocked for negative chat_id
  AC-6  EdgeOps alert is attempted when guard fires
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BOT_DIR))


# ── AC-1: source-level marker ─────────────────────────────────────────────────

class TestSourceMarker:
    def test_fix_marker_in_card_sender(self):
        src = (BOT_DIR / "card_sender.py").read_text(encoding="utf-8")
        assert "FIX-PROFILE-CARD-SPAM-02" in src, (
            "card_sender.py must contain FIX-PROFILE-CARD-SPAM-02 guard marker"
        )

    def test_edgeops_chat_id_defined(self):
        src = (BOT_DIR / "card_sender.py").read_text(encoding="utf-8")
        assert "_EDGEOPS_CHAT_ID" in src, (
            "_EDGEOPS_CHAT_ID must be defined in card_sender.py"
        )

    def test_guard_checks_profile_home_template(self):
        src = (BOT_DIR / "card_sender.py").read_text(encoding="utf-8")
        assert 'template == "profile_home.html"' in src, (
            'Guard must check template == "profile_home.html"'
        )

    def test_guard_checks_chat_id_lte_zero(self):
        src = (BOT_DIR / "card_sender.py").read_text(encoding="utf-8")
        assert "chat_id <= 0" in src, (
            "Guard must check chat_id <= 0 in card_sender.py"
        )


# ── AC-2, AC-3: group chat is blocked ────────────────────────────────────────

class TestGroupChatBlocked:
    @pytest.mark.asyncio
    async def test_profile_home_blocked_for_group_chat(self):
        """send_card_or_fallback must not render or send for group chat_id."""
        import card_sender as cs

        fake_bot = AsyncMock()

        with (
            patch("card_sender.render_card_sync") as mock_render,
            patch("card_sender._fid_available", False, create=True),
        ):
            mock_render.return_value = b"\x89PNG"
            await cs.send_card_or_fallback(
                bot=fake_bot,
                chat_id=-1002987429381,
                template="profile_home.html",
                data={},
                text_fallback="",
                markup=None,
            )

        fake_bot.send_photo.assert_not_called()
        mock_render.assert_not_called()

    @pytest.mark.asyncio
    async def test_profile_home_blocked_for_zero_chat_id(self):
        """Boundary: chat_id == 0 must also be blocked."""
        import card_sender as cs

        fake_bot = AsyncMock()

        with patch("card_sender.render_card_sync") as mock_render:
            mock_render.return_value = b"\x89PNG"
            await cs.send_card_or_fallback(
                bot=fake_bot,
                chat_id=0,
                template="profile_home.html",
                data={},
                text_fallback="",
                markup=None,
            )

        fake_bot.send_photo.assert_not_called()
        mock_render.assert_not_called()


# ── AC-4: DM chat proceeds normally ──────────────────────────────────────────

class TestDmChatProceeds:
    @pytest.mark.asyncio
    async def test_profile_home_allowed_for_positive_chat_id(self):
        """send_card_or_fallback must proceed when chat_id > 0."""
        import card_sender as cs

        fake_bot = AsyncMock()

        with (
            patch.object(cs, "_build_cache_key", return_value="key123"),
            patch("card_sender.asyncio.to_thread", new_callable=AsyncMock, return_value=b"\x89PNG"),
        ):
            # Patch file_id_cache to return no stored fid
            fake_fid = MagicMock()
            fake_fid.get.return_value = None

            with patch.dict("sys.modules", {"file_id_cache": MagicMock(file_id_cache=fake_fid)}):
                await cs.send_card_or_fallback(
                    bot=fake_bot,
                    chat_id=123456,
                    template="profile_home.html",
                    data={},
                    text_fallback="",
                    markup=None,
                )

        fake_bot.send_photo.assert_called_once()
        call_kwargs = fake_bot.send_photo.call_args
        sent_chat_id = (
            call_kwargs.kwargs.get("chat_id")
            or (call_kwargs.args[0] if call_kwargs.args else None)
        )
        assert sent_chat_id == 123456


# ── AC-5: guard is template-specific ─────────────────────────────────────────

class TestGuardTemplateSpecific:
    @pytest.mark.asyncio
    async def test_non_profile_template_not_blocked_for_group(self):
        """Other templates must NOT be blocked by the profile guard."""
        import card_sender as cs

        fake_bot = AsyncMock()

        fake_fid = MagicMock()
        fake_fid.get.return_value = None

        with (
            patch.object(cs, "_build_cache_key", return_value="key456"),
            patch("card_sender.asyncio.to_thread", new_callable=AsyncMock, return_value=b"\x89PNG"),
            patch.dict("sys.modules", {"file_id_cache": MagicMock(file_id_cache=fake_fid)}),
        ):
            await cs.send_card_or_fallback(
                bot=fake_bot,
                chat_id=-1002987429381,
                template="edge_picks.html",
                data={},
                text_fallback="",
                markup=None,
            )

        fake_bot.send_photo.assert_called_once()


# ── AC-6: EdgeOps alert is attempted ─────────────────────────────────────────

class TestEdgeOpsAlert:
    @pytest.mark.asyncio
    async def test_edgeops_alert_attempted_on_block(self):
        """When guard fires, bot.send_message must be called with EdgeOps chat_id."""
        import card_sender as cs

        fake_bot = AsyncMock()

        with patch("card_sender.render_card_sync"):
            await cs.send_card_or_fallback(
                bot=fake_bot,
                chat_id=-1002987429381,
                template="profile_home.html",
                data={},
                text_fallback="",
                markup=None,
            )

        fake_bot.send_message.assert_called_once()
        call_kwargs = fake_bot.send_message.call_args
        called_chat_id = (
            call_kwargs.kwargs.get("chat_id")
            or (call_kwargs.args[0] if call_kwargs.args else None)
        )
        assert called_chat_id == cs._EDGEOPS_CHAT_ID

    @pytest.mark.asyncio
    async def test_edgeops_alert_failure_does_not_raise(self):
        """EdgeOps send_message failure must be swallowed — guard still returns cleanly."""
        import card_sender as cs

        fake_bot = AsyncMock()
        fake_bot.send_message.side_effect = Exception("Telegram API error")

        with patch("card_sender.render_card_sync"):
            await cs.send_card_or_fallback(
                bot=fake_bot,
                chat_id=-1002987429381,
                template="profile_home.html",
                data={},
                text_fallback="",
                markup=None,
            )

        fake_bot.send_photo.assert_not_called()
