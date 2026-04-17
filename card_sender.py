"""IMG-PW3: Card sender utility — send_card_or_fallback.

WIRE STANDARD (BUILD-W3):
    photo→photo:  edit_media(InputMediaPhoto) — no flicker
    text→photo:   delete old message + send_photo
    fallback:     log + Sentry capture only (IMAGE ONLY rule — no user-visible message)
"""
from __future__ import annotations

import asyncio
import logging

from telegram import InputMediaPhoto

from card_renderer import render_card_sync

try:
    import sentry_sdk as _sentry
except ImportError:
    _sentry = None

log = logging.getLogger(__name__)


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
        Retained for call-site backward compatibility — ignored (IMAGE ONLY rule).
    markup:
        InlineKeyboardMarkup to attach to the photo.
    message_to_edit:
        Existing Message object to edit (None = send as a new message).
        - If message_to_edit.photo → edit_media (photo→photo, no flicker).
        - If message_to_edit is text → delete then send_photo.
    """
    try:
        png = await asyncio.to_thread(render_card_sync, template, data)
        if message_to_edit and message_to_edit.photo:
            await message_to_edit.edit_media(
                media=InputMediaPhoto(media=png),
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
                reply_markup=markup,
            )
    except Exception as exc:
        log.error("card_sender: render failed for %s: %s", template, exc, exc_info=True)
        if _sentry:
            _sentry.capture_exception(exc)
