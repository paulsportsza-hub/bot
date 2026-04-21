#!/usr/bin/env python3
"""BUILD-VERDICT-QUALITY-GATE-01 + BUILD-COACHES-MONITOR-WIRE-01: Narrative Integrity Monitor.

Runs signal checks against narrative_cache and writes results to
narrative_integrity_log.  Sends EdgeOps alerts when signals breach
thresholds.  2-hour debounce per signal.

Usage:
    python scripts/monitor_narrative_integrity.py

Signals produced (12 distinct values):
    1. total_narratives_24h              — all cache writes in last 24h
    2. w84_rate_24h                      — % of W84 (Sonnet) narratives
    3. w82_fallback_count_24h            — count of W82 fallback narratives
    4. empty_verdict_count_24h           — narratives missing a verdict section
    5. low_quality_verdict_count         — verdicts failing min_verdict_quality()
    6a. gold_edge_sonnet_fallback_rate   — % of Gold/Diamond served via W82 fallback (warn)
    6b. gold_edge_double_fail_count_24h  — count of Gold/Diamond where BOTH Sonnet attempts
                                           failed the verdict quality gate (critical)
    7. validator_reject_rate             — % of validator calls rejected
    8. banned_template_hit_rate          — % of validator calls hitting a banned template
    9. manager_name_fabrication_attempts — count of fabricated manager name attempts
   10. coach_freshness_pct               — % of coaches.json entries stale >7 days
   11. bot_coaches_sync                  — mismatches between bot/data/coaches.json and scrapers version
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

# ── GlitchTip ─────────────────────────────────────────────────────────────────
_SCRAPERS_DIR = os.path.join(os.path.dirname(_BOT_DIR), "scrapers")
sys.path.insert(0, _SCRAPERS_DIR)
try:
    from _sentry_init import init_sentry as _init_sentry
    _sentry = _init_sentry("narrative_integrity_monitor")
except Exception:
    _sentry = None

_ODDS_DB = os.path.join(str(SCRAPERS_ROOT.parent), "scrapers", "odds.db")

log = logging.getLogger("monitor_narrative_integrity")
if not log.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

# SO #20: EdgeOps alerts ONLY — never public channel
EDGE_OPS_CHAT_ID = -1003877525865

# Alert thresholds
_THRESHOLDS = {
    "low_quality_verdict_count": 1,           # any low-quality verdict is worth alerting
    "gold_edge_sonnet_fallback_rate": 60,     # warn when >60% of Gold/Diamond fall back from Sonnet to W82
    "gold_edge_double_fail_count_24h": 3,     # >=3 Gold/Diamond edges with both Sonnet attempts failing the quality gate
    "empty_verdict_count_24h": 3,             # more than 3 missing verdicts in 24h
    "w82_fallback_count_24h": 20,             # more than 20 W82 fallbacks in 24h
    "validator_reject_rate": 30,              # >30% rejection rate
    "banned_template_hit_rate": 10,           # >10% banned-template hit rate
    "manager_name_fabrication_attempts": 1,   # any fabrication attempt is worth alerting
}

# Debounce: 2 hours between repeated alerts for the same signal
_DEBOUNCE_HOURS = 2

# Signals that fire as severity='critical' in health_alerts
_CRITICAL_SIGNALS = frozenset({
    "sonnet_firing_rate",
    "staleness_pct",
    "empty_verdict_count_24h",
    "gold_edge_double_fail_count_24h",
    "manager_name_fabrication_attempts",
})

# source_id registered in source_registry for all narrative monitor alerts
_SOURCE_ID = "narrative_integrity_monitor"


def _severity_for(signal: str) -> str:
    return "critical" if signal in _CRITICAL_SIGNALS else "warning"


def _compute_int_band(signal: str, value: int) -> tuple[str, int]:
    """Return (band, breach) for an integer-valued signal using _THRESHOLDS."""
    threshold = _THRESHOLDS.get(signal)
    if threshold is not None and value >= threshold:
        return "ALERT", 1
    return "GREEN", 0


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
    # Migrate existing table: add columns if the table pre-dates this schema
    cols = {row[1] for row in conn.execute("PRAGMA table_info(narrative_integrity_log)").fetchall()}
    if "recorded_at" not in cols:
        conn.execute(
            "ALTER TABLE narrative_integrity_log ADD COLUMN recorded_at TEXT DEFAULT '2000-01-01T00:00:00'"
        )
        cols.add("recorded_at")
    if "fixture_id" not in cols:
        conn.execute(
            "ALTER TABLE narrative_integrity_log ADD COLUMN fixture_id TEXT"
        )
    if "details" not in cols:
        conn.execute(
            "ALTER TABLE narrative_integrity_log ADD COLUMN details TEXT"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_nil_signal_time "
        "ON narrative_integrity_log(signal, recorded_at)"
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


def _write_signal(conn: sqlite3.Connection, signal: str, value: int, band: str = "", breach: int = 0) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(narrative_integrity_log)").fetchall()}
    if "band" in cols:
        conn.execute(
            "INSERT INTO narrative_integrity_log (signal, value, ts, band, breach, recorded_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?, CURRENT_TIMESTAMP)",
            (signal, value, band, breach),
        )
    else:
        conn.execute(
            "INSERT INTO narrative_integrity_log (signal, value, recorded_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP)",
            (signal, value),
        )
    conn.commit()
    log.info("MONITOR: %s = %s [%s]", signal, value, band or "—")


def write_integrity_event(
    signal: str,
    fixture_id: str = "",
    reason: str = "",
    db_path: str | None = None,
) -> None:
    """Write a single raw integrity event row to narrative_integrity_log.

    Called by pregenerate_narratives.py to log individual rejection/fabrication
    events. The monitor aggregates these into rates on each 30-min run.

    Safe to call from any context — swallows all exceptions silently.
    """
    # W91-VALIDATOR-REJECT: never write to production integrity log from test runs.
    # pytest sets PYTEST_CURRENT_TEST for every test; contract tests intentionally
    # exercise the reject path with bad narratives and would otherwise inflate
    # validator_reject_rate (ALERT threshold = 30) on every run.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    path = db_path or _get_db_path()
    try:
        conn = sqlite3.connect(path, timeout=3)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(narrative_integrity_log)").fetchall()}
        if not cols:
            conn.close()
            return  # Table doesn't exist yet — skip silently
        if "band" in cols:
            conn.execute(
                "INSERT INTO narrative_integrity_log "
                "(signal, value, ts, band, breach, recorded_at, fixture_id, details) "
                "VALUES (?, 1, CURRENT_TIMESTAMP, '', 0, CURRENT_TIMESTAMP, ?, ?)",
                (signal, fixture_id, reason),
            )
        else:
            conn.execute(
                "INSERT INTO narrative_integrity_log "
                "(signal, value, recorded_at, fixture_id, details) "
                "VALUES (?, 1, CURRENT_TIMESTAMP, ?, ?)",
                (signal, fixture_id, reason),
            )
        conn.commit()
        conn.close()
    except Exception as _e:
        log.debug("MONITOR: write_integrity_event failed for %s/%s: %s", signal, fixture_id, _e)


def _send_edgeops_alert(signal: str, value: int, detail: str) -> None:
    """Send an alert to EDGE_OPS_CHAT_ID via Telegram Bot API.

    SO #20: EdgeOps alerts ONLY — never public channel.
    Mirrors health_monitor.py _send_tier_drift_alert() pattern.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(_BOT_DIR, ".env"))
    except Exception:
        pass
    token = os.environ.get("BOT_TOKEN", "")
    if not token:
        log.warning("MONITOR: EdgeOps alert skipped — BOT_TOKEN not set")
        return
    text = (
        f"⚠️ <b>Narrative Integrity Alert</b>\n"
        f"Signal: <code>{signal}</code>\n"
        f"Value: <b>{value}</b>\n"
        f"{detail}"
    )
    try:
        payload = json.dumps(
            {"chat_id": EDGE_OPS_CHAT_ID, "text": text, "parse_mode": "HTML"}
        ).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
        log.info("MONITOR: EdgeOps alert sent for signal %s", signal)
    except Exception as _te:
        log.warning("MONITOR: EdgeOps alert failed: %s", _te)


def signal_coach_freshness_pct() -> dict:
    """Pct of coaches.json entries stale beyond 7 days.

    Bands: GREEN ≤10%, WARN ≤25%, ALERT >25%.
    """
    try:
        from narrative_integrity_monitor import freshness_check
        result = freshness_check(max_age_days=7)
    except Exception as exc:
        log.warning("MONITOR: signal_coach_freshness_pct import error: %s", exc)
        return {
            "signal": "coach_freshness_pct",
            "value": 0.0,
            "band": "GREEN",
            "breach": 0,
            "details": json.dumps({"error": str(exc)}),
        }

    checked = result.get("checked", 0)
    stale = len(result.get("stale", []))
    missing = len(result.get("missing", []))

    if checked == 0:
        pct = 0.0
    else:
        pct = round((stale + missing) / checked * 100, 2)

    if pct <= 10:
        band = "GREEN"
    elif pct <= 25:
        band = "WARN"
    else:
        band = "ALERT"

    return {
        "signal": "coach_freshness_pct",
        "value": pct,
        "band": band,
        "breach": 1 if band == "ALERT" else 0,
        "details": json.dumps(
            {"stale": stale, "missing": missing, "checked": checked, "pct": pct}
        ),
    }


def signal_bot_coaches_sync() -> dict:
    """Mismatch count between bot/data/coaches.json and scrapers/coaches.json.

    Bands: GREEN = 0 mismatches, ALERT ≥ 1.
    """
    try:
        from narrative_integrity_monitor import bot_coaches_sync_check
        result = bot_coaches_sync_check()
    except Exception as exc:
        log.warning("MONITOR: signal_bot_coaches_sync import error: %s", exc)
        return {
            "signal": "bot_coaches_sync",
            "value": 0.0,
            "band": "GREEN",
            "breach": 0,
            "details": json.dumps({"error": str(exc)}),
        }

    mismatches = len(result.get("mismatches", []))
    band = "GREEN" if mismatches == 0 else "ALERT"

    return {
        "signal": "bot_coaches_sync",
        "value": float(mismatches),
        "band": band,
        "breach": 1 if band == "ALERT" else 0,
        "details": json.dumps({"mismatches": mismatches, "ok": result.get("ok", True)}),
    }


# SIGNAL_FNS: new-style signals that return {signal, value, band, breach, details}
# Appended to run_monitor() after the existing 9 integer signals.
SIGNAL_FNS = [
    signal_coach_freshness_pct,
    signal_bot_coaches_sync,
]


# ── Health-alerts integration ──────────────────────────────────────────────────

def _last_ha_fired_at(conn: sqlite3.Connection, signal: str) -> datetime | None:
    """Return fired_at of the most recent open health_alert for this signal, or None."""
    try:
        row = conn.execute(
            "SELECT fired_at FROM health_alerts "
            "WHERE source_id=? AND alert_type='quality_signal' "
            "AND resolved_at IS NULL "
            "AND json_extract(meta, '$.signal_name') = ? "
            "ORDER BY fired_at DESC LIMIT 1",
            (_SOURCE_ID, signal),
        ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    try:
        ts = row[0]
        if isinstance(ts, str):
            ts = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
    except Exception:
        return None


def _ha_debounced(conn: sqlite3.Connection, signal: str) -> bool:
    """Return True if an open health_alert for this signal was fired within _DEBOUNCE_HOURS."""
    last = _last_ha_fired_at(conn, signal)
    if last is None:
        return False
    now = datetime.now(tz=timezone.utc)
    return (now - last) < timedelta(hours=_DEBOUNCE_HOURS)


def _insert_health_alert(
    conn: sqlite3.Connection,
    signal: str,
    value,
    severity: str,
    message: str,
    meta: dict | None = None,
    dry_run: bool = False,
) -> None:
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    meta_str = json.dumps(meta) if meta else None
    try:
        conn.execute(
            "INSERT INTO health_alerts "
            "(source_id, alert_type, severity, message, fired_at, telegram_sent, meta) "
            "VALUES (?, 'quality_signal', ?, ?, ?, 0, ?)",
            (_SOURCE_ID, severity, message, now_iso, meta_str),
        )
        conn.commit()
        log.info("MONITOR: inserted health_alert signal=%s severity=%s", signal, severity)
    except Exception as _e:
        log.warning("MONITOR: failed to insert health_alert for %s: %s", signal, _e)


def _fire_cycle_alerts(
    conn: sqlite3.Connection,
    cycle_signals: list[dict],
    dry_run: bool = False,
) -> None:
    """Insert health_alerts rows + send EdgeOps for every ALERT+breach signal in this cycle."""
    now_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    for sig in cycle_signals:
        signal_name = sig.get("signal", "")
        band = sig.get("band", "GREEN")
        breach = sig.get("breach", 0)
        value = sig.get("value", 0)
        if band != "ALERT" or not breach:
            continue
        if _ha_debounced(conn, signal_name):
            log.info("MONITOR: %s ALERT debounced — open health_alert <2h old", signal_name)
            continue
        severity = _severity_for(signal_name)
        message = f"Narrative signal {signal_name} breached ALERT threshold — value={value}"
        meta = {"signal_name": signal_name, "value": value, "band": band, "fired_ts": now_str}
        _insert_health_alert(conn, signal_name, value, severity, message, meta, dry_run=dry_run)
        detail = (
            f"Severity: <b>{severity}</b>\n"
            f"Band: ALERT\n"
            f"Detected at: {now_str}"
        )
        if not dry_run:
            _send_edgeops_alert(signal_name, value, detail)
            if _sentry:
                _sentry.capture_message(
                    f"narrative_integrity: {signal_name} ALERT — value={value}",
                    level="error" if severity == "critical" else "warning",
                )
        else:
            log.info("DRY-RUN: would send EdgeOps alert signal=%s value=%s", signal_name, value)


def _auto_resolve_alerts(
    conn: sqlite3.Connection,
    cycle_signals: list[dict],
    dry_run: bool = False,
) -> None:
    """Resolve open health_alerts rows whose signal returned to GREEN or WARN this cycle."""
    try:
        open_rows = conn.execute(
            "SELECT id, meta FROM health_alerts "
            "WHERE source_id=? AND alert_type='quality_signal' AND resolved_at IS NULL",
            (_SOURCE_ID,),
        ).fetchall()
    except Exception as _e:
        log.warning("MONITOR: _auto_resolve_alerts query failed: %s", _e)
        return

    signal_bands = {s.get("signal"): s.get("band") for s in cycle_signals}
    now_iso = datetime.now(tz=timezone.utc).isoformat()

    for row_id, meta_str in open_rows:
        try:
            meta = json.loads(meta_str or "{}")
            signal_name = meta.get("signal_name") or meta.get("signal")
        except Exception:
            continue
        if not signal_name:
            continue
        band = signal_bands.get(signal_name)
        if band in ("GREEN", "WARN"):
            try:
                conn.execute(
                    "UPDATE health_alerts SET resolved_at=? WHERE id=?",
                    (now_iso, row_id),
                )
                log.info("MONITOR: resolved health_alert id=%d signal=%s band=%s", row_id, signal_name, band)
            except Exception as _e:
                log.warning("MONITOR: failed to resolve health_alert id=%d: %s", row_id, _e)

    if not dry_run:
        try:
            conn.commit()
        except Exception:
            pass


def _backfill_stale_alerts(conn: sqlite3.Connection, dry_run: bool = False) -> None:
    """Insert health_alerts for any signal stuck in ALERT+breach with no open alert row.

    Idempotent — skips signals that already have an open health_alerts row.
    Fires EdgeOps once per stale signal (debounce prevents re-fire next cycle).
    """
    try:
        stale = conn.execute("""
            SELECT n.signal, n.value, n.band, n.breach
            FROM narrative_integrity_log n
            INNER JOIN (
                SELECT signal, MAX(recorded_at) AS max_ts
                FROM narrative_integrity_log
                GROUP BY signal
            ) latest ON n.signal = latest.signal AND n.recorded_at = latest.max_ts
            WHERE n.band = 'ALERT' AND n.breach = 1
            AND n.recorded_at > datetime('now', '-2 hours')
        """).fetchall()
    except Exception as _e:
        log.warning("MONITOR: _backfill_stale_alerts query failed: %s", _e)
        return

    now_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    for signal, value, band, breach in stale:
        # Skip if already has an open health_alert
        try:
            existing = conn.execute(
                "SELECT id FROM health_alerts "
                "WHERE source_id=? AND alert_type='quality_signal' "
                "AND resolved_at IS NULL "
                "AND json_extract(meta, '$.signal_name') = ?",
                (_SOURCE_ID, signal),
            ).fetchone()
        except Exception:
            existing = None
        if existing:
            continue

        severity = _severity_for(signal)
        message = f"Narrative signal {signal} ALERT backfill — value={value} (alert missed before deploy)"
        meta = {
            "signal_name": signal,
            "value": value,
            "band": band,
            "fired_ts": now_str,
            "backfilled": True,
        }
        _insert_health_alert(conn, signal, value, severity, message, meta, dry_run=dry_run)
        if not dry_run:
            detail = (
                f"Severity: <b>{severity}</b>\n"
                f"Band: ALERT (backfilled — signal was breached before deploy)\n"
                f"Detected at: {now_str}"
            )
            _send_edgeops_alert(signal, value, detail)
        else:
            log.info("DRY-RUN: would backfill alert signal=%s value=%s severity=%s", signal, value, severity)


def run_monitor(db_path: str | None = None, dry_run: bool = False) -> dict[str, int]:
    """Run all signal checks and write results to narrative_integrity_log.

    Returns dict of {signal: value} for all signals.
    """
    path = db_path or _get_db_path()
    if not os.path.exists(path):
        log.warning("MONITOR: narrative DB not found at %s — skipping", path)
        return {}

    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    results: dict[str, int] = {}
    cycle_signals: list[dict] = []

    try:
        _ensure_integrity_log_table(conn)

        # Backfill any stale ALERT signals not yet in health_alerts
        _backfill_stale_alerts(conn, dry_run=dry_run)

        cutoff_24h = (
            datetime.now(tz=timezone.utc) - timedelta(hours=24)
        ).isoformat()

        # ── Signal 1: total_narratives_24h ────────────────────────────────────
        row = conn.execute(
            "SELECT COUNT(*) FROM narrative_cache WHERE created_at >= ?",
            (cutoff_24h,),
        ).fetchone()
        sig1_val = int(row[0]) if row else 0
        band1, breach1 = _compute_int_band("total_narratives_24h", sig1_val)
        _write_signal(conn, "total_narratives_24h", sig1_val, band1, breach1)
        results["total_narratives_24h"] = sig1_val
        cycle_signals.append({"signal": "total_narratives_24h", "value": sig1_val, "band": band1, "breach": breach1})

        # ── Signal 2: w84_rate_24h ─────────────────────────────────────────
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
        band2, breach2 = _compute_int_band("w84_rate_24h", sig2_val)
        _write_signal(conn, "w84_rate_24h", sig2_val, band2, breach2)
        results["w84_rate_24h"] = sig2_val
        cycle_signals.append({"signal": "w84_rate_24h", "value": sig2_val, "band": band2, "breach": breach2})

        # ── Signal 3: w82_fallback_count_24h ─────────────────────────────────
        row3 = conn.execute(
            "SELECT COUNT(*) FROM narrative_cache "
            "WHERE created_at >= ? AND narrative_source = 'w82'",
            (cutoff_24h,),
        ).fetchone()
        sig3_val = int(row3[0]) if row3 else 0
        band3, breach3 = _compute_int_band("w82_fallback_count_24h", sig3_val)
        _write_signal(conn, "w82_fallback_count_24h", sig3_val, band3, breach3)
        results["w82_fallback_count_24h"] = sig3_val
        cycle_signals.append({"signal": "w82_fallback_count_24h", "value": sig3_val, "band": band3, "breach": breach3})

        # ── Signal 4: empty_verdict_count_24h ────────────────────────────────
        row4 = conn.execute(
            "SELECT COUNT(*) FROM narrative_cache "
            "WHERE created_at >= ? AND (verdict_html IS NULL OR verdict_html = '')",
            (cutoff_24h,),
        ).fetchone()
        sig4_val = int(row4[0]) if row4 else 0
        band4, breach4 = _compute_int_band("empty_verdict_count_24h", sig4_val)
        _write_signal(conn, "empty_verdict_count_24h", sig4_val, band4, breach4)
        results["empty_verdict_count_24h"] = sig4_val
        cycle_signals.append({"signal": "empty_verdict_count_24h", "value": sig4_val, "band": band4, "breach": breach4})

        # ── Signal 5: low_quality_verdict_count ──────────────────────────────
        # EDGE-CARD-INJURY-TO-MYMATCHES-01 suppression — remove after 2026-04-17
        import datetime as _dt
        _suppression_end = _dt.datetime(2026, 4, 17, 23, 59, tzinfo=_dt.timezone(
            _dt.timedelta(hours=2)
        ))
        _now_sast = _dt.datetime.now(tz=_dt.timezone(_dt.timedelta(hours=2)))
        if _now_sast < _suppression_end:
            sig5_val = 0
        else:
            from narrative_spec import min_verdict_quality
            rows5 = conn.execute(
                "SELECT verdict_html FROM narrative_cache "
                "WHERE created_at >= ? AND verdict_html IS NOT NULL AND verdict_html != ''",
                (cutoff_24h,),
            ).fetchall()
            sig5_val = sum(
                1 for r in rows5 if not min_verdict_quality(r["verdict_html"])
            )
        band5, breach5 = _compute_int_band("low_quality_verdict_count", sig5_val)
        _write_signal(conn, "low_quality_verdict_count", sig5_val, band5, breach5)
        results["low_quality_verdict_count"] = sig5_val
        cycle_signals.append({"signal": "low_quality_verdict_count", "value": sig5_val, "band": band5, "breach": breach5})

        # ── Signal 6a: gold_edge_sonnet_fallback_rate (warn) ─────────────────
        # Percentage of Gold/Diamond edges served via W82 baseline (Sonnet polish
        # failed or skipped). Moderate W82 fallback is acceptable — alert only
        # when it dominates. Warn threshold: >60% in last 24h.
        _gd_total = conn.execute(
            "SELECT COUNT(*) FROM narrative_cache "
            "WHERE created_at >= ? AND edge_tier IN ('gold','diamond')",
            (cutoff_24h,),
        ).fetchone()
        _gd_total_count = int(_gd_total[0]) if _gd_total else 0
        _gd_non_sonnet = conn.execute(
            "SELECT COUNT(*) FROM narrative_cache "
            "WHERE created_at >= ? "
            "AND edge_tier IN ('gold','diamond') "
            "AND narrative_source NOT IN ('w84','w84_retry','w84_quality_retry')",
            (cutoff_24h,),
        ).fetchone()
        _gd_non_sonnet_count = int(_gd_non_sonnet[0]) if _gd_non_sonnet else 0
        sig6a_val = (
            int(100 * _gd_non_sonnet_count / _gd_total_count)
            if _gd_total_count else 0
        )
        band6a, breach6a = _compute_int_band("gold_edge_sonnet_fallback_rate", sig6a_val)
        _write_signal(conn, "gold_edge_sonnet_fallback_rate", sig6a_val, band6a, breach6a)
        results["gold_edge_sonnet_fallback_rate"] = sig6a_val
        cycle_signals.append({"signal": "gold_edge_sonnet_fallback_rate", "value": sig6a_val, "band": band6a, "breach": breach6a})

        # ── Signal 6b: gold_edge_double_fail_count_24h (critical) ────────────
        # Count of Gold/Diamond edges where BOTH Sonnet attempts failed the
        # verdict quality gate. These edges are NOT served to users at all —
        # real user-harm signal. Table lives in bot's mzansiedge.db.
        _bot_db_path = os.path.join(_BOT_DIR, "data", "mzansiedge.db")
        sig6b_val = 0
        if os.path.exists(_bot_db_path):
            _cutoff_24h_sql = (
                datetime.now(tz=timezone.utc) - timedelta(hours=24)
            ).strftime("%Y-%m-%d %H:%M:%S")
            _bot_conn = sqlite3.connect(_bot_db_path, timeout=10)
            try:
                _row6b = _bot_conn.execute(
                    "SELECT COUNT(*) FROM gold_verdict_failed_edges "
                    "WHERE failed_at >= ? "
                    "AND failure_reason = 'verdict_quality_gate_double_fail'",
                    (_cutoff_24h_sql,),
                ).fetchone()
                sig6b_val = int(_row6b[0]) if _row6b else 0
            except sqlite3.OperationalError as _err:
                if "no such table" not in str(_err).lower():
                    log.warning("MONITOR: gold_verdict_failed_edges query error: %s", _err)
            finally:
                _bot_conn.close()
        band6b, breach6b = _compute_int_band("gold_edge_double_fail_count_24h", sig6b_val)
        _write_signal(conn, "gold_edge_double_fail_count_24h", sig6b_val, band6b, breach6b)
        results["gold_edge_double_fail_count_24h"] = sig6b_val
        cycle_signals.append({"signal": "gold_edge_double_fail_count_24h", "value": sig6b_val, "band": band6b, "breach": breach6b})

        # ── Signal 7: validator_reject_rate ──────────────────────────────────
        _v_attempts = conn.execute(
            "SELECT COUNT(*) FROM narrative_integrity_log "
            "WHERE signal = 'validator_attempt' AND recorded_at >= ?",
            (cutoff_24h,),
        ).fetchone()
        _v_attempts_count = int(_v_attempts[0]) if _v_attempts else 0
        _v_rejects = conn.execute(
            "SELECT COUNT(*) FROM narrative_integrity_log "
            "WHERE signal = 'validator_rejection' AND recorded_at >= ?",
            (cutoff_24h,),
        ).fetchone()
        _v_rejects_count = int(_v_rejects[0]) if _v_rejects else 0
        sig7_val = int(100 * _v_rejects_count / _v_attempts_count) if _v_attempts_count else 0
        band7, breach7 = _compute_int_band("validator_reject_rate", sig7_val)
        _write_signal(conn, "validator_reject_rate", sig7_val, band7, breach7)
        results["validator_reject_rate"] = sig7_val
        cycle_signals.append({"signal": "validator_reject_rate", "value": sig7_val, "band": band7, "breach": breach7})

        # ── Signal 8: banned_template_hit_rate ───────────────────────────────
        _bt_hits = conn.execute(
            "SELECT COUNT(*) FROM narrative_integrity_log "
            "WHERE signal = 'banned_template_hit' AND recorded_at >= ?",
            (cutoff_24h,),
        ).fetchone()
        _bt_hits_count = int(_bt_hits[0]) if _bt_hits else 0
        sig8_val = int(100 * _bt_hits_count / _v_attempts_count) if _v_attempts_count else 0
        band8, breach8 = _compute_int_band("banned_template_hit_rate", sig8_val)
        _write_signal(conn, "banned_template_hit_rate", sig8_val, band8, breach8)
        results["banned_template_hit_rate"] = sig8_val
        cycle_signals.append({"signal": "banned_template_hit_rate", "value": sig8_val, "band": band8, "breach": breach8})

        # ── Signal 9: manager_name_fabrication_attempts ───────────────────────
        _mgr_fab = conn.execute(
            "SELECT COUNT(*) FROM narrative_integrity_log "
            "WHERE signal = 'manager_name_fabrication_attempt' AND recorded_at >= ?",
            (cutoff_24h,),
        ).fetchone()
        sig9_val = int(_mgr_fab[0]) if _mgr_fab else 0
        band9, breach9 = _compute_int_band("manager_name_fabrication_attempts", sig9_val)
        _write_signal(conn, "manager_name_fabrication_attempts", sig9_val, band9, breach9)
        results["manager_name_fabrication_attempts"] = sig9_val
        cycle_signals.append({"signal": "manager_name_fabrication_attempts", "value": sig9_val, "band": band9, "breach": breach9})

        # ── Coach freshness signals (BUILD-COACHES-MONITOR-WIRE-01) ─────────
        for fn in SIGNAL_FNS:
            sig = fn()
            signal_name = sig["signal"]
            sig_int = int(round(sig["value"]))
            _write_signal(conn, signal_name, sig_int, sig["band"], sig["breach"])
            results[signal_name] = sig_int
            cycle_signals.append(sig)

        # ── Unified alerter (BUILD-NARRATIVE-ALERT-WIRE-01) ─────────────────
        _fire_cycle_alerts(conn, cycle_signals, dry_run=dry_run)
        _auto_resolve_alerts(conn, cycle_signals, dry_run=dry_run)

    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            log.info("MONITOR: narrative_cache table missing — nothing to check")
        else:
            log.warning("MONITOR: DB error: %s", exc)
    finally:
        conn.close()

    return results


if __name__ == "__main__":
    _dry_run = "--dry-run" in sys.argv
    if _dry_run:
        logging.basicConfig(level=logging.INFO)
        log.info("DRY-RUN mode — no DB writes, no Telegram messages")
    results = run_monitor(dry_run=_dry_run)
    print(json.dumps(results, indent=2))
    distinct = len(results)
    print(f"\nDistinct signals: {distinct}")
    if _dry_run:
        print("(dry-run — no alerts fired, no health_alerts rows inserted)")
