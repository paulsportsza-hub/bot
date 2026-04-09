"""Contract tests for P2-03 BUILD-MONITORING-ALERTS — health_alerter.py.

Tests:
- Alert trigger logic (stale/error alerts fire for pending status_degraded rows)
- Dedup logic (same source not alerted twice within 2 hours)
- Recovery detection (stale/error → healthy triggers recovery alert)
- Daily summary format and gate (07:00 SAST, once per day)
- Quota alert format (>= threshold)
- W81-DBLOCK: no raw sqlite3.connect() calls

Run via:
    bash /home/paulsportsza/bot/scripts/qa_safe.sh contracts
"""
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

sys.path.insert(0, '/home/paulsportsza')
sys.path.insert(0, '/home/paulsportsza/scripts')

import health_alerter as ha


# ---------------------------------------------------------------------------
# DB helper — uses migration module (same as test_health_checker.py)
# ---------------------------------------------------------------------------

def _make_db(tmp_path):
    """Create a temp DB via health_schema_migration (proven + idempotent)."""
    import health_schema_migration as mig
    db_path = str(tmp_path / "test_alerts.db")
    orig = mig.ODDS_DB
    mig.ODDS_DB = db_path
    try:
        mig.run_migration()
    finally:
        mig.ODDS_DB = orig
    return db_path


def _open(db_path):
    """Open test DB via approved factory."""
    from scrapers.db_connect import connect_odds_db
    return connect_odds_db(db_path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _ts_ago(minutes: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


# ---------------------------------------------------------------------------
# Test 1 — W81-DBLOCK: no raw sqlite3.connect() in health_alerter.py
# ---------------------------------------------------------------------------

def test_alerter_no_raw_sqlite():
    """health_alerter.py must never call sqlite3.connect() directly."""
    alerter_path = '/home/paulsportsza/scripts/health_alerter.py'
    with open(alerter_path) as f:
        source = f.read()
    lines = source.split('\n')
    violations = []
    for i, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if stripped.startswith('#'):
            continue
        if 'sqlite3.connect(' in line:
            violations.append(f"Line {i}: {line.rstrip()}")
    assert not violations, (
        "W81-DBLOCK violation in health_alerter.py:\n" + '\n'.join(violations)
    )


# ---------------------------------------------------------------------------
# Test 2 — Alert fires for a pending stale source
# ---------------------------------------------------------------------------

def test_alert_fires_for_pending_stale(tmp_path):
    """When a pending status_degraded alert exists, _fire_stale_error_alerts sends it."""
    db_path = _make_db(tmp_path)
    conn = _open(db_path)

    # Simulate health_checker inserting a degradation alert
    conn.execute("""
        INSERT INTO health_alerts
            (source_id, alert_type, severity, message, fired_at, telegram_sent)
        VALUES ('bk_hollywoodbets', 'status_degraded', 'warning', 'degraded', ?, 0)
    """, (_ts_ago(5),))
    # Update current status to red
    conn.execute(
        "UPDATE source_health_current SET status='red', last_success_at=? "
        "WHERE source_id='bk_hollywoodbets'",
        (_ts_ago(300),)
    )
    conn.commit()

    sent_messages = []
    with patch.object(ha, '_send_telegram', side_effect=lambda t: sent_messages.append(t) or True):
        with conn:
            count = ha._fire_stale_error_alerts(conn)

    conn.close()
    assert count == 1, f"Expected 1 alert sent, got {count}"
    assert len(sent_messages) == 1
    msg = sent_messages[0]
    assert 'STALE' in msg, f"Expected 'STALE' in message: {msg}"
    assert 'Hollywoodbets' in msg, f"Expected source name in message: {msg}"
    assert 'Category:' in msg, f"Expected 'Category:' in message: {msg}"
    assert 'Threshold:' in msg, f"Expected 'Threshold:' in message: {msg}"


# ---------------------------------------------------------------------------
# Test 3 — Alert format matches AC-3 spec
# ---------------------------------------------------------------------------

def test_alert_format_matches_spec(tmp_path):
    """Alert text must match: ⚠️ STALE: {source_name} — Last update {time_ago}. Threshold: {threshold}. Category: {cat}."""
    db_path = _make_db(tmp_path)
    conn = _open(db_path)

    conn.execute("""
        INSERT INTO health_alerts
            (source_id, alert_type, severity, message, fired_at, telegram_sent)
        VALUES ('bk_hollywoodbets', 'status_degraded', 'warning', 'degraded', ?, 0)
    """, (_ts_ago(5),))
    conn.execute(
        "UPDATE source_health_current SET status='red', last_success_at=? "
        "WHERE source_id='bk_hollywoodbets'",
        (_ts_ago(240),)  # 4 hours ago
    )
    conn.commit()

    sent_messages = []
    with patch.object(ha, '_send_telegram', side_effect=lambda t: sent_messages.append(t) or True):
        with conn:
            ha._fire_stale_error_alerts(conn)

    conn.close()
    assert sent_messages, "No message was sent"
    msg = sent_messages[0]
    # Must contain all required parts
    assert '⚠️' in msg
    assert 'STALE' in msg or 'ERROR' in msg
    assert 'Hollywoodbets' in msg
    assert 'Last update' in msg
    assert 'Threshold:' in msg
    assert 'Category:' in msg
    assert msg.rstrip().endswith('.')


# ---------------------------------------------------------------------------
# Test 4 — Black (dead) sources get ERROR tag
# ---------------------------------------------------------------------------

def test_error_tag_for_black_status(tmp_path):
    """Sources with status='black' should get the ERROR tag in the alert."""
    db_path = _make_db(tmp_path)
    conn = _open(db_path)

    # Use a critical=1 source so _fire_stale_error_alerts does not silently discard it.
    # news_psl is marked critical=0 in health_schema_migration — use bk_hollywoodbets instead.
    conn.execute("""
        INSERT INTO health_alerts
            (source_id, alert_type, severity, message, fired_at, telegram_sent)
        VALUES ('bk_hollywoodbets', 'status_degraded', 'critical', 'dead', ?, 0)
    """, (_ts_ago(5),))
    conn.execute(
        "UPDATE source_health_current SET status='black' WHERE source_id='bk_hollywoodbets'"
    )
    conn.commit()

    sent_messages = []
    with patch.object(ha, '_send_telegram', side_effect=lambda t: sent_messages.append(t) or True):
        with conn:
            ha._fire_stale_error_alerts(conn)

    conn.close()
    assert sent_messages
    assert 'ERROR' in sent_messages[0], f"Expected 'ERROR' for black source: {sent_messages[0]}"


# ---------------------------------------------------------------------------
# Test 5 — Dedup: same source not alerted twice within 2 hours
# ---------------------------------------------------------------------------

def test_dedup_within_2h(tmp_path):
    """Same source not alerted twice within 2 hours."""
    db_path = _make_db(tmp_path)
    conn = _open(db_path)

    # Insert a pending alert that was already sent 30 min ago (within dedup window)
    conn.execute("""
        INSERT INTO health_alerts
            (source_id, alert_type, severity, message, fired_at, telegram_sent)
        VALUES ('bk_hollywoodbets', 'status_degraded', 'warning', 'sent 30m ago', ?, 1)
    """, (_ts_ago(30),))
    # New pending alert
    conn.execute("""
        INSERT INTO health_alerts
            (source_id, alert_type, severity, message, fired_at, telegram_sent)
        VALUES ('bk_hollywoodbets', 'status_degraded', 'warning', 'new pending', ?, 0)
    """, (_ts_ago(1),))
    conn.execute(
        "UPDATE source_health_current SET status='red', last_success_at=? "
        "WHERE source_id='bk_hollywoodbets'",
        (_ts_ago(300),)
    )
    conn.commit()

    sent_messages = []
    with patch.object(ha, '_send_telegram', side_effect=lambda t: sent_messages.append(t) or True):
        with conn:
            count = ha._fire_stale_error_alerts(conn)

    conn.close()
    assert count == 0, f"Should be deduped (0 sent), got {count}"
    assert len(sent_messages) == 0


# ---------------------------------------------------------------------------
# Test 6 — Dedup expires after 2 hours
# ---------------------------------------------------------------------------

def test_dedup_expires_after_2h(tmp_path):
    """Alert fires again after 2-hour dedup window has passed."""
    db_path = _make_db(tmp_path)
    conn = _open(db_path)

    # Last alert was 3 hours ago (outside dedup window)
    conn.execute("""
        INSERT INTO health_alerts
            (source_id, alert_type, severity, message, fired_at, telegram_sent)
        VALUES ('bk_hollywoodbets', 'status_degraded', 'warning', 'old', ?, 1)
    """, (_ts_ago(180),))
    # New pending alert
    conn.execute("""
        INSERT INTO health_alerts
            (source_id, alert_type, severity, message, fired_at, telegram_sent)
        VALUES ('bk_hollywoodbets', 'status_degraded', 'warning', 'new pending', ?, 0)
    """, (_ts_ago(1),))
    conn.execute(
        "UPDATE source_health_current SET status='red', last_success_at=? "
        "WHERE source_id='bk_hollywoodbets'",
        (_ts_ago(300),)
    )
    conn.commit()

    sent_messages = []
    with patch.object(ha, '_send_telegram', side_effect=lambda t: sent_messages.append(t) or True):
        with conn:
            count = ha._fire_stale_error_alerts(conn)

    conn.close()
    assert count == 1, f"Expected 1 alert sent after dedup expiry, got {count}"


# ---------------------------------------------------------------------------
# Test 7 — Recovery alert fires when source returns to healthy
# ---------------------------------------------------------------------------

def test_recovery_alert_fires(tmp_path):
    """Recovery alert sent when source returns to green after a stale alert."""
    db_path = _make_db(tmp_path)
    conn = _open(db_path)

    # Source had a stale alert that was sent (telegram_sent=1) but not resolved
    conn.execute("""
        INSERT INTO health_alerts
            (source_id, alert_type, severity, message, fired_at, telegram_sent)
        VALUES ('bk_hollywoodbets', 'status_degraded', 'warning', 'was stale', ?, 1)
    """, (_ts_ago(60),))
    # Source is now back to green
    conn.execute(
        "UPDATE source_health_current SET status='green' WHERE source_id='bk_hollywoodbets'"
    )
    conn.commit()

    sent_messages = []
    with patch.object(ha, '_send_telegram', side_effect=lambda t: sent_messages.append(t) or True):
        with conn:
            count = ha._fire_recovery_alerts(conn)

    conn.close()
    assert count == 1, f"Expected 1 recovery alert, got {count}"
    assert len(sent_messages) == 1
    msg = sent_messages[0]
    assert 'RECOVERED' in msg, f"Expected 'RECOVERED' in message: {msg}"
    assert 'Hollywoodbets' in msg
    assert 'Back online' in msg


# ---------------------------------------------------------------------------
# Test 8 — Recovery format matches AC-5 spec
# ---------------------------------------------------------------------------

def test_recovery_format_matches_spec(tmp_path):
    """Recovery text: ✅ RECOVERED: {source_name} — Back online."""
    db_path = _make_db(tmp_path)
    conn = _open(db_path)

    conn.execute("""
        INSERT INTO health_alerts
            (source_id, alert_type, severity, message, fired_at, telegram_sent)
        VALUES ('sharp_odds_api', 'status_degraded', 'warning', 'was stale', ?, 1)
    """, (_ts_ago(30),))
    conn.execute(
        "UPDATE source_health_current SET status='yellow' WHERE source_id='sharp_odds_api'"
    )
    conn.commit()

    sent_messages = []
    with patch.object(ha, '_send_telegram', side_effect=lambda t: sent_messages.append(t) or True):
        with conn:
            ha._fire_recovery_alerts(conn)

    conn.close()
    assert sent_messages
    msg = sent_messages[0]
    assert '✅' in msg
    assert 'RECOVERED' in msg
    assert 'The Odds API' in msg
    assert 'Back online' in msg


# ---------------------------------------------------------------------------
# Test 9 — Recovery not sent when source was never alerted
# ---------------------------------------------------------------------------

def test_recovery_not_sent_without_prior_alert(tmp_path):
    """No recovery alert for sources that never had a stale alert."""
    db_path = _make_db(tmp_path)
    conn = _open(db_path)
    # All sources are green with no prior alerts
    conn.commit()

    sent_messages = []
    with patch.object(ha, '_send_telegram', side_effect=lambda t: sent_messages.append(t) or True):
        with conn:
            count = ha._fire_recovery_alerts(conn)

    conn.close()
    assert count == 0
    assert len(sent_messages) == 0


# ---------------------------------------------------------------------------
# Test 10 — Recovery resolves the open alert (sets resolved_at)
# ---------------------------------------------------------------------------

def test_recovery_resolves_open_alert(tmp_path):
    """Recovery processing must set resolved_at on the stale alert."""
    db_path = _make_db(tmp_path)
    conn = _open(db_path)

    conn.execute("""
        INSERT INTO health_alerts
            (source_id, alert_type, severity, message, fired_at, telegram_sent)
        VALUES ('bk_hollywoodbets', 'status_degraded', 'warning', 'was stale', ?, 1)
    """, (_ts_ago(60),))
    conn.execute(
        "UPDATE source_health_current SET status='green' WHERE source_id='bk_hollywoodbets'"
    )
    conn.commit()

    with patch.object(ha, '_send_telegram', return_value=True):
        with conn:
            ha._fire_recovery_alerts(conn)
        conn.commit()

    row = conn.execute(
        "SELECT resolved_at FROM health_alerts "
        "WHERE source_id='bk_hollywoodbets' AND alert_type='status_degraded'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] is not None, "resolved_at should be set after recovery"


# ---------------------------------------------------------------------------
# Test 11 — Daily summary format matches AC-7 spec
# ---------------------------------------------------------------------------

def test_daily_summary_format(tmp_path):
    """Daily summary: 📊 Health Summary — {N} healthy, {M} stale, {K} error"""
    db_path = _make_db(tmp_path)
    conn = _open(db_path)

    # Reset all sources to green, then set specific statuses for 3 sources
    conn.execute("UPDATE source_health_current SET status='green'")
    conn.execute(
        "UPDATE source_health_current SET status='green' WHERE source_id='bk_hollywoodbets'"
    )
    conn.execute(
        "UPDATE source_health_current SET status='green' WHERE source_id='sharp_odds_api'"
    )
    conn.execute(
        "UPDATE source_health_current SET status='red' WHERE source_id='news_psl'"
    )
    conn.commit()

    # Use 07:00 SAST to pass the hour gate
    now_sast = datetime(2026, 4, 5, 7, 15, tzinfo=timezone.utc)

    sent_messages = []
    with patch.object(ha, '_send_telegram', side_effect=lambda t: sent_messages.append(t) or True):
        with conn:
            count = ha._fire_daily_summary(conn, now_sast=now_sast)

    conn.close()
    assert count == 1
    assert len(sent_messages) == 1
    msg = sent_messages[0]
    assert '📊' in msg
    assert 'Health Summary' in msg
    assert 'healthy' in msg
    assert 'stale' in msg
    assert 'error' in msg
    # 41 green = healthy, 1 red = stale, 0 black = error
    assert '41 healthy' in msg
    assert '1 stale' in msg
    assert '0 error' in msg


# ---------------------------------------------------------------------------
# Test 12 — Daily summary only fires at 07:00 SAST
# ---------------------------------------------------------------------------

def test_daily_summary_not_sent_outside_hour(tmp_path):
    """Daily summary should NOT send at hours other than 07:00 SAST."""
    db_path = _make_db(tmp_path)
    conn = _open(db_path)
    conn.commit()

    # 08:00 SAST — wrong hour
    now_sast = datetime(2026, 4, 5, 8, 0, tzinfo=timezone.utc)

    sent_messages = []
    with patch.object(ha, '_send_telegram', side_effect=lambda t: sent_messages.append(t) or True):
        with conn:
            count = ha._fire_daily_summary(conn, now_sast=now_sast)

    conn.close()
    assert count == 0
    assert len(sent_messages) == 0


# ---------------------------------------------------------------------------
# Test 13 — Daily summary not sent twice on the same day
# ---------------------------------------------------------------------------

def test_daily_summary_not_sent_twice(tmp_path):
    """Daily summary sent at most once per SAST day."""
    db_path = _make_db(tmp_path)
    conn = _open(db_path)
    conn.commit()

    now_sast = datetime(2026, 4, 5, 7, 0, tzinfo=timezone.utc)

    sent_messages = []
    with patch.object(ha, '_send_telegram', side_effect=lambda t: sent_messages.append(t) or True):
        with conn:
            count1 = ha._fire_daily_summary(conn, now_sast=now_sast)
        with conn:
            count2 = ha._fire_daily_summary(conn, now_sast=now_sast)

    conn.close()
    assert count1 == 1, "First send should succeed"
    assert count2 == 0, "Second send same day should be blocked"
    assert len(sent_messages) == 1


# ---------------------------------------------------------------------------
# Test 14 — Quota alert fires when pct_used >= threshold
# ---------------------------------------------------------------------------

def test_quota_alert_fires_above_threshold(tmp_path):
    """Quota alert fires when pct_used >= alert_threshold."""
    db_path = _make_db(tmp_path)
    conn = _open(db_path)

    conn.execute("""
        INSERT INTO api_quota_tracking
            (api_name, checked_at, credits_used, credits_limit, credits_remaining,
             period, pct_used, alert_threshold)
        VALUES ('the_odds_api', ?, 16500, 20000, 3500, 'month', 82.5, 80.0)
    """, (_now_iso(),))
    conn.commit()

    sent_messages = []
    with patch.object(ha, '_send_telegram', side_effect=lambda t: sent_messages.append(t) or True):
        with conn:
            count = ha._fire_quota_alerts(conn)

    conn.close()
    assert count == 1
    assert len(sent_messages) == 1
    msg = sent_messages[0]
    assert '⚠️' in msg
    assert 'QUOTA' in msg
    assert 'the_odds_api' in msg
    assert '82.5%' in msg
    assert '3500' in msg


# ---------------------------------------------------------------------------
# Test 15 — Quota alert format matches AC-9 spec
# ---------------------------------------------------------------------------

def test_quota_alert_format(tmp_path):
    """Quota text: ⚠️ QUOTA: {source} at {pct}% — {remaining} calls left"""
    db_path = _make_db(tmp_path)
    conn = _open(db_path)

    conn.execute("""
        INSERT INTO api_quota_tracking
            (api_name, checked_at, credits_used, credits_limit, credits_remaining,
             period, pct_used, alert_threshold)
        VALUES ('the_odds_api', ?, 17000, 20000, 3000, 'month', 85.0, 80.0)
    """, (_now_iso(),))
    conn.commit()

    sent_messages = []
    with patch.object(ha, '_send_telegram', side_effect=lambda t: sent_messages.append(t) or True):
        with conn:
            ha._fire_quota_alerts(conn)

    conn.close()
    assert sent_messages
    msg = sent_messages[0]
    assert '⚠️' in msg
    assert 'QUOTA' in msg
    assert 'at' in msg
    assert '%' in msg
    assert 'calls left' in msg


# ---------------------------------------------------------------------------
# Test 16 — Quota alert not fired when below threshold
# ---------------------------------------------------------------------------

def test_quota_alert_not_fired_below_threshold(tmp_path):
    """Quota alert must NOT fire when pct_used < threshold."""
    db_path = _make_db(tmp_path)
    conn = _open(db_path)

    conn.execute("""
        INSERT INTO api_quota_tracking
            (api_name, checked_at, credits_used, credits_limit, credits_remaining,
             period, pct_used, alert_threshold)
        VALUES ('the_odds_api', ?, 1000, 20000, 19000, 'month', 5.0, 80.0)
    """, (_now_iso(),))
    conn.commit()

    sent_messages = []
    with patch.object(ha, '_send_telegram', side_effect=lambda t: sent_messages.append(t) or True):
        with conn:
            count = ha._fire_quota_alerts(conn)

    conn.close()
    assert count == 0
    assert len(sent_messages) == 0


# ---------------------------------------------------------------------------
# Test 17 — Quota alert deduplication
# ---------------------------------------------------------------------------

def test_quota_alert_deduped(tmp_path):
    """Quota alert deduped if same api_name already alerted within 2h."""
    db_path = _make_db(tmp_path)
    conn = _open(db_path)

    # Prior quota alert sent 30 min ago
    conn.execute("""
        INSERT INTO health_alerts
            (source_id, alert_type, severity, message, fired_at, telegram_sent)
        VALUES ('the_odds_api', 'quota_warning', 'warning', 'quota 82%', ?, 1)
    """, (_ts_ago(30),))
    # Current quota still over threshold
    conn.execute("""
        INSERT INTO api_quota_tracking
            (api_name, checked_at, credits_used, credits_limit, credits_remaining,
             period, pct_used, alert_threshold)
        VALUES ('the_odds_api', ?, 16600, 20000, 3400, 'month', 83.0, 80.0)
    """, (_now_iso(),))
    conn.commit()

    sent_messages = []
    with patch.object(ha, '_send_telegram', side_effect=lambda t: sent_messages.append(t) or True):
        with conn:
            count = ha._fire_quota_alerts(conn)

    conn.close()
    assert count == 0, "Quota alert should be deduped within 2h"


# ---------------------------------------------------------------------------
# Test 18 — run_alerts returns correct count dict
# ---------------------------------------------------------------------------

def test_run_alerts_returns_counts(tmp_path):
    """run_alerts() returns a dict with stale/recovery/quota/daily_summary keys."""
    db_path = _make_db(tmp_path)

    with patch.object(ha, '_send_telegram', return_value=True):
        result = ha.run_alerts(db_path=db_path)

    assert isinstance(result, dict)
    assert 'stale' in result
    assert 'recovery' in result
    assert 'quota' in result
    assert 'daily_summary' in result


# ---------------------------------------------------------------------------
# Test 19 — run_alerts never raises on exception
# ---------------------------------------------------------------------------

def test_run_alerts_never_raises():
    """run_alerts must not propagate exceptions — health check must complete."""
    # Pass a non-existent DB path — should log error and return counts dict
    result = ha.run_alerts(db_path='/tmp/nonexistent_test.db')
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Test 20 — Telegram send is always to EDGEOPS_CHAT_ID only (SO #20)
# ---------------------------------------------------------------------------

def test_send_targets_edgeops_only():
    """_send_telegram must only send to EDGEOPS_CHAT_ID — never @MzansiEdgeAlerts."""
    assert ha.EDGEOPS_CHAT_ID == -1003877525865, (
        "EDGEOPS_CHAT_ID has been changed — Standing Order #20 violation"
    )
    # Verify the forbidden ID is not referenced anywhere in the module code
    alerter_path = '/home/paulsportsza/scripts/health_alerter.py'
    with open(alerter_path) as f:
        source = f.read()
    # The forbidden chat ID should not appear in non-comment lines
    lines = source.split('\n')
    for i, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if stripped.startswith('#'):
            continue
        if '-1003789410835' in line:
            pytest.fail(
                f"SO #20 violation: @MzansiEdgeAlerts chat_id found at line {i}: {line}"
            )
