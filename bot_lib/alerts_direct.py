"""Bot-direct Alerts channel post for tier-fire events.

BUILD-BOT-ALERTS-DIRECT-01 (20 Apr 2026).

Posts canonical edge_detail.html card to @MzansiEdgeAlerts on Gold/Diamond
tier-fire, without going through the publisher cron. Same renderer as the
bot's /edges detail view — NOT render_reel_card.py.

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

_TIER_EMOJIS = {"diamond": "💎", "gold": "🥇", "silver": "🥈", "bronze": "🥉"}
_TIER_LABELS = {"diamond": "DIAMOND", "gold": "GOLDEN", "silver": "SILVER", "bronze": "BRONZE"}


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


def _build_deeplink_markup(edge_id: str) -> dict:
    return {
        "inline_keyboard": [[
            {"text": "⚡ View full edge", "url": f"{_DEEPLINK_BASE}{edge_id}"}
        ]]
    }


def _build_caption(tip: dict) -> str:
    tier = (tip.get("display_tier") or tip.get("edge_tier") or tip.get("edge_rating") or "gold").lower()
    tier_emoji = _TIER_EMOJIS.get(tier, "🥇")
    tier_label = _TIER_LABELS.get(tier, "GOLDEN")
    home = tip.get("home_team", "")
    away = tip.get("away_team", "")
    outcome = tip.get("outcome", "")
    odds = float(tip.get("odds") or tip.get("recommended_odds") or 0)
    bookmaker = tip.get("bookmaker", "")
    ev = float(tip.get("ev") or tip.get("predicted_ev") or 0)
    league = tip.get("league") or tip.get("league_display") or ""

    parts = [
        f"{tier_emoji} <b>{tier_label} EDGE</b>",
        f"<b>{home} vs {away}</b>",
    ]
    if league:
        parts.append(f"🏆 {league}")
    if outcome and odds > 1.0:
        bk_part = f" ({bookmaker})" if bookmaker else ""
        parts.append(f"💰 {outcome} @ {odds:.2f}{bk_part}")
    if ev > 0:
        parts.append(f"📈 EV +{ev:.1f}%")
    parts.append("")
    parts.append("Tap ⚡ below for full analysis →")
    return "\n".join(parts)


def _render_edge_card_sync(tip: dict) -> bytes | None:
    """Render canonical edge_detail.html card synchronously.

    Uses the same renderer as the bot's /edges detail view.
    NOT render_reel_card.py (retired surface).
    """
    _ensure_paths()
    match_key = tip.get("match_id") or tip.get("match_key") or ""
    try:
        from card_pipeline import build_card_data  # type: ignore[import]
        from card_renderer import render_card_sync  # type: ignore[import]
        card_data = build_card_data(match_key, None, tip=tip, include_analysis=False)
        png = render_card_sync("edge_detail.html", card_data)
        return png if png else None
    except Exception as exc:
        log.warning("alerts_direct: card render failed for %s: %s", match_key, exc)
        return None


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

    AC-B: Uses edge_detail.html renderer (canonical bot card, NOT reel still).
    AC-C: Attaches inline View-full-edge deeplink button.
    AC-J: Emits latency telemetry event.

    Returns:
        Telegram message URL on success, None on failure.
    """
    token = os.environ.get("TELEGRAM_PUBLISHER_BOT_TOKEN", "")
    if not token:
        log.error("alerts_direct: TELEGRAM_PUBLISHER_BOT_TOKEN not set")
        return None

    png_bytes = await asyncio.to_thread(_render_edge_card_sync, tip)
    if not png_bytes:
        log.warning("alerts_direct: card render returned empty bytes for edge_id=%s", edge_id)
        return None

    caption = _build_caption(tip)
    reply_markup = _build_deeplink_markup(edge_id)

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
