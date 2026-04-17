"""IMG-PW3: Card sender utility — send_card_or_fallback.

WIRE STANDARD (BUILD-W3):
    photo→photo:  edit_media(InputMediaPhoto) — no flicker
    text→photo:   delete old message + send_photo
    fallback:     edit_text / send_message on render failure
"""
from __future__ import annotations

import asyncio
import logging

from telegram import InputMediaPhoto
from telegram.constants import ParseMode

from card_renderer import render_card_sync

log = logging.getLogger(__name__)


def _truncate_caption(text: str, limit: int = 1024) -> str:
    """Truncate to limit at a word boundary, never mid-word."""
    if len(text) <= limit:
        return text
    trunc = text[:limit]
    last_space = trunc.rfind(" ")
    if last_space > limit // 2:
        return trunc[:last_space]
    return trunc


async def send_card_or_fallback(
    bot,
    chat_id: int,
    template: str,
    data: dict,
    text_fallback: str,
    markup,
    message_to_edit=None,
) -> None:
    """Render an HTML card to PNG and send/edit in Telegram.

    Parameters
    ----------
    bot:
        PTB bot instance (Application.bot or ctx.bot).
    chat_id:
        Telegram chat_id to send to.
    template:
        Jinja2 template filename inside card_templates/ (e.g. "edge_picks.html").
    data:
        Template variables dict (output of build_*_data() adapter functions).
    text_fallback:
        HTML text to show if card rendering fails.
    markup:
        InlineKeyboardMarkup to attach to the photo or fallback message.
    message_to_edit:
        Existing Message object to edit (None = send as a new message).
        - If message_to_edit.photo → edit_media (photo→photo, no flicker).
        - If message_to_edit is text → delete then send_photo (text→photo).
    """
    try:
        png = await asyncio.to_thread(render_card_sync, template, data)
        _caption = _truncate_caption(text_fallback) if text_fallback else None
        _parse_mode = ParseMode.HTML if (_caption and "<" in _caption) else None
        if message_to_edit and message_to_edit.photo:
            # photo → photo: edit in-place (no flicker)
            await message_to_edit.edit_media(
                media=InputMediaPhoto(
                    media=png,
                    caption=_caption,
                    parse_mode=_parse_mode,
                ),
                reply_markup=markup,
            )
        else:
            if message_to_edit:
                try:
                    await message_to_edit.delete()
                except Exception:
                    pass
            await bot.send_photo(
                chat_id=chat_id,
                photo=png,
                caption=_caption,
                parse_mode=_parse_mode,
                reply_markup=markup,
            )
    except Exception as exc:
        log.warning("card_sender: render failed for %s: %s", template, exc)
        if message_to_edit:
            await message_to_edit.edit_text(
                text=text_fallback,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=text_fallback,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
