"""Unit tests for card_sender caption pass-through (ARBITER-IMAGE-CARD-FIX-01)."""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

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
async def test_send_photo_caption_present_when_text_fallback_given():
    """send_photo must include caption= when text_fallback is non-empty."""
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
    assert "caption" in kwargs, "caption= must be passed to send_photo"
    assert kwargs["caption"], "caption must not be empty"
    assert len(kwargs["caption"]) <= 1024


@pytest.mark.asyncio
async def test_send_photo_no_caption_when_text_fallback_empty():
    """send_photo must NOT include a truthy caption= when text_fallback is empty."""
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
    assert not kwargs.get("caption"), "caption must be absent or falsy when text_fallback is empty"


@pytest.mark.asyncio
async def test_caption_truncated_at_word_boundary():
    """Caption exceeding 1024 chars is truncated at a word boundary."""
    long_text = "word " * 300  # ~1500 chars
    bot = _make_bot()
    with patch("card_sender.render_card_sync", return_value=_FAKE_PNG):
        import card_sender
        await card_sender.send_card_or_fallback(
            bot=bot,
            chat_id=999,
            template="edge_picks.html",
            data={},
            text_fallback=long_text,
            markup=MagicMock(),
        )
    kwargs = bot.send_photo.call_args.kwargs
    caption = kwargs.get("caption", "")
    assert len(caption) <= 1024
    assert not caption.endswith("wor"), "should not truncate mid-word"


def test_truncate_caption_under_limit():
    """Short captions pass through unchanged."""
    from card_sender import _truncate_caption
    text = "Short caption"
    assert _truncate_caption(text) == text


def test_truncate_caption_at_word_boundary():
    """Long captions are cut at last space before limit."""
    from card_sender import _truncate_caption
    text = " ".join(["word"] * 300)  # ~1499 chars
    result = _truncate_caption(text)
    assert len(result) <= 1024
    assert result.endswith("word")  # ends at a complete word
