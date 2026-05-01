"""IMG-PW3: Card sender utility — send_card_or_fallback.

WIRE STANDARD (BUILD-W3):
    photo→photo:  edit_media(InputMediaPhoto) — no flicker
    text→photo:   delete old message + send_photo
    fallback:     log + Sentry capture only (IMAGE ONLY rule — no user-visible message)

BUILD-FILE-ID-REUSE-01:
    Persistent file_id cache checked before Playwright render.  On hit,
    send_photo(photo=file_id) / edit_media(InputMediaPhoto(media=file_id)) —
    no render, no upload.  On miss, render normally, send, then store the
    returned file_id.  Stale or Telegram-rejected file_ids are invalidated
    and fall through to a full byte render automatically.
"""
from __future__ import annotations

import asyncio
import logging

from telegram import InputMediaPhoto

from card_renderer import build_cache_key as _renderer_build_cache_key
from card_renderer import render_card_sync

try:
    import sentry_sdk as _sentry
except ImportError:
    _sentry = None

log = logging.getLogger(__name__)

_DSF = 2  # device_scale_factor — must match render_card_sync's default


def _build_cache_key(template: str, data: dict, width: int | None) -> str:
    """Mirror render_card_sync's cache key so the file_id key matches the PNG key.

    Delegates to card_renderer.build_cache_key, which embeds the template
    content version. INV-WAVE-F-GLOW-MISSING-PROD-01: prior to this delegation
    the file_id store was keyed without the template version, so a CSS-only
    template change (e.g. lifting .logo-glow into my_matches.html /
    match_detail.html via 2b843ed) left the cache_key stable and the bot
    kept reusing the stale pre-glow Telegram file_id under its 7-day TTL.
    """
    _w = width if width is not None else 480
    return _renderer_build_cache_key(template, data, _w, _DSF)


async def send_card_or_fallback(
    bot,
    chat_id: int,
    template: str,
    data: dict,
    text_fallback: str,
    markup,
    message_to_edit=None,
    width: int | None = None,
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
    width:
        Optional explicit render width in CSS pixels (physical = width × DSF).
        When None, render_card_sync's default (480) applies. Pass 540 for
        match_detail.html to produce 1080px output; other templates keep 480.
    """
    try:
        from file_id_cache import file_id_cache as _fid  # type: ignore[import]

        _cache_key = _build_cache_key(template, data, width)
        _stored_fid = _fid.get(_cache_key)

        # ── file_id fast path ─────────────────────────────────────────────────
        if _stored_fid:
            try:
                if message_to_edit and message_to_edit.photo:
                    await message_to_edit.edit_media(
                        media=InputMediaPhoto(media=_stored_fid),
                        reply_markup=markup,
                    )
                    return
                if message_to_edit:
                    try:
                        await message_to_edit.delete()
                    except Exception:
                        pass
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=_stored_fid,
                    reply_markup=markup,
                )
                return
            except Exception as _fid_err:
                log.warning(
                    "card_sender: file_id reuse rejected for %s (%s), re-rendering",
                    template,
                    _fid_err,
                )
                _fid.invalidate(_cache_key)
            # fall through to full render

        # ── Full render path ──────────────────────────────────────────────────
        if width is None:
            png = await asyncio.to_thread(render_card_sync, template, data)
        else:
            png = await asyncio.to_thread(render_card_sync, template, data, width)

        if message_to_edit and message_to_edit.photo:
            try:
                result = await message_to_edit.edit_media(
                    media=InputMediaPhoto(media=png),
                    reply_markup=markup,
                )
                try:
                    if result and hasattr(result, "photo") and result.photo:
                        _fid.put(_cache_key, result.photo[-1].file_id)
                except Exception:
                    pass
                return
            except Exception as em_err:
                log.warning(
                    "card_sender: edit_media failed (%s), falling back to send_photo",
                    em_err,
                )

        if message_to_edit:
            try:
                await message_to_edit.delete()
            except Exception:
                pass

        msg = await bot.send_photo(
            chat_id=chat_id,
            photo=png,
            reply_markup=markup,
        )
        try:
            if msg and msg.photo:
                _fid.put(_cache_key, msg.photo[-1].file_id)
        except Exception:
            pass

    except Exception as exc:
        log.error("card_sender: render failed for %s: %s", template, exc, exc_info=True)
        if _sentry:
            _sentry.capture_exception(exc)
