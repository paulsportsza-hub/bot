"""BUILD-NARRATIVE-ALERT-WIRE-01: Contract tests for narrative integrity alerter.

Tests:
- ALERT+breach signals flow into health_alerts table
- 2-hour debounce prevents duplicate inserts
- Non-ALERT signals are not inserted
- _auto_resolve_alerts resolves open rows when signal returns to GREEN/WARN
- _auto_resolve_alerts leaves rows open when signal is still ALERT
- _backfill_stale_alerts inserts for stale narrative_integrity_log ALERT rows
- _backfill_stale_alerts skips if open health_alert already exists
- dry_run writes nothing to DB
- _CRITICAL_SIGNALS contains expected entries
- severity classification (critical vs warning)

Run via:
    bash /home/paulsportsza/bot/scripts/qa_safe.sh contracts -- -k test_narrative_integrity_alerter
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

# ── Path setup ──────────────────────────────────────────────────────────────
_BOT_DIR = Path(__file__).resolve().parent.parent.parent
_SCRIPTS_DIR = _BOT_DIR / "scripts"
sys.path.insert(0, str(_BOT_DIR))
sys.path.insert(0, str(_SCRIPTS_DIR))

# ── Load module under test ──────────────────────────────────────────────────
_spec = importlib.util.spec_from_file_location(
    "monitor_narrative_integrity",
    str(_SCRIPTS_DIR / "monitor_narrative_integrity.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


# ── DB helpers ──────────────────────────────────────────────────────────────

def _make_db(tmp_path: Path) -> str:
    """Create a temp DB with both health_alerts and narrative_integrity_log tables."""
    import health_schema_migration as mig
    db_path = str(tmp_path / "test_alerter.db")
    orig = mig.ODDS_DB
    mig.ODDS_DB = db_path
    try:
        mig.run_migration()
    finally:
        mig.ODDS_DB = orig
    # Add narrative_integrity_log table
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS narrative_integrity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            signal TEXT NOT NULL,
            value REAL NOT NULL,
            band TEXT NOT NULL DEFAULT '',
            breach INTEGER NOT NULL DEFAULT 0,
            details TEXT,
            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            fixture_id TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_nil_signal_time "
        "ON narrative_integrity_log(signal, recorded_at)"
    )
    conn.commit()
    conn.close()
    return db_path


def _open(db_path: str) -> sqlite3.Connection:
    from scrapers.db_connect import connect_odds_db
    conn = connect_odds_db(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ago_iso(hours: float = 0, minutes: float = 0) -> str:
    delta = timedelta(hours=hours, minutes=minutes)
    return (datetime.now(timezone.utc) - delta).isoformat()


def _insert_nil_row(conn: sqlite3.Connection, signal: str, value: float, band: str, breach: int) -> None:
    conn.execute(
        "INSERT INTO narrative_integrity_log (signal, value, band, breach, recorded_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (signal, value, band, breach, _now_iso()),
    )
    conn.commit()


def _get_open_alerts(conn: sqlite3.Connection, signal: str) -> list:
    return conn.execute(
        "SELECT * FROM health_alerts "
        "WHERE source_id=? AND alert_type='quality_signal' AND resolved_at IS NULL "
        "AND json_extract(meta, '$.signal_name') = ?",
        (_mod._SOURCE_ID, signal),
    ).fetchall()


# ── Tests ───────────────────────────────────────────────────────────────────

class TestCriticalSignalsConstant:
    def test_critical_signals_is_frozenset(self):
        assert isinstance(_mod._CRITICAL_SIGNALS, frozenset)

    def test_expected_critical_signals_present(self):
        expected = {"sonnet_firing_rate", "staleness_pct", "empty_verdict_count_24h",
                    "gold_edge_non_sonnet_count", "manager_name_fabrication_attempts"}
        assert expected <= _mod._CRITICAL_SIGNALS

    def test_severity_for_critical(self):
        for s in _mod._CRITICAL_SIGNALS:
            assert _mod._severity_for(s) == "critical"

    def test_severity_for_warning(self):
        assert _mod._severity_for("validator_reject_rate") == "warning"
        assert _mod._severity_for("banned_template_hit_rate") == "warning"
        assert _mod._severity_for("coach_freshness_pct") == "warning"


class TestComputeIntBand:
    def test_above_threshold_is_alert(self):
        band, breach = _mod._compute_int_band("empty_verdict_count_24h", 5)
        assert band == "ALERT"
        assert breach == 1

    def test_at_threshold_is_alert(self):
        band, breach = _mod._compute_int_band("manager_name_fabrication_attempts", 1)
        assert band == "ALERT"
        assert breach == 1

    def test_below_threshold_is_green(self):
        band, breach = _mod._compute_int_band("empty_verdict_count_24h", 2)
        assert band == "GREEN"
        assert breach == 0

    def test_signal_not_in_thresholds_is_green(self):
        band, breach = _mod._compute_int_band("total_narratives_24h", 9999)
        assert band == "GREEN"
        assert breach == 0


class TestFireCycleAlerts:
    """_fire_cycle_alerts inserts health_alerts row and sends EdgeOps for ALERT+breach."""

    def test_alert_signal_inserts_health_alert(self, tmp_path):
        db_path = _make_db(tmp_path)
        conn = _open(db_path)
        cycle = [{"signal": "empty_verdict_count_24h", "value": 5, "band": "ALERT", "breach": 1}]
        with patch.object(_mod, "_send_edgeops_alert"):
            _mod._fire_cycle_alerts(conn, cycle, dry_run=False)
        rows = _get_open_alerts(conn, "empty_verdict_count_24h")
        assert len(rows) == 1
        assert rows[0]["severity"] == "critical"
        conn.close()

    def test_non_alert_signal_not_inserted(self, tmp_path):
        db_path = _make_db(tmp_path)
        conn = _open(db_path)
        cycle = [{"signal": "total_narratives_24h", "value": 10, "band": "GREEN", "breach": 0}]
        _mod._fire_cycle_alerts(conn, cycle, dry_run=False)
        rows = _get_open_alerts(conn, "total_narratives_24h")
        assert len(rows) == 0
        conn.close()

    def test_debounced_if_recent_open_alert_exists(self, tmp_path):
        db_path = _make_db(tmp_path)
        conn = _open(db_path)
        # Pre-insert a fresh open alert
        conn.execute(
            "INSERT INTO health_alerts (source_id, alert_type, severity, message, fired_at, meta) "
            "VALUES (?, 'quality_signal', 'warning', 'test', ?, ?)",
            (_mod._SOURCE_ID, _ago_iso(minutes=30), json.dumps({"signal_name": "validator_reject_rate"})),
        )
        conn.commit()
        cycle = [{"signal": "validator_reject_rate", "value": 50, "band": "ALERT", "breach": 1}]
        with patch.object(_mod, "_send_edgeops_alert") as mock_send:
            _mod._fire_cycle_alerts(conn, cycle, dry_run=False)
        # Should not fire again (debounced)
        mock_send.assert_not_called()
        rows = _get_open_alerts(conn, "validator_reject_rate")
        assert len(rows) == 1  # still just the original row
        conn.close()

    def test_fires_after_debounce_window(self, tmp_path):
        db_path = _make_db(tmp_path)
        conn = _open(db_path)
        # Old open alert (3 hours ago — outside debounce window)
        conn.execute(
            "INSERT INTO health_alerts (source_id, alert_type, severity, message, fired_at, meta) "
            "VALUES (?, 'quality_signal', 'warning', 'test', ?, ?)",
            (_mod._SOURCE_ID, _ago_iso(hours=3), json.dumps({"signal_name": "validator_reject_rate"})),
        )
        conn.commit()
        cycle = [{"signal": "validator_reject_rate", "value": 50, "band": "ALERT", "breach": 1}]
        with patch.object(_mod, "_send_edgeops_alert"):
            _mod._fire_cycle_alerts(conn, cycle, dry_run=False)
        rows = _get_open_alerts(conn, "validator_reject_rate")
        assert len(rows) == 2  # new row inserted
        conn.close()

    def test_warning_severity_for_non_critical_signal(self, tmp_path):
        db_path = _make_db(tmp_path)
        conn = _open(db_path)
        cycle = [{"signal": "validator_reject_rate", "value": 35, "band": "ALERT", "breach": 1}]
        with patch.object(_mod, "_send_edgeops_alert"):
            _mod._fire_cycle_alerts(conn, cycle, dry_run=False)
        rows = _get_open_alerts(conn, "validator_reject_rate")
        assert len(rows) == 1
        assert rows[0]["severity"] == "warning"
        conn.close()

    def test_dry_run_inserts_nothing(self, tmp_path):
        db_path = _make_db(tmp_path)
        conn = _open(db_path)
        cycle = [{"signal": "empty_verdict_count_24h", "value": 5, "band": "ALERT", "breach": 1}]
        with patch.object(_mod, "_send_edgeops_alert") as mock_send:
            _mod._fire_cycle_alerts(conn, cycle, dry_run=True)
        rows = _get_open_alerts(conn, "empty_verdict_count_24h")
        assert len(rows) == 0
        mock_send.assert_not_called()
        conn.close()


class TestAutoResolveAlerts:
    """_auto_resolve_alerts closes health_alerts rows when signal returns to GREEN/WARN."""

    def _insert_open_alert(self, conn: sqlite3.Connection, signal: str) -> int:
        conn.execute(
            "INSERT INTO health_alerts (source_id, alert_type, severity, message, fired_at, meta) "
            "VALUES (?, 'quality_signal', 'warning', 'test', ?, ?)",
            (_mod._SOURCE_ID, _ago_iso(hours=1), json.dumps({"signal_name": signal})),
        )
        conn.commit()
        return conn.execute(
            "SELECT id FROM health_alerts WHERE source_id=? AND alert_type='quality_signal' "
            "ORDER BY id DESC LIMIT 1",
            (_mod._SOURCE_ID,),
        ).fetchone()[0]

    def test_resolves_when_signal_returns_green(self, tmp_path):
        db_path = _make_db(tmp_path)
        conn = _open(db_path)
        row_id = self._insert_open_alert(conn, "empty_verdict_count_24h")
        cycle = [{"signal": "empty_verdict_count_24h", "value": 0, "band": "GREEN", "breach": 0}]
        _mod._auto_resolve_alerts(conn, cycle, dry_run=False)
        row = conn.execute("SELECT resolved_at FROM health_alerts WHERE id=?", (row_id,)).fetchone()
        assert row["resolved_at"] is not None

    def test_resolves_when_signal_returns_warn(self, tmp_path):
        db_path = _make_db(tmp_path)
        conn = _open(db_path)
        row_id = self._insert_open_alert(conn, "coach_freshness_pct")
        cycle = [{"signal": "coach_freshness_pct", "value": 15.0, "band": "WARN", "breach": 0}]
        _mod._auto_resolve_alerts(conn, cycle, dry_run=False)
        row = conn.execute("SELECT resolved_at FROM health_alerts WHERE id=?", (row_id,)).fetchone()
        assert row["resolved_at"] is not None

    def test_does_not_resolve_when_still_alert(self, tmp_path):
        db_path = _make_db(tmp_path)
        conn = _open(db_path)
        row_id = self._insert_open_alert(conn, "empty_verdict_count_24h")
        cycle = [{"signal": "empty_verdict_count_24h", "value": 5, "band": "ALERT", "breach": 1}]
        _mod._auto_resolve_alerts(conn, cycle, dry_run=False)
        row = conn.execute("SELECT resolved_at FROM health_alerts WHERE id=?", (row_id,)).fetchone()
        assert row["resolved_at"] is None

    def test_signal_not_in_cycle_not_touched(self, tmp_path):
        db_path = _make_db(tmp_path)
        conn = _open(db_path)
        row_id = self._insert_open_alert(conn, "empty_verdict_count_24h")
        cycle = [{"signal": "validator_reject_rate", "value": 0, "band": "GREEN", "breach": 0}]
        _mod._auto_resolve_alerts(conn, cycle, dry_run=False)
        row = conn.execute("SELECT resolved_at FROM health_alerts WHERE id=?", (row_id,)).fetchone()
        assert row["resolved_at"] is None  # different signal — not touched

    def test_dry_run_does_not_resolve(self, tmp_path):
        db_path = _make_db(tmp_path)
        conn = _open(db_path)
        row_id = self._insert_open_alert(conn, "empty_verdict_count_24h")
        cycle = [{"signal": "empty_verdict_count_24h", "value": 0, "band": "GREEN", "breach": 0}]
        _mod._auto_resolve_alerts(conn, cycle, dry_run=True)
        row = conn.execute("SELECT resolved_at FROM health_alerts WHERE id=?", (row_id,)).fetchone()
        assert row["resolved_at"] is None


class TestBackfillStaleAlerts:
    """_backfill_stale_alerts inserts health_alerts for stale ALERT rows in narrative_integrity_log."""

    def test_inserts_for_stale_alert_signal(self, tmp_path):
        db_path = _make_db(tmp_path)
        conn = _open(db_path)
        _insert_nil_row(conn, "sonnet_firing_rate", 0.35, "ALERT", 1)
        with patch.object(_mod, "_send_edgeops_alert"):
            _mod._backfill_stale_alerts(conn, dry_run=False)
        rows = _get_open_alerts(conn, "sonnet_firing_rate")
        assert len(rows) == 1
        meta = json.loads(rows[0]["meta"])
        assert meta.get("backfilled") is True
        conn.close()

    def test_skips_if_open_alert_exists(self, tmp_path):
        db_path = _make_db(tmp_path)
        conn = _open(db_path)
        _insert_nil_row(conn, "sonnet_firing_rate", 0.35, "ALERT", 1)
        # Pre-insert open alert
        conn.execute(
            "INSERT INTO health_alerts (source_id, alert_type, severity, message, fired_at, meta) "
            "VALUES (?, 'quality_signal', 'critical', 'existing', ?, ?)",
            (_mod._SOURCE_ID, _ago_iso(hours=25), json.dumps({"signal_name": "sonnet_firing_rate"})),
        )
        conn.commit()
        with patch.object(_mod, "_send_edgeops_alert") as mock_send:
            _mod._backfill_stale_alerts(conn, dry_run=False)
        mock_send.assert_not_called()
        rows = _get_open_alerts(conn, "sonnet_firing_rate")
        assert len(rows) == 1  # still just the pre-existing row
        conn.close()

    def test_skips_green_signals(self, tmp_path):
        db_path = _make_db(tmp_path)
        conn = _open(db_path)
        _insert_nil_row(conn, "total_narratives_24h", 10, "GREEN", 0)
        _mod._backfill_stale_alerts(conn, dry_run=False)
        rows = _get_open_alerts(conn, "total_narratives_24h")
        assert len(rows) == 0
        conn.close()

    def test_dry_run_inserts_nothing(self, tmp_path):
        db_path = _make_db(tmp_path)
        conn = _open(db_path)
        _insert_nil_row(conn, "staleness_pct", 75.0, "ALERT", 1)
        with patch.object(_mod, "_send_edgeops_alert") as mock_send:
            _mod._backfill_stale_alerts(conn, dry_run=True)
        mock_send.assert_not_called()
        rows = _get_open_alerts(conn, "staleness_pct")
        assert len(rows) == 0
        conn.close()

    def test_backfill_uses_latest_row_per_signal(self, tmp_path):
        """If the latest row is GREEN (resolved), backfill should not insert."""
        db_path = _make_db(tmp_path)
        conn = _open(db_path)
        # Old ALERT row
        conn.execute(
            "INSERT INTO narrative_integrity_log (signal, value, band, breach, recorded_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("sonnet_firing_rate", 0.35, "ALERT", 1, _ago_iso(hours=2)),
        )
        # Newer GREEN row (signal recovered)
        conn.execute(
            "INSERT INTO narrative_integrity_log (signal, value, band, breach, recorded_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("sonnet_firing_rate", 0.8, "GREEN", 0, _ago_iso(hours=0, minutes=5)),
        )
        conn.commit()
        with patch.object(_mod, "_send_edgeops_alert") as mock_send:
            _mod._backfill_stale_alerts(conn, dry_run=False)
        mock_send.assert_not_called()
        rows = _get_open_alerts(conn, "sonnet_firing_rate")
        assert len(rows) == 0
        conn.close()
