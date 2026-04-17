"""Unit tests — card_sender IMAGE ONLY compliance (BUG-KILL-TEXT-DUMPS-01).

Verifies:
- No caption= is passed to send_photo or edit_media (IMAGE ONLY rule)
- No text message is sent on render failure (log + Sentry only)
- text_fallback parameter is accepted but silently ignored
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ODDS_API_KEY", "test-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("SENTRY_DSN", "")


_FAKE_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
    b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x11\x00\x01\x85b"
    b"D\xa6\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_bot():
    bot = MagicMock()
    bot.send_photo = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


@pytest.mark.asyncio
async def test_send_photo_has_no_caption():
    """send_photo must NOT include caption= (IMAGE ONLY rule)."""
    bot = _make_bot()
    with patch("card_sender.render_card_sync", return_value=_FAKE_PNG):
        import card_sender
        await card_sender.send_card_or_fallback(
            bot=bot,
            chat_id=999,
            template="edge_picks.html",
            data={},
            text_fallback="<b>Arsenal</b> vs Chelsea",
            markup=MagicMock(),
        )
    bot.send_photo.assert_called_once()
    kwargs = bot.send_photo.call_args.kwargs
    assert "caption" not in kwargs, "caption= must NOT be passed to send_photo (IMAGE ONLY)"


@pytest.mark.asyncio
async def test_send_photo_no_caption_when_text_fallback_empty():
    """send_photo must NOT include caption= even when text_fallback is empty."""
    bot = _make_bot()
    with patch("card_sender.render_card_sync", return_value=_FAKE_PNG):
        import card_sender
        await card_sender.send_card_or_fallback(
            bot=bot,
            chat_id=999,
            template="edge_picks.html",
            data={},
            text_fallback="",
            markup=MagicMock(),
        )
    bot.send_photo.assert_called_once()
    kwargs = bot.send_photo.call_args.kwargs
    assert "caption" not in kwargs, "caption= must never be passed to send_photo"


@pytest.mark.asyncio
async def test_no_text_message_on_render_failure():
    """On render failure, bot must NOT send a text message (log + Sentry only)."""
    bot = _make_bot()
    with patch("card_sender.render_card_sync", side_effect=RuntimeError("render boom")):
        import card_sender
        await card_sender.send_card_or_fallback(
            bot=bot,
            chat_id=999,
            template="edge_picks.html",
            data={},
            text_fallback="<b>Fallback text</b>",
            markup=MagicMock(),
        )
    bot.send_message.assert_not_called()
    bot.send_photo.assert_not_called()


@pytest.mark.asyncio
async def test_edit_media_has_no_caption():
    """edit_media (photo→photo) must NOT include caption= on InputMediaPhoto."""
    bot = _make_bot()
    msg = MagicMock()
    msg.photo = [MagicMock()]
    msg.edit_media = AsyncMock()
    with patch("card_sender.render_card_sync", return_value=_FAKE_PNG):
        import card_sender
        await card_sender.send_card_or_fallback(
            bot=bot,
            chat_id=999,
            template="edge_picks.html",
            data={},
            text_fallback="some text",
            markup=MagicMock(),
            message_to_edit=msg,
        )
    msg.edit_media.assert_called_once()
    call_kwargs = msg.edit_media.call_args.kwargs
    media = call_kwargs.get("media")
    assert media is not None
    # InputMediaPhoto must not carry caption
    assert not getattr(media, "caption", None), "InputMediaPhoto must not have caption= (IMAGE ONLY)"
