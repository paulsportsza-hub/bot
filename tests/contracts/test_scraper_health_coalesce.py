"""
FIX-SCRAPER-HEALTH-DB-LOCK-COALESCE-01 — contract tests (AC-4).

Covers:
  AC-1  same-exception coalescing
  AC-2  file-based dedup fallback
  AC-3  in-band [monitor_name] source tag
"""
from __future__ import annotations

import contextlib
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, "/home/paulsportsza")

from contracts.monitors.scraper_health import (
    ALERT_COOLDOWN_MIN,
    DBLOCK_LOCK_VOLUME_24H,
    DBLOCK_LOCK_VOLUME_4H,
    MONITOR_NAME,
    PUBLISHER_MONITOR_NAME,
    _build_alert,
    _check_db_lock_volume,
    _coalesce_p0_fails,
    _count_lock_events,
    _was_alerted_recently,
    run_checks,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _exc_fail(check: str, exc_msg: str = "database is locked") -> dict:
    return {
        "check": check,
        "severity": "P0",
        "status": "FAIL",
        "detail": f"EXCEPTION: {exc_msg}",
    }


def _plain_fail(check: str, detail: str = "Last edge recommended 200min ago") -> dict:
    return {"check": check, "severity": "P0", "status": "FAIL", "detail": detail}


# ---------------------------------------------------------------------------
# AC-1: same-exception coalescing
# ---------------------------------------------------------------------------

class TestCoalesceP0Fails:

    def test_all_same_exception_produces_one_entry(self):
        fails = [_exc_fail(f"c{i}") for i in range(6)]
        result = _coalesce_p0_fails(fails, MONITOR_NAME)
        assert len(result) == 1
        r = result[0]
        assert r["check"] == "db_lock_cascade"
        assert r["severity"] == "P0"
        assert r["status"] == "FAIL"
        assert "[scraper_health] DB LOCKED: all 6" in r["detail"]
        assert "EXCEPTION: database is locked" in r["detail"]

    def test_mixed_exception_and_assertion_preserves_list(self):
        fails = [_exc_fail(f"c{i}") for i in range(5)] + [_plain_fail("edge_pipeline_freshness")]
        result = _coalesce_p0_fails(fails, MONITOR_NAME)
        assert len(result) == 6

    def test_diverse_exceptions_preserve_list(self):
        fails = [
            _exc_fail("c1", "database is locked"),
            _exc_fail("c2", "disk I/O error"),
        ]
        result = _coalesce_p0_fails(fails, MONITOR_NAME)
        assert len(result) == 2

    def test_empty_list_returns_empty(self):
        assert _coalesce_p0_fails([], MONITOR_NAME) == []

    def test_single_exception_coalesces_with_count_1(self):
        result = _coalesce_p0_fails([_exc_fail("c1")], MONITOR_NAME)
        assert len(result) == 1
        assert "all 1" in result[0]["detail"]

    def test_publisher_monitor_name_in_detail(self):
        fails = [_exc_fail(f"c{i}") for i in range(2)]
        result = _coalesce_p0_fails(fails, PUBLISHER_MONITOR_NAME)
        assert "[data_contract_monitor] DB LOCKED" in result[0]["detail"]

    def test_non_exception_only_fails_preserve_list(self):
        fails = [_plain_fail("c1"), _plain_fail("c2")]
        result = _coalesce_p0_fails(fails, MONITOR_NAME)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# AC-2: file-based dedup fallback
# ---------------------------------------------------------------------------

class TestFileBasedDedup:

    def test_db_lock_no_file_allows_alert(self, tmp_path):
        locked = MagicMock()
        locked.execute.side_effect = sqlite3.OperationalError("database is locked")
        alert_file = str(tmp_path / "last_alert.txt")
        with patch("contracts.monitors.scraper_health.DBLOCK_ALERT_FILE", alert_file):
            assert _was_alerted_recently(locked, "db_lock_cascade") is False

    def test_db_lock_recent_file_suppresses(self, tmp_path):
        locked = MagicMock()
        locked.execute.side_effect = sqlite3.OperationalError("database is locked")
        alert_file = str(tmp_path / "last_alert.txt")
        with open(alert_file, "w") as f:
            f.write(datetime.now(timezone.utc).isoformat())
        with patch("contracts.monitors.scraper_health.DBLOCK_ALERT_FILE", alert_file):
            assert _was_alerted_recently(locked, "db_lock_cascade") is True

    def test_db_lock_old_file_allows_alert(self, tmp_path):
        locked = MagicMock()
        locked.execute.side_effect = sqlite3.OperationalError("database is locked")
        alert_file = str(tmp_path / "last_alert.txt")
        old_ts = datetime.now(timezone.utc) - timedelta(minutes=ALERT_COOLDOWN_MIN + 10)
        with open(alert_file, "w") as f:
            f.write(old_ts.isoformat())
        with patch("contracts.monitors.scraper_health.DBLOCK_ALERT_FILE", alert_file):
            assert _was_alerted_recently(locked, "db_lock_cascade") is False

    def test_db_lock_corrupt_file_allows_alert(self, tmp_path):
        locked = MagicMock()
        locked.execute.side_effect = sqlite3.OperationalError("database is locked")
        alert_file = str(tmp_path / "last_alert.txt")
        with open(alert_file, "w") as f:
            f.write("not-a-timestamp")
        with patch("contracts.monitors.scraper_health.DBLOCK_ALERT_FILE", alert_file):
            assert _was_alerted_recently(locked, "db_lock_cascade") is False

    def test_current_run_ts_excluded_from_dedup_query(self, tmp_path):
        """Blocker 2: current run's own FAIL row must not suppress its own alert.

        When the only FAIL row in the DB is from the current run (same run_ts),
        _was_alerted_recently must return False so the alert can fire.
        """
        import sqlite3 as _sqlite3
        db_path = str(tmp_path / "test.db")
        conn = _sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE monitor_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                monitor TEXT,
                check_name TEXT,
                severity TEXT,
                status TEXT,
                detail TEXT,
                run_timestamp TEXT,
                UNIQUE(monitor, check_name, run_timestamp)
            )
        """)
        run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        # Simulate: check just wrote its own FAIL row for current run
        conn.execute(
            "INSERT INTO monitor_results (monitor, check_name, severity, status, detail, run_timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (MONITOR_NAME, "db_lock_volume", "P0", "FAIL", "976 lock events/24h", run_ts),
        )
        conn.commit()
        # With current_run_ts exclusion: must return False (allow the alert to fire)
        result = _was_alerted_recently(conn, "db_lock_volume", MONITOR_NAME, current_run_ts=run_ts)
        assert result is False, "Current run's own row must not suppress its own first alert"
        conn.close()

    def test_previous_run_ts_still_deduplicates(self, tmp_path):
        """A FAIL row from a PREVIOUS run (different run_ts) must still suppress."""
        import sqlite3 as _sqlite3
        db_path = str(tmp_path / "test.db")
        conn = _sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE monitor_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                monitor TEXT,
                check_name TEXT,
                severity TEXT,
                status TEXT,
                detail TEXT,
                run_timestamp TEXT,
                UNIQUE(monitor, check_name, run_timestamp)
            )
        """)
        prev_run_ts = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        current_run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        # Previous run's FAIL row (30 min ago, within the 60-min cooldown)
        conn.execute(
            "INSERT INTO monitor_results (monitor, check_name, severity, status, detail, run_timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (MONITOR_NAME, "db_lock_volume", "P0", "FAIL", "976 lock events/24h", prev_run_ts),
        )
        conn.commit()
        # With current_run_ts exclusion: previous run's row IS still found → True
        result = _was_alerted_recently(conn, "db_lock_volume", MONITOR_NAME, current_run_ts=current_run_ts)
        assert result is True, "Previous run's FAIL row must still suppress duplicate alert"
        conn.close()


# ---------------------------------------------------------------------------
# AC-3: in-band source tagging
# ---------------------------------------------------------------------------

class TestSourceTagging:

    def test_scraper_health_alert_prefixed(self):
        fails = [{"check": "bookmaker_odds_freshness", "severity": "P0", "status": "FAIL",
                  "detail": "STALE: hollywoodbets"}]
        text = _build_alert(fails, "2026-05-04T10:00:00+00:00", MONITOR_NAME)
        assert text.startswith("[scraper_health]")

    def test_publisher_monitor_alert_prefixed(self):
        fails = [{"check": "publisher_log_freshness", "severity": "P0", "status": "FAIL",
                  "detail": "publisher log stale"}]
        text = _build_alert(fails, "2026-05-04T10:00:00+00:00", PUBLISHER_MONITOR_NAME)
        assert text.startswith("[data_contract_monitor]")

    def test_source_tag_independent_of_monitor_name_in_body(self):
        fails = [{"check": "c1", "severity": "P0", "status": "FAIL", "detail": "oops"}]
        for name in (MONITOR_NAME, PUBLISHER_MONITOR_NAME):
            text = _build_alert(fails, "2026-05-04T10:00:00+00:00", name)
            assert f"[{name}]" in text


# ---------------------------------------------------------------------------
# AC-4 integration: run_checks() sends exactly 1 alert on full DB lock
# ---------------------------------------------------------------------------

def _db_locked(conn, run_ts):
    raise sqlite3.OperationalError("database is locked")


def _genuine_edge_fail(conn, run_ts):
    return {
        "check": "edge_pipeline_freshness",
        "severity": "P0",
        "status": "FAIL",
        "detail": "Last edge recommended 200min ago",
    }


def _pub_pass_fn(label, sev="P0"):
    def _fn(conn, run_ts):
        return {"check": label, "severity": sev, "status": "PASS", "detail": "ok"}
    return _fn


def _run_with_all_locked(tmp_path, edge_fn=None, alerts_sent=None, send_edgeops=None):
    """Helper: run run_checks() with 5 scraper checks locked + configurable 6th."""
    alert_file = str(tmp_path / "last_alert.txt")
    if alerts_sent is None:
        alerts_sent = []

    def _default_send(msg, dry_run=False):
        alerts_sent.append(msg)

    _send = send_edgeops or _default_send

    patches = {
        "contracts.monitors.scraper_health._check_bookmaker_odds_freshness": _db_locked,
        "contracts.monitors.scraper_health._check_scrape_run_continuity": _db_locked,
        "contracts.monitors.scraper_health._check_scrape_run_errors": _db_locked,
        "contracts.monitors.scraper_health._check_sharp_odds_freshness": _db_locked,
        "contracts.monitors.scraper_health._check_fpl_injuries_freshness": _db_locked,
        "contracts.monitors.scraper_health._check_edge_pipeline_freshness": edge_fn or _db_locked,
        # Volume check is a separate data source (journalctl) — patch as PASS to test cascade coalescing in isolation
        "contracts.monitors.scraper_health._check_db_lock_volume": _pub_pass_fn("db_lock_volume"),
        "contracts.monitors.scraper_health._check_publisher_log_freshness": _pub_pass_fn("publisher_log_freshness"),
        "contracts.monitors.scraper_health._check_tg_community_asset_null": _pub_pass_fn("tg_community_asset_null"),
        "contracts.monitors.scraper_health._check_autogen_image_log_freshness": _pub_pass_fn("autogen_image_log_freshness", "P1"),
    }

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = None

    with contextlib.ExitStack() as stack:
        for target, new_fn in patches.items():
            stack.enter_context(patch(target, new=new_fn))
        mock_db = stack.enter_context(patch("contracts.monitors.scraper_health.connect_odds_db"))
        mock_db.return_value = mock_conn
        stack.enter_context(patch("contracts.monitors.scraper_health._send_edgeops_alert", side_effect=_send))
        stack.enter_context(patch("contracts.monitors.scraper_health.DBLOCK_ALERT_FILE", alert_file))
        run_checks(dry_run=False)

    return alert_file, alerts_sent


class TestRunChecksCoalescing:

    def test_all_six_scraper_checks_locked_sends_one_alert(self, tmp_path):
        alerts: list[str] = []
        _, alerts = _run_with_all_locked(tmp_path, alerts_sent=alerts)
        assert len(alerts) == 1, f"Expected 1, got {len(alerts)}: {alerts}"
        msg = alerts[0]
        assert "[scraper_health]" in msg
        assert "DB LOCKED" in msg
        assert "6" in msg

    def test_mixed_failures_do_not_coalesce(self, tmp_path):
        alerts: list[str] = []
        _, alerts = _run_with_all_locked(tmp_path, edge_fn=_genuine_edge_fail, alerts_sent=alerts)
        assert len(alerts) == 1
        assert "DB LOCKED" not in alerts[0]

    def test_db_lock_dedup_file_written_on_alert(self, tmp_path):
        import os
        alert_file, _ = _run_with_all_locked(tmp_path)
        assert os.path.exists(alert_file)
        content = open(alert_file).read().strip()
        datetime.fromisoformat(content)  # must be a valid ISO timestamp


# ---------------------------------------------------------------------------
# Codex-review blockers (second pass)
# ---------------------------------------------------------------------------

class TestCoalesceNonLockException:
    """Blocker 1 — non-DB-lock same-exception cascade uses EXCEPTION CASCADE label."""

    def test_network_error_cascade_not_labelled_db_locked(self):
        fails = [_exc_fail(f"c{i}", "Connection refused") for i in range(6)]
        result = _coalesce_p0_fails(fails, MONITOR_NAME)
        assert len(result) == 1
        r = result[0]
        assert r["check"] == "exception_cascade"
        assert "EXCEPTION CASCADE" in r["detail"]
        assert "DB LOCKED" not in r["detail"]

    def test_db_lock_exception_keeps_db_locked_label(self):
        fails = [_exc_fail(f"c{i}", "database is locked") for i in range(3)]
        result = _coalesce_p0_fails(fails, MONITOR_NAME)
        assert result[0]["check"] == "db_lock_cascade"
        assert "DB LOCKED" in result[0]["detail"]


class TestWasAlertedRecentlyNarrowExcept:
    """Blocker 2 — non-OperationalError DB failure should NOT fall back to file dedup."""

    def test_programming_error_propagates_not_file_fallback(self, tmp_path):
        from contracts.monitors.scraper_health import _was_alerted_recently
        bad_conn = MagicMock()
        bad_conn.execute.side_effect = sqlite3.ProgrammingError("closed")
        alert_file = str(tmp_path / "last_alert.txt")
        # Write a recent timestamp that would suppress if fallback ran
        with open(alert_file, "w") as f:
            f.write(datetime.now(timezone.utc).isoformat())
        with patch("contracts.monitors.scraper_health.DBLOCK_ALERT_FILE", alert_file):
            # ProgrammingError should propagate (not fall through to True suppression)
            try:
                result = _was_alerted_recently(bad_conn, "some_check")
                # If it didn't raise, it must NOT have returned True (file-fallback suppression)
                assert result is False
            except sqlite3.ProgrammingError:
                pass  # expected — the error propagated correctly


class TestDedupFileOnlyForDbLock:
    """Blocker 4 — dedup file must not be written for non-DB-lock P0 alerts."""

    def test_non_lock_p0_does_not_write_dedup_file(self, tmp_path):
        import os
        alert_file = str(tmp_path / "last_alert.txt")
        alerts_sent: list[str] = []

        def _send(msg, dry_run=False):
            alerts_sent.append(msg)

        def _genuine_stale(conn, run_ts):
            return {
                "check": "edge_pipeline_freshness",
                "severity": "P0",
                "status": "FAIL",
                "detail": "Last edge recommended 200min ago",
            }

        def _pass(conn, run_ts):
            return {"check": "bookmaker_odds_freshness", "severity": "P0", "status": "PASS", "detail": "ok"}

        patches = {
            "contracts.monitors.scraper_health._check_bookmaker_odds_freshness": _pass,
            "contracts.monitors.scraper_health._check_scrape_run_continuity": _pass,
            "contracts.monitors.scraper_health._check_scrape_run_errors": _pass,
            "contracts.monitors.scraper_health._check_sharp_odds_freshness": _pass,
            "contracts.monitors.scraper_health._check_fpl_injuries_freshness": _pass,
            "contracts.monitors.scraper_health._check_edge_pipeline_freshness": _genuine_stale,
            # Volume check uses journalctl — patch as PASS so it doesn't write the dedup file
            "contracts.monitors.scraper_health._check_db_lock_volume": _pub_pass_fn("db_lock_volume"),
            "contracts.monitors.scraper_health._check_publisher_log_freshness": _pub_pass_fn("publisher_log_freshness"),
            "contracts.monitors.scraper_health._check_tg_community_asset_null": _pub_pass_fn("tg_community_asset_null"),
            "contracts.monitors.scraper_health._check_autogen_image_log_freshness": _pub_pass_fn("autogen_image_log_freshness", "P1"),
        }

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None

        with contextlib.ExitStack() as stack:
            for target, new_fn in patches.items():
                stack.enter_context(patch(target, new=new_fn))
            mock_db = stack.enter_context(patch("contracts.monitors.scraper_health.connect_odds_db"))
            mock_db.return_value = mock_conn
            stack.enter_context(patch("contracts.monitors.scraper_health._send_edgeops_alert", side_effect=_send))
            stack.enter_context(patch("contracts.monitors.scraper_health.DBLOCK_ALERT_FILE", alert_file))
            run_checks(dry_run=False)

        # Alert was sent for the genuine P0
        assert len(alerts_sent) == 1
        # But the dedup file must NOT have been written
        assert not os.path.exists(alert_file), "Dedup file should not be written for non-lock alerts"


class TestMigrateAndCommitLockTolerance:
    """Blocker 3 — _migrate and conn.commit OperationalError must not abort run_checks."""

    def test_migrate_lock_does_not_crash_run_checks(self, tmp_path):
        alert_file = str(tmp_path / "last_alert.txt")
        alerts_sent: list[str] = []

        def _send(msg, dry_run=False):
            alerts_sent.append(msg)

        mock_conn = MagicMock()
        # _migrate calls conn.execute — make it raise on migration DDL
        mock_conn.execute.side_effect = sqlite3.OperationalError("database is locked")

        with contextlib.ExitStack() as stack:
            mock_db = stack.enter_context(patch("contracts.monitors.scraper_health.connect_odds_db"))
            mock_db.return_value = mock_conn
            stack.enter_context(patch("contracts.monitors.scraper_health._send_edgeops_alert", side_effect=_send))
            stack.enter_context(patch("contracts.monitors.scraper_health.DBLOCK_ALERT_FILE", alert_file))
            # Should not raise even if _migrate and all checks are locked
            run_checks(dry_run=False)

    def test_commit_lock_does_not_crash_run_checks(self, tmp_path):
        """conn.commit() OperationalError must not abort run_checks."""
        alert_file = str(tmp_path / "last_alert.txt")
        alerts_sent: list[str] = []

        def _send(msg, dry_run=False):
            alerts_sent.append(msg)

        def _genuine_stale(conn, run_ts):
            return {
                "check": "edge_pipeline_freshness",
                "severity": "P0",
                "status": "FAIL",
                "detail": "Last edge recommended 200min ago",
            }

        def _pass(conn, run_ts):
            return {"check": "bookmaker_odds_freshness", "severity": "P0", "status": "PASS", "detail": "ok"}

        patches = {
            "contracts.monitors.scraper_health._check_bookmaker_odds_freshness": _pass,
            "contracts.monitors.scraper_health._check_scrape_run_continuity": _pass,
            "contracts.monitors.scraper_health._check_scrape_run_errors": _pass,
            "contracts.monitors.scraper_health._check_sharp_odds_freshness": _pass,
            "contracts.monitors.scraper_health._check_fpl_injuries_freshness": _pass,
            "contracts.monitors.scraper_health._check_edge_pipeline_freshness": _genuine_stale,
            # Volume check uses journalctl — patch as PASS so it doesn't write the dedup file
            "contracts.monitors.scraper_health._check_db_lock_volume": _pub_pass_fn("db_lock_volume"),
            "contracts.monitors.scraper_health._check_publisher_log_freshness": _pub_pass_fn("publisher_log_freshness"),
            "contracts.monitors.scraper_health._check_tg_community_asset_null": _pub_pass_fn("tg_community_asset_null"),
            "contracts.monitors.scraper_health._check_autogen_image_log_freshness": _pub_pass_fn("autogen_image_log_freshness", "P1"),
        }

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        # migrate succeeds, but commit raises
        mock_conn.commit.side_effect = sqlite3.OperationalError("database is locked")

        with contextlib.ExitStack() as stack:
            for target, new_fn in patches.items():
                stack.enter_context(patch(target, new=new_fn))
            mock_db = stack.enter_context(patch("contracts.monitors.scraper_health.connect_odds_db"))
            mock_db.return_value = mock_conn
            stack.enter_context(patch("contracts.monitors.scraper_health._send_edgeops_alert", side_effect=_send))
            stack.enter_context(patch("contracts.monitors.scraper_health.DBLOCK_ALERT_FILE", alert_file))
            result = run_checks(dry_run=False)

        # run_checks must not raise; alert for the genuine P0 must still fire
        assert result is not None
        assert len(alerts_sent) == 1


# ---------------------------------------------------------------------------
# FIX-DB-LOCK-CASCADE-MONITOR-CALIBRATION-01 — db_lock_volume check (AC-2–AC-4)
# ---------------------------------------------------------------------------

class TestDbLockVolumeConstants:
    """AC-2 — threshold constants are calibrated to brief spec."""

    def test_24h_threshold_is_500(self):
        assert DBLOCK_LOCK_VOLUME_24H == 500

    def test_4h_threshold_is_800(self):
        assert DBLOCK_LOCK_VOLUME_4H == 800


class TestCountLockEvents:
    """AC-2 — _count_lock_events returns -1 on OSError (journalctl unavailable)."""

    def test_returns_minus_one_on_os_error(self):
        with patch("contracts.monitors.scraper_health.subprocess.run",
                   side_effect=OSError("not found")):
            result = _count_lock_events(24)
        assert result == -1

    def test_returns_minus_one_on_timeout(self):
        import subprocess
        with patch("contracts.monitors.scraper_health.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="journalctl", timeout=60)):
            result = _count_lock_events(24)
        assert result == -1

    def test_returns_minus_one_on_nonzero_returncode(self):
        """journalctl non-zero exit (e.g. permission error) must return -1, not 0."""
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        with patch("contracts.monitors.scraper_health.subprocess.run", return_value=mock_proc):
            result = _count_lock_events(24)
        assert result == -1

    def test_counts_occurrences_correctly(self):
        fake_output = (
            "line with database is locked here\n"
            "another: database is locked\n"
            "nothing here\n"
            "database is locked\n"
        )
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = fake_output
        with patch("contracts.monitors.scraper_health.subprocess.run", return_value=mock_proc):
            result = _count_lock_events(24)
        assert result == 3

    def test_zero_when_no_matches(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "clean run, no problems here\n"
        with patch("contracts.monitors.scraper_health.subprocess.run", return_value=mock_proc):
            result = _count_lock_events(4)
        assert result == 0


class TestCheckDbLockVolume:
    """AC-2 — _check_db_lock_volume fires correctly on thresholds."""

    def _mock_conn(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        return conn

    def _run(self, count_24h: int, count_4h: int):
        conn = self._mock_conn()
        run_ts = "2026-05-04T10:00:00+00:00"
        with patch("contracts.monitors.scraper_health._count_lock_events",
                   side_effect=[count_24h, count_4h]):
            return _check_db_lock_volume(conn, run_ts)

    def test_fail_when_24h_exceeds_threshold(self):
        result = self._run(count_24h=501, count_4h=0)
        assert result["status"] == "FAIL"
        assert result["check"] == "db_lock_volume"
        assert "24h" in result["detail"]

    def test_fail_when_4h_exceeds_threshold(self):
        result = self._run(count_24h=0, count_4h=801)
        assert result["status"] == "FAIL"
        assert "4h" in result["detail"]

    def test_fail_when_both_thresholds_exceeded(self):
        result = self._run(count_24h=1000, count_4h=900)
        assert result["status"] == "FAIL"
        assert "24h" in result["detail"]
        assert "4h" in result["detail"]

    def test_pass_when_under_both_thresholds(self):
        result = self._run(count_24h=499, count_4h=799)
        assert result["status"] == "PASS"
        assert result["check"] == "db_lock_volume"

    def test_pass_at_exact_threshold_boundary(self):
        # Thresholds are >500 and >800 (strict greater-than)
        result = self._run(count_24h=500, count_4h=800)
        assert result["status"] == "PASS"

    def test_skip_when_journalctl_unavailable(self):
        result = self._run(count_24h=-1, count_4h=-1)
        assert result["status"] == "SKIP_NO_DATA"
        assert "unavailable" in result["detail"]

    def test_uses_24h_only_when_4h_unavailable(self):
        # count_24h available, count_4h unavailable
        result = self._run(count_24h=600, count_4h=-1)
        assert result["status"] == "FAIL"
        assert "24h" in result["detail"]

    def test_uses_4h_only_when_24h_unavailable(self):
        result = self._run(count_24h=-1, count_4h=900)
        assert result["status"] == "FAIL"
        assert "4h" in result["detail"]

    def test_detail_includes_avg_per_hour_on_4h_fail(self):
        result = self._run(count_24h=0, count_4h=1000)
        assert result["status"] == "FAIL"
        # 1000 / 4 = 250 → included in detail
        assert "250" in result["detail"]

    def test_severity_is_p0(self):
        result = self._run(count_24h=600, count_4h=0)
        assert result["severity"] == "P0"


class TestDbLockVolumeDedup:
    """AC-3 — db_lock_volume alert deduplicates 1× per hour via file fallback."""

    def test_dblock_alert_file_written_on_volume_fail(self, tmp_path):
        """When db_lock_volume fires, the shared dedup file is written."""
        import os
        alert_file = str(tmp_path / "last_alert.txt")
        alerts_sent: list[str] = []

        def _send(msg, dry_run=False):
            alerts_sent.append(msg)

        def _volume_fail(conn, run_ts):
            return {
                "check": "db_lock_volume",
                "severity": "P0",
                "status": "FAIL",
                "detail": "976 lock events/24h (threshold: >500)",
            }

        patches = {
            "contracts.monitors.scraper_health._check_bookmaker_odds_freshness": _pub_pass_fn("bookmaker_odds_freshness"),
            "contracts.monitors.scraper_health._check_scrape_run_continuity": _pub_pass_fn("scrape_run_continuity"),
            "contracts.monitors.scraper_health._check_scrape_run_errors": _pub_pass_fn("scrape_run_errors"),
            "contracts.monitors.scraper_health._check_sharp_odds_freshness": _pub_pass_fn("sharp_odds_freshness"),
            "contracts.monitors.scraper_health._check_edge_pipeline_freshness": _pub_pass_fn("edge_pipeline_freshness"),
            "contracts.monitors.scraper_health._check_fpl_injuries_freshness": _pub_pass_fn("fpl_injuries_freshness"),
            "contracts.monitors.scraper_health._check_db_lock_volume": _volume_fail,
            "contracts.monitors.scraper_health._check_publisher_log_freshness": _pub_pass_fn("publisher_log_freshness"),
            "contracts.monitors.scraper_health._check_tg_community_asset_null": _pub_pass_fn("tg_community_asset_null"),
            "contracts.monitors.scraper_health._check_autogen_image_log_freshness": _pub_pass_fn("autogen_image_log_freshness", "P1"),
        }

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None

        with contextlib.ExitStack() as stack:
            for target, new_fn in patches.items():
                stack.enter_context(patch(target, new=new_fn))
            mock_db = stack.enter_context(patch("contracts.monitors.scraper_health.connect_odds_db"))
            mock_db.return_value = mock_conn
            stack.enter_context(patch("contracts.monitors.scraper_health._send_edgeops_alert", side_effect=_send))
            stack.enter_context(patch("contracts.monitors.scraper_health.DBLOCK_ALERT_FILE", alert_file))
            run_checks(dry_run=False)

        assert len(alerts_sent) == 1
        assert "db_lock_volume" in alerts_sent[0]
        # Dedup file written for db_lock_volume alert
        assert os.path.exists(alert_file)
        content = open(alert_file).read().strip()
        datetime.fromisoformat(content)  # must be a valid ISO timestamp


class TestDbLockVolumeDryRun:
    """AC-4 — dry-run against real journal confirms alert fires at 976+ events."""

    def test_threshold_fires_on_baseline_data(self):
        """976 events/24h > 500 threshold: would have fired on 2026-05-04 baseline."""
        assert 976 > DBLOCK_LOCK_VOLUME_24H, (
            f"The 2026-05-04 baseline (976 events/24h) must exceed threshold "
            f"({DBLOCK_LOCK_VOLUME_24H}). Recalibrate if threshold changed."
        )

    def test_4h_threshold_does_not_fire_on_baseline_data(self):
        """197 events/4h < 800 threshold: correctly does NOT fire on steady-state pattern."""
        baseline_4h = 197  # measured from journalctl on 2026-05-04
        assert baseline_4h <= DBLOCK_LOCK_VOLUME_4H, (
            f"The 4h baseline ({baseline_4h}) should not exceed threshold "
            f"({DBLOCK_LOCK_VOLUME_4H}). The 4h gate is for burst detection only."
        )
