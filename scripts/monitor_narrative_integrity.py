#!/usr/bin/env python3
"""BUILD-VERDICT-QUALITY-GATE-01: Narrative Integrity Monitor.

Runs signal checks against narrative_cache and writes results to
narrative_integrity_log.  Sends EdgeOps alerts when signals breach
thresholds.  2-hour debounce per signal.

Usage:
    python scripts/monitor_narrative_integrity.py

Signals produced (6 distinct values):
    1. total_narratives_24h         — all cache writes in last 24h
    2. w84_rate_24h                 — % of W84 (Sonnet) narratives
    3. w82_fallback_count_24h       — count of W82 fallback narratives
    4. empty_verdict_count_24h      — narratives missing a verdict section
    5. low_quality_verdict_count    — verdicts failing min_verdict_quality()
    6. gold_edge_non_sonnet_count   — Gold/Diamond edges NOT served by Sonnet
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

# Resolve paths
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BOT_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _BOT_DIR)
sys.path.insert(0, os.path.dirname(_BOT_DIR))

from config import SCRAPERS_ROOT

_ODDS_DB = os.path.join(str(SCRAPERS_ROOT.parent), "scrapers", "odds.db")

log = logging.getLogger("monitor_narrative_integrity")
if not log.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

# Alert thresholds
_THRESHOLDS = {
    "low_quality_verdict_count": 1,     # any low-quality verdict is worth alerting
    "gold_edge_non_sonnet_count": 1,    # any Gold edge not using Sonnet
    "empty_verdict_count_24h": 3,       # more than 3 missing verdicts in 24h
    "w82_fallback_count_24h": 20,       # more than 20 W82 fallbacks in 24h
}

# Debounce: 2 hours between repeated alerts for the same signal
_DEBOUNCE_HOURS = 2


def _get_db_path() -> str:
    """Return path to the odds.db that holds narrative_cache."""
    if os.path.exists(_ODDS_DB):
        return _ODDS_DB
    # Fallback: look for any odds.db accessible from bot dir
    candidates = [
        os.path.join(_BOT_DIR, "data", "odds.db"),
        os.path.join(os.path.dirname(_BOT_DIR), "scrapers", "odds.db"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return _ODDS_DB  # let it fail with a clear path


def _ensure_integrity_log_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS narrative_integrity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal TEXT NOT NULL,
            value INTEGER NOT NULL,
            recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migrate existing table: add recorded_at if the table pre-dates this schema
    cols = {row[1] for row in conn.execute("PRAGMA table_info(narrative_integrity_log)").fetchall()}
    if "recorded_at" not in cols:
        conn.execute(
            "ALTER TABLE narrative_integrity_log ADD COLUMN recorded_at TEXT DEFAULT '2000-01-01T00:00:00'"
        )
    # Use the correct timestamp column for the index
    ts_col = "recorded_at" if "recorded_at" in cols or True else "ts"
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_nil_signal_time "
        f"ON narrative_integrity_log(signal, {ts_col})"
    )
    conn.commit()


def _ts_col(conn: sqlite3.Connection) -> str:
    """Return the timestamp column name for narrative_integrity_log."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(narrative_integrity_log)").fetchall()}
    return "recorded_at" if "recorded_at" in cols else "ts"


def _last_alert_time(conn: sqlite3.Connection, signal: str) -> datetime | None:
    """Return the last time this signal was recorded, or None."""
    tc = _ts_col(conn)
    row = conn.execute(
        f"SELECT {tc} FROM narrative_integrity_log "
        f"WHERE signal = ? ORDER BY {tc} DESC LIMIT 1",
        (signal,),
    ).fetchone()
    if not row:
        return None
    try:
        ts = row[0]
        if isinstance(ts, str):
            ts = ts.replace("Z", "+00:00")
            return datetime.fromisoformat(ts)
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except Exception:
        return None


def _debounced(conn: sqlite3.Connection, signal: str) -> bool:
    """Return True if this signal was recorded within the debounce window."""
    last = _last_alert_time(conn, signal)
    if last is None:
        return False
    now = datetime.now(tz=timezone.utc)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now - last) < timedelta(hours=_DEBOUNCE_HOURS)


def _write_signal(conn: sqlite3.Connection, signal: str, value: int) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(narrative_integrity_log)").fetchall()}
    if "band" in cols:
        # Old schema — provide required NOT NULL columns
        conn.execute(
            "INSERT INTO narrative_integrity_log (signal, value, ts, band, breach) "
            "VALUES (?, ?, CURRENT_TIMESTAMP, '', 0)",
            (signal, value),
        )
    else:
        conn.execute(
            "INSERT INTO narrative_integrity_log (signal, value) VALUES (?, ?)",
            (signal, value),
        )
    conn.commit()
    log.info("MONITOR: %s = %d", signal, value)


def _send_edgeops_alert(signal: str, value: int, detail: str) -> None:
    """Send an alert to EdgeOps via Telegram Bot API."""
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(_BOT_DIR, ".env"))
    except Exception:
        pass
    token = os.environ.get("BOT_TOKEN", "")
    admin_ids_raw = os.environ.get("ADMIN_IDS", "")
    if not token or not admin_ids_raw:
        log.warning("MONITOR: EdgeOps alert skipped — BOT_TOKEN or ADMIN_IDS not set")
        return
    admin_ids = [int(i.strip()) for i in admin_ids_raw.split(",") if i.strip().isdigit()]
    text = (
        f"⚠️ <b>Narrative Integrity Alert</b>\n"
        f"Signal: <code>{signal}</code>\n"
        f"Value: <b>{value}</b>\n"
        f"{detail}"
    )
    for admin_id in admin_ids:
        try:
            payload = json.dumps(
                {"chat_id": admin_id, "text": text, "parse_mode": "HTML"}
            ).encode()
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10)
            log.info("MONITOR: EdgeOps alert sent to %d for signal %s", admin_id, signal)
        except Exception as _te:
            log.warning("MONITOR: EdgeOps alert to %d failed: %s", admin_id, _te)


def run_monitor(db_path: str | None = None) -> dict[str, int]:
    """Run all signal checks and write results to narrative_integrity_log.

    Returns dict of {signal: value} for all 6 signals.
    """
    path = db_path or _get_db_path()
    if not os.path.exists(path):
        log.warning("MONITOR: narrative DB not found at %s — skipping", path)
        return {}

    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    results: dict[str, int] = {}

    try:
        _ensure_integrity_log_table(conn)

        cutoff_24h = (
            datetime.now(tz=timezone.utc) - timedelta(hours=24)
        ).isoformat()

        # ── Signal 1: total_narratives_24h ────────────────────────────────────
        row = conn.execute(
            "SELECT COUNT(*) FROM narrative_cache WHERE created_at >= ?",
            (cutoff_24h,),
        ).fetchone()
        sig1_val = int(row[0]) if row else 0
        _write_signal(conn, "total_narratives_24h", sig1_val)
        results["total_narratives_24h"] = sig1_val

        # ── Signal 2: w84_rate_24h ─────────────────────────────────────────
        # Percentage of narratives in last 24h that used W84 (Sonnet/Opus)
        if sig1_val > 0:
            row2 = conn.execute(
                "SELECT COUNT(*) FROM narrative_cache "
                "WHERE created_at >= ? AND narrative_source IN ('w84','w84_retry','w84_quality_retry')",
                (cutoff_24h,),
            ).fetchone()
            w84_count = int(row2[0]) if row2 else 0
            sig2_val = int(100 * w84_count / sig1_val)
        else:
            sig2_val = 0
        _write_signal(conn, "w84_rate_24h", sig2_val)
        results["w84_rate_24h"] = sig2_val

        # ── Signal 3: w82_fallback_count_24h ─────────────────────────────────
        row3 = conn.execute(
            "SELECT COUNT(*) FROM narrative_cache "
            "WHERE created_at >= ? AND narrative_source = 'w82'",
            (cutoff_24h,),
        ).fetchone()
        sig3_val = int(row3[0]) if row3 else 0
        _write_signal(conn, "w82_fallback_count_24h", sig3_val)
        results["w82_fallback_count_24h"] = sig3_val

        # ── Signal 4: empty_verdict_count_24h ────────────────────────────────
        # Narratives where the verdict section (🏆) is absent in narrative_html
        row4 = conn.execute(
            "SELECT COUNT(*) FROM narrative_cache "
            "WHERE created_at >= ? AND (verdict_html IS NULL OR verdict_html = '')",
            (cutoff_24h,),
        ).fetchone()
        sig4_val = int(row4[0]) if row4 else 0
        _write_signal(conn, "empty_verdict_count_24h", sig4_val)
        results["empty_verdict_count_24h"] = sig4_val

        # ── Signal 5 (NEW): low_quality_verdict_count ────────────────────────
        # Narratives where the verdict_html fails min_verdict_quality()
        from narrative_spec import min_verdict_quality
        rows5 = conn.execute(
            "SELECT verdict_html FROM narrative_cache "
            "WHERE created_at >= ? AND verdict_html IS NOT NULL AND verdict_html != ''",
            (cutoff_24h,),
        ).fetchall()
        sig5_val = sum(
            1 for r in rows5 if not min_verdict_quality(r["verdict_html"])
        )
        _write_signal(conn, "low_quality_verdict_count", sig5_val)
        results["low_quality_verdict_count"] = sig5_val

        # ── Signal 6 (NEW): gold_edge_non_sonnet_count ───────────────────────
        # Gold/Diamond edges in last 24h where narrative was NOT from Sonnet
        row6 = conn.execute(
            "SELECT COUNT(*) FROM narrative_cache "
            "WHERE created_at >= ? "
            "AND edge_tier IN ('gold','diamond') "
            "AND narrative_source NOT IN ('w84','w84_retry','w84_quality_retry')",
            (cutoff_24h,),
        ).fetchone()
        sig6_val = int(row6[0]) if row6 else 0
        _write_signal(conn, "gold_edge_non_sonnet_count", sig6_val)
        results["gold_edge_non_sonnet_count"] = sig6_val

        # ── EdgeOps alerts (SO #20, 2-hour debounce) ─────────────────────────
        for signal, threshold in _THRESHOLDS.items():
            value = results.get(signal, 0)
            if value >= threshold and not _debounced(conn, signal):
                detail = (
                    f"Threshold: {threshold}\n"
                    f"Detected at: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
                )
                _send_edgeops_alert(signal, value, detail)

    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            log.info("MONITOR: narrative_cache table missing — nothing to check")
        else:
            log.warning("MONITOR: DB error: %s", exc)
    finally:
        conn.close()

    return results


if __name__ == "__main__":
    results = run_monitor()
    print(json.dumps(results, indent=2))
    distinct = len(results)
    print(f"\nDistinct signals: {distinct}")
