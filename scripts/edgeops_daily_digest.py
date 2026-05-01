#!/usr/bin/env python3
"""edgeops_daily_digest.py — FIX-EDGEOPS-NOISE-CLEANUP-01

Daily 04:00 SAST summary for the EdgeOps channel.
Replaces the 30+ noisy real-time alerts with one actionable morning brief.

Cron: 0 4 * * *  (04:00 UTC = 06:00 SAST)
Run:  cd /home/paulsportsza/bot && python scripts/edgeops_daily_digest.py
"""

from __future__ import annotations

import json
import logging
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '/home/paulsportsza')
sys.path.insert(0, '/home/paulsportsza/bot')
from scrapers.db_connect import connect_odds_db
from db_connection import get_connection

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)

import os as _os
BOT_TOKEN = _os.environ.get("BOT_TOKEN", "")
EDGEOPS_CHAT_ID = -1003877525865

ODDS_DB = '/home/paulsportsza/scrapers/odds.db'
BOT_DB = '/home/paulsportsza/bot/data/mzansiedge.db'

SAST = timezone(timedelta(hours=2))
UTC = timezone.utc


def _send_telegram(text: str) -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        'chat_id': EDGEOPS_CHAT_ID,
        'text': text,
        'parse_mode': 'HTML',
    }).encode('utf-8')
    req = urllib.request.Request(
        url, data=payload,
        headers={'Content-Type': 'application/json'},
    )
    for attempt in range(2):
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            return resp.status == 200
        except urllib.error.HTTPError as e:
            log.error(f"Telegram HTTP {e.code} (attempt {attempt + 1}): {e.read()[:200]}")
        except Exception as e:
            log.error(f"Telegram send failed (attempt {attempt + 1}): {e}")
    return False


def _edge_results_summary(conn_odds) -> str:
    """Settled edges in the last 24h."""
    try:
        rows = conn_odds.execute("""
            SELECT result, COUNT(*) as cnt
            FROM edge_results
            WHERE settled_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-24 hours')
              AND result IN ('hit', 'miss', 'void')
            GROUP BY result
        """).fetchall()
    except Exception as e:
        log.warning(f"edge_results query failed: {e}")
        return ""

    if not rows:
        return ""

    counts = {r: c for r, c in rows}
    hits = counts.get('hit', 0)
    misses = counts.get('miss', 0)
    voids = counts.get('void', 0)
    total = hits + misses
    rate_str = f"{100 * hits // total}%" if total > 0 else "n/a"

    parts = [f"📊 <b>Edges (24h):</b> {hits}H / {misses}M / {voids}V — {rate_str} hit rate"]
    return "\n".join(parts)


def _pregen_summary(conn_bot) -> str:
    """Narrative cache coverage for active edges."""
    try:
        rows = conn_bot.execute("""
            SELECT narrative_source, COUNT(*) as cnt
            FROM narrative_cache
            WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-24 hours')
            GROUP BY narrative_source
            ORDER BY cnt DESC
            LIMIT 6
        """).fetchall()
    except Exception as e:
        log.warning(f"narrative_cache query failed: {e}")
        return ""

    if not rows:
        return ""

    total = sum(c for _, c in rows)
    breakdown = ", ".join(f"{src}:{cnt}" for src, cnt in rows[:4])
    return f"🤖 <b>Pregen (24h):</b> {total} narratives ({breakdown})"


def _health_summary(conn_odds) -> str:
    """Source health status snapshot."""
    try:
        rows = conn_odds.execute("""
            SELECT status, COUNT(*) as cnt
            FROM source_health_current
            GROUP BY status
        """).fetchall()
    except Exception as e:
        log.warning(f"source_health_current query failed: {e}")
        return ""

    if not rows:
        return ""

    counts = {s: c for s, c in rows}
    green = counts.get('green', 0)
    yellow = counts.get('yellow', 0)
    red = counts.get('red', 0)
    black = counts.get('black', 0)
    total = green + yellow + red + black

    status_line = f"🏥 <b>Sources:</b> {green}/{total} green"
    if yellow:
        status_line += f", {yellow} yellow"
    if red or black:
        status_line += f", {red + black} red/black"

    # List problem sources
    problem_lines = []
    if red or black:
        problem_rows = conn_odds.execute("""
            SELECT source_id, status FROM source_health_current
            WHERE status IN ('red', 'black')
            ORDER BY status DESC, source_id
            LIMIT 5
        """).fetchall()
        for sid, st in problem_rows:
            icon = "⚫" if st == "black" else "🔴"
            problem_lines.append(f"  {icon} {sid}")

    return "\n".join([status_line] + problem_lines)


def _recovery_summary(conn_odds) -> str:
    """Sources that recovered in the last 24h (replaces RECOVERED Telegram spam)."""
    try:
        rows = conn_odds.execute("""
            SELECT DISTINCT source_id
            FROM health_alerts
            WHERE alert_type = 'status_recovered'
              AND fired_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-24 hours')
            ORDER BY source_id
        """).fetchall()
    except Exception as e:
        log.warning(f"recovery query failed: {e}")
        return ""

    if not rows:
        return ""

    names = [r[0] for r in rows]
    return f"✅ <b>Recovered (24h):</b> {', '.join(names)}"


def _openrouter_balance(conn_odds) -> str:
    """Current OpenRouter balance."""
    try:
        row = conn_odds.execute("""
            SELECT pct_used, credits_remaining
            FROM api_quota_tracking
            WHERE api_name = 'openrouter'
            ORDER BY id DESC
            LIMIT 1
        """).fetchone()
    except Exception as e:
        log.warning(f"openrouter balance query failed: {e}")
        return ""

    if not row:
        return ""

    pct_used, remaining = row
    bal_usd = (remaining / 100) if remaining is not None else 0
    pct_str = f"{pct_used:.1f}%" if pct_used is not None else "?"
    return f"💳 <b>OpenRouter:</b> ${bal_usd:.2f} remaining ({pct_str} used)"


def _stitch_payment_summary(conn_bot) -> str:
    """Payment activity summary for the daily EdgeOps digest.

    BUILD-STITCH-EDGEOPS-WIRE-01: includes 24h failure count alongside
    active subscriber count. Real-time failure alerts are sent immediately
    via _send_edgeops_payment_alert() in bot.py on each webhook event.
    """
    try:
        # Total subscriptions that are active (proxy for paying users)
        row = conn_bot.execute("""
            SELECT COUNT(*) FROM users WHERE subscription_status = 'active'
        """).fetchone()
        active = row[0] if row else 0

        # Failure events in the last 24h from the payments table
        fail_row = conn_bot.execute("""
            SELECT COUNT(*) FROM payments
            WHERE status IN ('failed', 'cancelled', 'expired')
              AND created_at >= datetime('now', '-24 hours')
        """).fetchone()
        failures_24h = fail_row[0] if fail_row else 0

        line = f"💳 <b>Active subs:</b> {active} users"
        if failures_24h > 0:
            line += f" · ⚠️ {failures_24h} payment failure(s) in 24h"
        return line
    except Exception as e:
        log.warning(f"stitch summary query failed: {e}")
        return ""


def build_digest() -> str:
    """Build the full digest message."""
    now_sast = datetime.now(UTC).astimezone(SAST)
    date_str = now_sast.strftime('%a %d %b %Y')

    sections = [f"📋 <b>EdgeOps Daily — {date_str}</b>"]

    try:
        conn_odds = connect_odds_db(ODDS_DB)
        sections.append(_health_summary(conn_odds))
        sections.append(_recovery_summary(conn_odds))
        sections.append(_edge_results_summary(conn_odds))
        sections.append(_openrouter_balance(conn_odds))
        conn_odds.close()
    except Exception as e:
        log.error(f"odds.db access failed: {e}")
        sections.append(f"⚠️ odds.db unavailable: {e}")

    try:
        conn_bot = get_connection(BOT_DB)
        sections.append(_pregen_summary(conn_bot))
        sections.append(_stitch_payment_summary(conn_bot))
        conn_bot.close()
    except Exception as e:
        log.warning(f"bot DB access failed: {e}")

    # Filter empty sections
    body = "\n".join(s for s in sections if s)
    return body


def main() -> None:
    digest = build_digest()
    if not digest:
        log.error("Digest is empty — skipping send")
        return

    ok = _send_telegram(digest)
    if ok:
        log.info("Daily digest sent to EdgeOps")
    else:
        log.error("Daily digest send failed")


if __name__ == '__main__':
    main()
