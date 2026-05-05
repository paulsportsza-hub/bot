"""Contract tests for P2-02 BUILD-MONITORING-DASHBOARD.

Tests health_checker.py and health_schema_migration.py.

Run via:
    bash /home/paulsportsza/bot/scripts/qa_safe.sh contracts
"""
import sys
import os
import sqlite3
import tempfile
import shutil
import importlib

import pytest

# Ensure scripts directory is importable
sys.path.insert(0, '/home/paulsportsza')
sys.path.insert(0, '/home/paulsportsza/scripts')


# ---------------------------------------------------------------------------
# Import the modules under test
# ---------------------------------------------------------------------------

import health_checker as hc

# ---------------------------------------------------------------------------
# Test 1-5: status_from_minutes classification
# ---------------------------------------------------------------------------

def test_status_classification_green():
    """30 min elapsed vs 120 min interval = green (< 50% of threshold)."""
    assert hc.status_from_minutes(30, 120) == 'green'


def test_status_classification_yellow():
    """70 min elapsed vs 120 min interval = yellow (50–100% of threshold)."""
    assert hc.status_from_minutes(70, 120) == 'yellow'


def test_status_classification_red():
    """150 min elapsed vs 120 min interval = red (>100% but <300%)."""
    assert hc.status_from_minutes(150, 120) == 'red'


def test_status_classification_dead():
    """400 min elapsed vs 120 min interval = black (>3x threshold = dead)."""
    assert hc.status_from_minutes(400, 120) == 'black'


def test_status_classification_ondemand():
    """on-demand source (interval=0) always returns black."""
    assert hc.status_from_minutes(0, 0) == 'black'
    assert hc.status_from_minutes(9999, 0) == 'black'


# ---------------------------------------------------------------------------
# Test 6: migration creates all 5 tables in a fresh DB
# ---------------------------------------------------------------------------

def test_migration_tables_exist(tmp_path):
    """Run migration against a temp DB and verify all 5 tables are created."""
    import health_schema_migration as mig
    import importlib

    tmp_db = str(tmp_path / "test_odds.db")

    # Monkey-patch ODDS_DB in the migration module
    original_db = mig.ODDS_DB
    mig.ODDS_DB = tmp_db
    try:
        mig.run_migration()
    finally:
        mig.ODDS_DB = original_db

    # Verify tables exist
    conn = sqlite3.connect(tmp_db)
    table_names = {
        r[0] for r in
        conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    conn.close()

    expected = {
        'source_registry',
        'source_health_log',
        'source_health_current',
        'api_quota_tracking',
        'health_alerts',
    }
    assert expected.issubset(table_names), (
        f"Missing tables: {expected - table_names}"
    )


# ---------------------------------------------------------------------------
# Test 7: migration is idempotent (safe to run twice)
# ---------------------------------------------------------------------------

def test_migration_is_idempotent(tmp_path):
    """Running migration twice does not raise or double-insert rows."""
    import health_schema_migration as mig

    tmp_db = str(tmp_path / "test_odds_idem.db")
    original_db = mig.ODDS_DB
    mig.ODDS_DB = tmp_db
    try:
        mig.run_migration()
        mig.run_migration()  # second run must not crash
    finally:
        mig.ODDS_DB = original_db

    conn = sqlite3.connect(tmp_db)
    count = conn.execute("SELECT COUNT(*) FROM source_registry").fetchone()[0]
    conn.close()
    # Should still be exactly 46 after two runs (INSERT OR IGNORE)
    assert count == 46, f"Expected 46 sources, got {count}"


# ---------------------------------------------------------------------------
# Test 8: migration seeds exactly 42 sources
# ---------------------------------------------------------------------------

def test_migration_seeds_43_sources(tmp_path):
    """source_registry should have exactly 46 rows after migration."""
    import health_schema_migration as mig

    tmp_db = str(tmp_path / "test_seeds.db")
    original_db = mig.ODDS_DB
    mig.ODDS_DB = tmp_db
    try:
        mig.run_migration()
    finally:
        mig.ODDS_DB = original_db

    conn = sqlite3.connect(tmp_db)
    count = conn.execute("SELECT COUNT(*) FROM source_registry").fetchone()[0]
    hc_count = conn.execute("SELECT COUNT(*) FROM source_health_current").fetchone()[0]
    conn.close()

    assert count == 46, f"Expected 46 sources in registry, got {count}"
    assert hc_count == 46, f"Expected 46 rows in health_current, got {hc_count}"


# ---------------------------------------------------------------------------
# Test 9: health_checker has no direct sqlite3.connect() calls
# ---------------------------------------------------------------------------

def test_health_checker_no_raw_sqlite():
    """health_checker.py must never call sqlite3.connect() directly.

    W81-DBLOCK: All DB access must go through approved factories.
    """
    checker_path = '/home/paulsportsza/scripts/health_checker.py'
    with open(checker_path, 'r') as f:
        source = f.read()

    # Allow sqlite3.connect only inside comments
    lines = source.split('\n')
    violations = []
    for i, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if stripped.startswith('#'):
            continue  # comment line — allowed
        if 'sqlite3.connect(' in line:
            violations.append(f"Line {i}: {line.rstrip()}")

    assert not violations, (
        "W81-DBLOCK violation: health_checker.py calls sqlite3.connect() directly.\n"
        "Use connect_odds_db() or connect_db() from scrapers.db_connect instead.\n"
        "Violations:\n" + '\n'.join(violations)
    )


# ---------------------------------------------------------------------------
# Test 10: health_schema_migration has no raw sqlite3.connect() either
# ---------------------------------------------------------------------------

def test_migration_no_raw_sqlite():
    """health_schema_migration.py must use connect_odds_db(), not sqlite3.connect()."""
    migration_path = '/home/paulsportsza/scripts/health_schema_migration.py'
    with open(migration_path, 'r') as f:
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
        "W81-DBLOCK violation: health_schema_migration.py calls sqlite3.connect() directly.\n"
        + '\n'.join(violations)
    )


# ---------------------------------------------------------------------------
# Test 11: CLV family uses identical 36h lookback windows (BUILD-HEALTH-CLVBF-WINDOW-01)
# ---------------------------------------------------------------------------

def test_clv_family_uses_identical_windows():
    """_check_sharp_closing, _check_clv_tracker, _check_clv_backfill must all
    use window_hours=36 (primary) and '-36 hours' (fallback SQL).

    Regression guard: prevents overnight BLACK caused by a 6h window that ages
    out during the 12h off-window gap (22:30→10:30 UTC).
    """
    import re

    checker_path = '/home/paulsportsza/scripts/health_checker.py'
    with open(checker_path, 'r') as f:
        source = f.read()

    # Extract body of each check function (from def line to next def at same indent)
    def _extract_fn_body(src, fn_name):
        pattern = rf'def {re.escape(fn_name)}\(.*?(?=\ndef |\Z)'
        m = re.search(pattern, src, re.DOTALL)
        assert m, f"{fn_name} not found in health_checker.py"
        return m.group(0)

    bodies = {
        fn: _extract_fn_body(source, fn)
        for fn in ('_check_sharp_closing', '_check_clv_tracker', '_check_clv_backfill')
    }

    # All three must share the same primary window (36h covers the 12h overnight gap)
    for fn, body in bodies.items():
        assert 'window_hours=36' in body, (
            f"{fn}: expected window_hours=36 but found different value. "
            "All CLV-family functions must use 36h to survive the 12h overnight gap."
        )

    # _check_clv_backfill fallback SQL must also use 36h (was 6h — the root-cause bug)
    assert "'-36 hours'" in bodies['_check_clv_backfill'], (
        "_check_clv_backfill: SQL fallback must use '-36 hours' (was '-6 hours'). "
        "Short fallback window caused BLACK status overnight."
    )


# ---------------------------------------------------------------------------
# Test 11: status_from_minutes boundary conditions
# ---------------------------------------------------------------------------

def test_status_boundary_exactly_at_half():
    """Exactly at 50% of threshold → yellow (not green)."""
    # 60 minutes elapsed, 120 min threshold → 60/120 = 0.5 exactly → yellow
    assert hc.status_from_minutes(60, 120) == 'yellow'


def test_status_boundary_exactly_at_threshold():
    """Exactly at 100% of threshold → red (not yellow)."""
    # 120 min elapsed, 120 min threshold → red
    assert hc.status_from_minutes(120, 120) == 'red'


def test_status_boundary_exactly_at_3x():
    """Exactly at 3x threshold → black (dead)."""
    # 360 min elapsed, 120 min threshold → 3x exactly → black
    assert hc.status_from_minutes(360, 120) == 'black'


# ---------------------------------------------------------------------------
# Test 12: record_health writes to both tables
# ---------------------------------------------------------------------------

def test_record_health_writes_to_db(tmp_path):
    """record_health() should write to both source_health_log and source_health_current."""
    import health_schema_migration as mig
    from scrapers.db_connect import connect_odds_db

    tmp_db = str(tmp_path / "test_record.db")
    orig = mig.ODDS_DB
    mig.ODDS_DB = tmp_db
    try:
        mig.run_migration()
    finally:
        mig.ODDS_DB = orig

    conn = connect_odds_db(tmp_db)
    with conn:
        hc.record_health(
            conn,
            source_id='bk_hollywoodbets',
            status='green',
            last_success_at='2026-04-05T06:00:00Z',
            minutes_since=5,
            rows_produced=100,
            error_message=None,
        )

    log_count = conn.execute(
        "SELECT COUNT(*) FROM source_health_log WHERE source_id='bk_hollywoodbets'"
    ).fetchone()[0]
    cur_row = conn.execute(
        "SELECT status, last_rows_produced FROM source_health_current WHERE source_id='bk_hollywoodbets'"
    ).fetchone()
    conn.close()

    assert log_count == 1, "Should have exactly 1 log entry"
    assert cur_row is not None, "source_health_current should have a row"
    assert cur_row[0] == 'green', f"Expected status 'green', got {cur_row[0]}"
    assert cur_row[1] == 100, f"Expected 100 rows produced, got {cur_row[1]}"
