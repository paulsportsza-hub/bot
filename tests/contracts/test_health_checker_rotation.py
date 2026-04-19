"""Contract tests for FIX-HEALTH-MONITOR-ROTATION-01.

Verifies that _check_bot_log() scans all 6 log files
(bot.log + .1 through .5) so log rotation cannot produce
false CRITICAL alerts.
"""
import sys
from datetime import datetime, timezone, timedelta
from unittest import mock

sys.path.insert(0, '/home/paulsportsza/scripts')

import health_checker as hc


def _make_log_line(pattern: str, minutes_ago: int = 30) -> str:
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return f"{ts.strftime('%Y-%m-%d %H:%M:%S')} INFO {pattern}\n"


def _make_unrelated_line() -> str:
    ts = datetime.now(timezone.utc) - timedelta(minutes=10)
    return f"{ts.strftime('%Y-%m-%d %H:%M:%S')} INFO unrelated log line\n"


class TestCheckBotLogRotation:
    """AC1: all 6 candidate files are scanned."""

    def test_match_in_dot3_is_found(self, tmp_path):
        """Pattern only in bot.log.3 — must be returned."""
        base = tmp_path / "bot.log"
        pattern = "PREGEN_COMPLETE"
        for i in range(1, 6):
            p = tmp_path / f"bot.log.{i}"
            if i == 3:
                p.write_text(_make_log_line(pattern))
            else:
                p.write_text(_make_unrelated_line())
        base.write_text(_make_unrelated_line())

        with mock.patch.object(hc, "BOT_LOG", str(base)):
            ts_str, count = hc._check_bot_log(pattern, window_hours=3)

        assert count >= 1, "Should find the match in bot.log.3"
        assert ts_str is not None

    def test_match_in_current_log_is_found(self, tmp_path):
        """Pattern only in bot.log (no regression)."""
        base = tmp_path / "bot.log"
        pattern = "PREGEN_COMPLETE"
        base.write_text(_make_log_line(pattern))

        with mock.patch.object(hc, "BOT_LOG", str(base)):
            ts_str, count = hc._check_bot_log(pattern, window_hours=3)

        assert count >= 1, "Should find the match in bot.log"
        assert ts_str is not None

    def test_no_match_returns_zero(self, tmp_path):
        """No matching pattern anywhere → (None, 0)."""
        base = tmp_path / "bot.log"
        pattern = "PREGEN_COMPLETE"
        base.write_text(_make_unrelated_line())
        for i in range(1, 6):
            (tmp_path / f"bot.log.{i}").write_text(_make_unrelated_line())

        with mock.patch.object(hc, "BOT_LOG", str(base)):
            ts_str, count = hc._check_bot_log(pattern, window_hours=3)

        assert count == 0
        assert ts_str is None

    def test_candidate_list_has_six_entries(self, tmp_path):
        """Internal candidate list must cover bot.log + .1 through .5."""
        base = tmp_path / "bot.log"
        base.write_text("")
        captured = []

        original_open = open

        def capturing_open(path, *args, **kwargs):
            captured.append(str(path))
            return original_open(path, *args, **kwargs)

        with mock.patch.object(hc, "BOT_LOG", str(base)):
            for i in range(1, 6):
                (tmp_path / f"bot.log.{i}").write_text("")
            with mock.patch("builtins.open", side_effect=capturing_open):
                hc._check_bot_log("ANYTHING", window_hours=3)

        assert len(captured) == 6, (
            f"Expected 6 file opens (bot.log + .1-.5), got {len(captured)}: {captured}"
        )
