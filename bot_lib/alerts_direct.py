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
_ALERTS_SEND_CHANNEL = "alerts"
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
_SEND_RESERVATION_STALE_SECONDS = 10 * 60


def _alerts_db_path() -> str:
    return os.environ.get(
        "ALERTS_SEND_LOG_DB_PATH",
        os.path.expanduser("~/scrapers/odds.db"),
    )


def _ensure_alerts_send_log_schema(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alerts_send_log (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            edge_id          TEXT,
            match_key        TEXT,
            tier             TEXT,
            channel          TEXT NOT NULL DEFAULT 'alerts',
            status           TEXT NOT NULL DEFAULT 'sent',
            image_bytes_size INTEGER,
            msg_url          TEXT,
            sent_at          REAL NOT NULL
        )
    """)
    _cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(alerts_send_log)").fetchall()
    }
    if "channel" not in _cols:
        conn.execute(
            "ALTER TABLE alerts_send_log "
            "ADD COLUMN channel TEXT NOT NULL DEFAULT 'alerts'"
        )
    if "status" not in _cols:
        conn.execute(
            "ALTER TABLE alerts_send_log "
            "ADD COLUMN status TEXT NOT NULL DEFAULT 'sent'"
        )
    conn.execute(
        "DELETE FROM alerts_send_log "
        "WHERE edge_id IS NOT NULL "
        "AND id NOT IN ("
        "  SELECT keep_id FROM ("
        "    SELECT MAX(id) AS keep_id "
        "    FROM alerts_send_log "
        "    WHERE edge_id IS NOT NULL "
        "    GROUP BY edge_id, channel"
        "  )"
        ")"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uix_alerts_send_log_edge_channel "
        "ON alerts_send_log(edge_id, channel)"
    )


def _reserve_send_sync(
    edge_id: str,
    match_key: str,
    tier: str,
) -> tuple[bool, str | None, int | None]:
    """Atomically reserve an Alerts send; return (acquired, existing_url, row id)."""
    if not edge_id:
        return False, None, None
    db_path = _alerts_db_path()
    try:
        from scrapers.db_connect import connect_odds_db  # type: ignore[import]
    except ImportError as exc:
        log.warning("alerts_direct: _reserve_send_sync import error: %s", exc)
        return False, None, None
    conn = None
    try:
        conn = connect_odds_db(db_path)
        _ensure_alerts_send_log_schema(conn)
        now = time.time()
        stale_before = now - _SEND_RESERVATION_STALE_SECONDS
        conn.execute(
            "DELETE FROM alerts_send_log "
            "WHERE edge_id = ? AND channel = ? AND status = 'sending' AND sent_at < ?",
            (edge_id, _ALERTS_SEND_CHANNEL, stale_before),
        )
        cur = conn.execute(
            "INSERT OR IGNORE INTO alerts_send_log"
            " (edge_id, match_key, tier, channel, status, image_bytes_size, msg_url, sent_at)"
            " VALUES (?, ?, ?, ?, 'sending', 0, '', ?)",
            (edge_id, match_key, tier, _ALERTS_SEND_CHANNEL, now),
        )
        if cur.rowcount == 1:
            reservation_id = int(cur.lastrowid)
            conn.commit()
            return True, None, reservation_id
        row = conn.execute(
            "SELECT status, msg_url FROM alerts_send_log "
            "WHERE edge_id = ? AND channel = ? "
            "ORDER BY sent_at DESC LIMIT 1",
            (edge_id, _ALERTS_SEND_CHANNEL),
        ).fetchone()
        conn.commit()
        if row and row[0] == "sent":
            return False, row[1] or "already_sent", None
        return False, None, None
    except Exception as exc:
        log.warning("alerts_direct: send reservation failed: %s", exc)
        return False, None, None
    finally:
        if conn is not None:
            conn.close()


def _release_send_reservation_sync(edge_id: str, reservation_id: int | None) -> None:
    if not edge_id or reservation_id is None:
        return
    db_path = _alerts_db_path()
    try:
        from scrapers.db_connect import connect_odds_db  # type: ignore[import]
    except ImportError as exc:
        log.warning("alerts_direct: _release_send_reservation_sync import error: %s", exc)
        return
    conn = None
    try:
        conn = connect_odds_db(db_path)
        _ensure_alerts_send_log_schema(conn)
        conn.execute(
            "DELETE FROM alerts_send_log "
            "WHERE id = ? AND edge_id = ? AND channel = ? AND status = 'sending'",
            (reservation_id, edge_id, _ALERTS_SEND_CHANNEL),
        )
        conn.commit()
    except Exception as exc:
        log.warning("alerts_direct: send reservation release failed: %s", exc)
    finally:
        if conn is not None:
            conn.close()


def _finalize_send_log_sync(
    edge_id: str,
    match_key: str,
    tier: str,
    image_bytes_size: int,
    msg_url: str | None,
    reservation_id: int | None,
) -> None:
    """Persist a successful Alerts send to alerts_send_log in odds.db.

    AC-A (BUILD-SOCIAL-OPS-ALERTS-EVENT-DRIVEN-01): event-driven replacement
    for the dead MOQ→Alerts path. W81-DBLOCK compliant — uses connect_odds_db.
    """
    db_path = _alerts_db_path()
    try:
        from scrapers.db_connect import connect_odds_db  # type: ignore[import]
    except ImportError as exc:
        log.warning("alerts_direct: _finalize_send_log_sync import error: %s", exc)
        return
    conn = None
    try:
        conn = connect_odds_db(db_path)
        _ensure_alerts_send_log_schema(conn)
        cur = conn.execute(
            "UPDATE alerts_send_log "
            "SET match_key = ?, tier = ?, status = 'sent', "
            "image_bytes_size = ?, msg_url = ?, sent_at = ? "
            "WHERE id = ? AND edge_id = ? AND channel = ? AND status = 'sending'",
            (
                match_key,
                tier,
                image_bytes_size,
                msg_url,
                time.time(),
                reservation_id,
                edge_id,
                _ALERTS_SEND_CHANNEL,
            ),
        )
        if cur.rowcount == 0:
            log.warning(
                "alerts_direct: send reservation finalize skipped edge_id=%s reservation_id=%s",
                edge_id,
                reservation_id,
            )
        conn.commit()
    except Exception as exc:
        log.warning("alerts_direct: alerts_send_log write failed: %s", exc)
    finally:
        if conn is not None:
            conn.close()


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
    _dl_match_key = tip.get("match_key") or tip.get("match_id") or edge_id
    # Encode the tier at post time so the deeplink can restore it even if the
    # scraper later recalculates and changes the DB row's edge_tier.
    _dl_tier_now = (tip.get("display_tier") or tip.get("edge_tier") or "gold").lower()

    reservation_acquired, existing_msg_url, reservation_id = await asyncio.to_thread(
        _reserve_send_sync,
        edge_id,
        _dl_match_key,
        _dl_tier_now,
    )
    if existing_msg_url:
        log.info(
            "alerts_direct: skipped duplicate edge_id=%s existing_url=%s",
            edge_id,
            existing_msg_url,
        )
        return existing_msg_url
    if not reservation_acquired:
        log.info("alerts_direct: skipped in-flight duplicate edge_id=%s", edge_id)
        return None

    token = os.environ.get("TELEGRAM_PUBLISHER_BOT_TOKEN", "")
    if not token:
        log.error("alerts_direct: TELEGRAM_PUBLISHER_BOT_TOKEN not set")
        await asyncio.to_thread(_release_send_reservation_sync, edge_id, reservation_id)
        return None

    _dl_key_with_tier = f"{_dl_match_key}_{_dl_tier_now}"
    try:
        png_bytes = await asyncio.to_thread(_sync_render_card, tip)
    except Exception as exc:
        log.warning("alerts_direct: card render failed for %s: %s", _dl_match_key, exc)
        await asyncio.to_thread(_release_send_reservation_sync, edge_id, reservation_id)
        return None

    caption = ""
    reply_markup = _build_deeplink_markup(_dl_key_with_tier)

    msg_url = await asyncio.to_thread(_post_sync, token, png_bytes, caption, reply_markup)
    if not msg_url:
        await asyncio.to_thread(_release_send_reservation_sync, edge_id, reservation_id)
        return None

    latency_ms: int | None = None
    if tier_assigned_at is not None:
        latency_ms = int((time.time() - tier_assigned_at) * 1000)

    _emit_latency_event(edge_id, tip, latency_ms, msg_url)
    tier = (tip.get("display_tier") or tip.get("edge_tier") or "gold").lower()
    log.info(
        "alerts_direct: posted edge_id=%s tier=%s latency_ms=%s url=%s",
        edge_id, tier, latency_ms, msg_url,
    )
    # AC-A: persist send record for event-driven dashboard feed
    _mk = tip.get("match_key") or tip.get("match_id") or edge_id
    await asyncio.to_thread(
        _finalize_send_log_sync,
        edge_id,
        _mk,
        tier,
        len(png_bytes),
        msg_url,
        reservation_id,
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
