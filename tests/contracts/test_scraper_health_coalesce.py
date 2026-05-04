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
    MONITOR_NAME,
    PUBLISHER_MONITOR_NAME,
    _build_alert,
    _coalesce_p0_fails,
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
