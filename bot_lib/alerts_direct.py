"""Bot-direct Alerts channel post for tier-fire events.

BUILD-BOT-ALERTS-DIRECT-01 (20 Apr 2026).

Posts canonical per-edge detail card to @MzansiEdgeAlerts on Gold/Diamond
tier-fire, without going through the publisher cron. Uses card_pipeline.render_card_bytes —
same pipeline as the bot's /edges detail view — NOT render_reel_card.py.

Each post carries a View-full-edge deeplink so Founders Floor members can
tap into the bot's full card view for that exact edge.

Note: In-app deeplinks (t.me/mzansiedge_bot?start=card_*) are navigation
links for already-subscribed users — they are NOT acquisition CTAs and do not
go through Bitly. See compliance_config.IN_APP_DEEPLINK_PATTERNS.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time

log = logging.getLogger("bot.alerts_direct")

_ALERTS_CHANNEL_ID = "-1003789410835"
# IN_APP_DEEPLINK: navigation for already-subscribed Founders Floor members.
# Not an acquisition CTA — raw t.me deeplink is intentional (no Bitly wrap).
_DEEPLINK_BASE = "https://t.me/mzansiedge_bot?start=card_"


def _ensure_paths() -> None:
    bot_dir = os.path.dirname(os.path.dirname(__file__))  # bot/
    pub_channels = "/home/paulsportsza/publisher/channels"
    pub_dir = "/home/paulsportsza/publisher"
    pub_lib = "/home/paulsportsza/publisher/lib"
    for p in (bot_dir, pub_dir, pub_channels):
        if p not in sys.path:
            sys.path.insert(0, p)
    # Publisher's lib.channel_link must resolve before bot's lib package.
    # Insert at position 0 after bot_dir so it takes priority.
    if pub_lib not in sys.path:
        idx = sys.path.index(bot_dir) + 1 if bot_dir in sys.path else 0
        sys.path.insert(idx, pub_lib)


def _build_deeplink_markup(match_key: str) -> dict:
    return {
        "inline_keyboard": [[
            {"text": "⚡ View full edge →", "url": f"{_DEEPLINK_BASE}{match_key}"}
        ]]
    }



def _sync_render_card(tip: dict, buttons: list | None = None) -> bytes:
    """Sync wrapper — calls canonical render_card_bytes pipeline.

    AC-C.1: accepts optional PTB buttons list (None = default no embedded buttons).
    No hardcoded buttons=[] — callers decide whether to embed PTB keyboard objects.
    The Telegram reply_markup (deeplink inline keyboard) is constructed separately in
    post_to_alerts and passed to _post_sync — not embedded in the card image.

    Raises CardPopulationError if CARD-GATE-INV-01 fails.
    Raises any other exception on render failure.
    """
    _ensure_paths()
    from card_pipeline import render_card_bytes  # type: ignore[import]
    match_key = tip.get("match_key") or tip.get("match_id") or ""

    # Hydrate tip with full DB enrichment so the card is identical to ep:pick.
    # _enrich_tip_for_card (bot.py) is safe to import here: alerts_direct always
    # runs inside the bot process where bot is already in sys.modules.
    try:
        from bot import _enrich_tip_for_card  # type: ignore[import]
        tip = _enrich_tip_for_card(tip, match_key)
    except Exception as _hydrate_err:
        log.warning("alerts_direct: tip hydration failed (%s) — card may be partial", _hydrate_err)

    img_bytes, _, _ = render_card_bytes(match_key, tip, include_analysis=False, buttons=buttons)
    return img_bytes


_PUBLISHED_URL_BASE = "https://t.me/c/3789410835"


def _post_sync(token: str, png_bytes: bytes, caption: str, reply_markup: dict) -> str | None:
    """Post card to Alerts channel synchronously (direct HTTP — no publisher imports)."""
    import io
    import json
    import requests as _req

    if not token:
        log.error("alerts_direct: TELEGRAM_PUBLISHER_BOT_TOKEN not set")
        return None

    caption = (caption[:1021] + "...") if len(caption) > 1024 else caption
    api_url = f"https://api.telegram.org/bot{token}/sendPhoto"
    payload = {"chat_id": str(_ALERTS_CHANNEL_ID), "parse_mode": "HTML"}
    if caption:
        payload["caption"] = caption
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(reply_markup) if isinstance(reply_markup, dict) else reply_markup

    try:
        files = {"photo": ("card.png", io.BytesIO(png_bytes), "image/png")}
        resp = _req.post(api_url, data=payload, files=files, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            log.warning("alerts_direct: Telegram API error: %s", data.get("description", "unknown"))
            return None
        message_id = data["result"]["message_id"]
        return f"{_PUBLISHED_URL_BASE}/{message_id}"
    except Exception as exc:
        log.warning("alerts_direct: sendPhoto failed: %s", exc)
        return None


async def post_to_alerts(
    tip: dict,
    edge_id: str,
    tier_assigned_at: float | None = None,
) -> str | None:
    """Render canonical edge card and post to @MzansiEdgeAlerts.

    Uses card_pipeline.render_card_bytes (canonical bot card, NOT reel still).
    Attaches inline View-full-edge deeplink button.
    AC-J: Emits latency telemetry event.

    Returns:
        Telegram message URL on success, None on failure.
    """
    token = os.environ.get("TELEGRAM_PUBLISHER_BOT_TOKEN", "")
    if not token:
        log.error("alerts_direct: TELEGRAM_PUBLISHER_BOT_TOKEN not set")
        return None

    _dl_match_key = tip.get("match_key") or tip.get("match_id") or edge_id
    # Encode the tier at post time so the deeplink can restore it even if the
    # scraper later recalculates and changes the DB row's edge_tier.
    _dl_tier_now = (tip.get("display_tier") or tip.get("edge_tier") or "gold").lower()
    _dl_key_with_tier = f"{_dl_match_key}_{_dl_tier_now}"
    try:
        png_bytes = await asyncio.to_thread(_sync_render_card, tip)
    except Exception as exc:
        log.warning("alerts_direct: card render failed for %s: %s", _dl_match_key, exc)
        return None

    caption = ""
    reply_markup = _build_deeplink_markup(_dl_key_with_tier)

    msg_url = await asyncio.to_thread(_post_sync, token, png_bytes, caption, reply_markup)

    latency_ms: int | None = None
    if tier_assigned_at is not None:
        latency_ms = int((time.time() - tier_assigned_at) * 1000)

    if msg_url:
        _emit_latency_event(edge_id, tip, latency_ms, msg_url)
        tier = (tip.get("display_tier") or tip.get("edge_tier") or "gold").lower()
        log.info(
            "alerts_direct: posted edge_id=%s tier=%s latency_ms=%s url=%s",
            edge_id, tier, latency_ms, msg_url,
        )

    return msg_url


def _emit_latency_event(
    edge_id: str,
    tip: dict,
    latency_ms: int | None,
    msg_url: str | None,
) -> None:
    """AC-J: emit alerts_direct_post event for latency SLO monitoring."""
    tier = (tip.get("display_tier") or tip.get("edge_tier") or "gold").lower()
    match_key = tip.get("match_id") or tip.get("match_key") or ""
    props = {
        "edge_id": edge_id,
        "match_key": match_key,
        "tier": tier,
        "latency_ms_from_tier_assignment": latency_ms,
        "alerts_message_url": msg_url,
        "feature": "alerts_direct",
    }
    try:
        import sentry_sdk  # type: ignore[import]
        sentry_sdk.add_breadcrumb(
            category="alerts_direct",
            message="Bot-direct Alerts post",
            data=props,
            level="info",
        )
        with sentry_sdk.new_scope() as _scope:
            _scope.set_tag("feature", "alerts_direct")
            for k, v in props.items():
                _scope.set_extra(k, v)
            sentry_sdk.capture_message(
                f"alerts_direct_post: {match_key} tier={tier} latency_ms={latency_ms}",
                level="info",
                scope=_scope,
            )
    except Exception:
        pass
