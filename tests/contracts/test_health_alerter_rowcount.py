"""Contract test for FIX-HEALTH-ALERTER-ROWCOUNT-01.

Verifies that _resolve_quota_alerts() uses cursor.rowcount (not conn.rowcount)
and correctly resolves open quota_warning alerts.
"""
import sqlite3
import sys
from datetime import datetime, timezone, timedelta

import pytest

sys.path.insert(0, '/home/paulsportsza/scripts')

import health_alerter as ha


def _make_mem_db():
    """In-memory SQLite with the tables _resolve_quota_alerts needs."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE health_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            fired_at TEXT NOT NULL,
            resolved_at TEXT,
            acknowledged INTEGER NOT NULL DEFAULT 0,
            telegram_sent INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE api_quota_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_name TEXT NOT NULL,
            checked_at TEXT NOT NULL,
            credits_used INTEGER,
            credits_limit INTEGER,
            credits_remaining INTEGER,
            period TEXT NOT NULL DEFAULT 'month',
            pct_used REAL,
            alert_threshold REAL NOT NULL DEFAULT 80.0,
            meta TEXT
        );
    """)
    return conn


def _now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _ts_ago(minutes):
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


class TestResolveQuotaAlerts:

    def test_no_attribute_error(self):
        """_resolve_quota_alerts must not raise AttributeError (conn.rowcount regression)."""
        conn = _make_mem_db()
        conn.execute(
            "INSERT INTO api_quota_tracking (api_name, checked_at, pct_used, alert_threshold) "
            "VALUES (?, ?, ?, ?)",
            ("openrouter", _now_iso(), 50.0, 80.0),
        )
        conn.execute(
            "INSERT INTO health_alerts (source_id, alert_type, severity, message, fired_at) "
            "VALUES (?, 'quota_warning', 'warning', 'test', ?)",
            ("openrouter", _ts_ago(30)),
        )
        conn.commit()

        try:
            result = ha._resolve_quota_alerts(conn)
        except AttributeError as exc:
            pytest.fail(f"_resolve_quota_alerts raised AttributeError: {exc}")

        assert isinstance(result, int)

    def test_resolves_alert_when_below_threshold(self):
        """Alert is resolved when pct_used drops below alert_threshold."""
        conn = _make_mem_db()
        conn.execute(
            "INSERT INTO api_quota_tracking (api_name, checked_at, pct_used, alert_threshold) "
            "VALUES (?, ?, ?, ?)",
            ("odds_api", _now_iso(), 60.0, 80.0),
        )
        conn.execute(
            "INSERT INTO health_alerts (source_id, alert_type, severity, message, fired_at) "
            "VALUES (?, 'quota_warning', 'warning', 'quota exceeded', ?)",
            ("odds_api", _ts_ago(60)),
        )
        conn.commit()

        resolved = ha._resolve_quota_alerts(conn)

        assert resolved == 1

        row = conn.execute(
            "SELECT resolved_at FROM health_alerts WHERE source_id='odds_api'"
        ).fetchone()
        assert row is not None
        assert row[0] is not None, "resolved_at should have been set"

    def test_does_not_resolve_when_above_threshold(self):
        """Alert stays open when pct_used is still >= alert_threshold."""
        conn = _make_mem_db()
        conn.execute(
            "INSERT INTO api_quota_tracking (api_name, checked_at, pct_used, alert_threshold) "
            "VALUES (?, ?, ?, ?)",
            ("betway_api", _now_iso(), 92.0, 90.0),
        )
        conn.execute(
            "INSERT INTO health_alerts (source_id, alert_type, severity, message, fired_at) "
            "VALUES (?, 'quota_warning', 'warning', 'quota exceeded', ?)",
            ("betway_api", _ts_ago(60)),
        )
        conn.commit()

        resolved = ha._resolve_quota_alerts(conn)

        assert resolved == 0

        row = conn.execute(
            "SELECT resolved_at FROM health_alerts WHERE source_id='betway_api'"
        ).fetchone()
        assert row[0] is None, "resolved_at should remain NULL when still over threshold"

    def test_no_open_alerts_returns_zero(self):
        """Returns 0 when there are no open quota_warning alerts."""
        conn = _make_mem_db()
        resolved = ha._resolve_quota_alerts(conn)
        assert resolved == 0

    def test_already_resolved_alert_not_double_resolved(self):
        """An already-resolved alert is not counted again."""
        conn = _make_mem_db()
        conn.execute(
            "INSERT INTO api_quota_tracking (api_name, checked_at, pct_used, alert_threshold) "
            "VALUES (?, ?, ?, ?)",
            ("sentry_api", _now_iso(), 40.0, 80.0),
        )
        conn.execute(
            "INSERT INTO health_alerts "
            "(source_id, alert_type, severity, message, fired_at, resolved_at) "
            "VALUES (?, 'quota_warning', 'warning', 'old', ?, ?)",
            ("sentry_api", _ts_ago(120), _ts_ago(60)),
        )
        conn.commit()

        resolved = ha._resolve_quota_alerts(conn)
        assert resolved == 0
