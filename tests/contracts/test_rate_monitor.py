"""Contract tests for the RateMonitor rate limit tracking system.

API-RATE-MONITOR — W28-2026-03-28
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from evidence_providers.rate_monitor import RateMonitor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_monitor(daily_limit: int = 100) -> RateMonitor:
    mon = RateMonitor()
    mon.register_provider("test", daily_limit=daily_limit)
    return mon


def _make_shared_monitor() -> RateMonitor:
    mon = RateMonitor()
    mon.register_provider("api_sports", daily_limit=100, shared_with=["rugby", "mma"])
    return mon


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRateMonitorCountsCorrectly:
    """record 5 calls — count must be 5."""

    def test_basic_count(self) -> None:
        mon = _make_monitor()
        for _ in range(5):
            mon.record_call("test")
        assert mon._counters["test"] == 5

    def test_unknown_provider_ignored(self) -> None:
        mon = _make_monitor()
        mon.record_call("unknown")  # should not raise
        assert mon._counters.get("unknown") is None


class TestRateMonitorSharedPool:
    """rugby + MMA both use api_sports — each call increments the same counter."""

    def test_rugby_and_mma_share_counter(self) -> None:
        mon = _make_shared_monitor()
        # Simulate rugby calling record_call
        mon.record_call("api_sports")
        # Simulate MMA calling record_call
        mon.record_call("api_sports")
        assert mon._counters["api_sports"] == 2

    def test_shared_with_in_display(self) -> None:
        mon = _make_shared_monitor()
        display = mon._display_name("api_sports")
        assert "rugby" in display
        assert "mma" in display

    def test_shared_pool_in_usage(self) -> None:
        mon = _make_shared_monitor()
        usage = mon.get_usage("api_sports")
        assert "rugby" in usage["shared_pool_names"]
        assert "mma" in usage["shared_pool_names"]


class TestRateMonitorThreshold70:
    """At 70/100 calls, a single ALERT fires."""

    def test_alert_fires_at_70_pct(self) -> None:
        mon = _make_monitor()
        fired: list[str] = []

        async def _mock_alert(msg: str) -> None:
            fired.append(msg)

        mon._send_edgeops_alert = _mock_alert  # type: ignore[method-assign]

        with patch.object(mon, "_fire_and_forget", side_effect=lambda m: asyncio.run(mon._send_edgeops_alert(m))):
            for _ in range(70):
                mon.record_call("test")

        assert len(fired) == 1
        assert "ALERT" in fired[0]
        assert "70/100" in fired[0]


class TestRateMonitorThreshold90:
    """At 90/100 calls, a WARNING fires (70% alert already consumed)."""

    def test_warning_fires_at_90_pct(self) -> None:
        mon = _make_monitor()
        fired: list[str] = []

        async def _mock_alert(msg: str) -> None:
            fired.append(msg)

        mon._send_edgeops_alert = _mock_alert  # type: ignore[method-assign]

        with patch.object(mon, "_fire_and_forget", side_effect=lambda m: asyncio.run(mon._send_edgeops_alert(m))):
            for _ in range(90):
                mon.record_call("test")

        # Should have fired twice: once at 70%, once at 90%
        assert any("WARNING" in m for m in fired)
        assert any("90/100" in m for m in fired)


class TestRateMonitorThreshold100:
    """At 100/100 calls, a CRITICAL fires."""

    def test_critical_fires_at_100_pct(self) -> None:
        mon = _make_monitor()
        fired: list[str] = []

        async def _mock_alert(msg: str) -> None:
            fired.append(msg)

        mon._send_edgeops_alert = _mock_alert  # type: ignore[method-assign]

        with patch.object(mon, "_fire_and_forget", side_effect=lambda m: asyncio.run(mon._send_edgeops_alert(m))):
            for _ in range(100):
                mon.record_call("test")

        assert any("CRITICAL" in m for m in fired)
        assert any("100/100" in m for m in fired)


class TestRateMonitorNoDoubleAlert:
    """Crossing 70% threshold twice must fire only one alert for that threshold."""

    def test_no_double_alert(self) -> None:
        mon = _make_monitor()
        alert_count = 0

        def _capture(_msg: str) -> None:
            nonlocal alert_count
            alert_count += 1

        with patch.object(mon, "_fire_and_forget", side_effect=_capture):
            # First crossing: 70 calls
            for _ in range(70):
                mon.record_call("test")
            after_first = alert_count

            # Extra calls that stay below 90% — threshold already marked
            for _ in range(5):
                mon.record_call("test")

        assert alert_count == after_first  # no additional 70% alert


class TestRateMonitorDailyReset:
    """After midnight UTC, counter resets to 0 and thresholds can re-fire."""

    def test_counter_resets_on_new_day(self) -> None:
        mon = _make_monitor()
        for _ in range(50):
            mon.record_call("test")
        assert mon._counters["test"] == 50

        # Simulate a new day by backdating last_reset
        mon._last_reset["test"] = "2000-01-01"

        mon.record_call("test")
        # Should have reset to 0 then incremented to 1
        assert mon._counters["test"] == 1

    def test_alerted_set_clears_on_reset(self) -> None:
        mon = _make_monitor()
        # Trigger 70% alert
        with patch.object(mon, "_fire_and_forget"):
            for _ in range(70):
                mon.record_call("test")
        assert 70 in mon._alerted["test"]

        # Simulate new day
        mon._last_reset["test"] = "2000-01-01"
        mon.record_call("test")
        assert 70 not in mon._alerted["test"]


class TestRateMonitorUsageReport:
    """get_all_usage returns correct shape for all registered providers."""

    def test_usage_report_shape(self) -> None:
        mon = RateMonitor()
        mon.register_provider("cricketdata", daily_limit=100)
        mon.register_provider("api_sports", daily_limit=100, shared_with=["rugby", "mma"])
        mon.register_provider("boxing_data", daily_limit=100)

        for _ in range(42):
            mon.record_call("cricketdata")
        for _ in range(67):
            mon.record_call("api_sports")

        usage = mon.get_all_usage()

        assert set(usage.keys()) == {"cricketdata", "api_sports", "boxing_data"}

        assert usage["cricketdata"]["calls_used"] == 42
        assert usage["cricketdata"]["daily_limit"] == 100
        assert usage["cricketdata"]["pct_used"] == 42.0

        assert usage["api_sports"]["calls_used"] == 67
        assert usage["api_sports"]["pct_used"] == 67.0
        assert "rugby" in usage["api_sports"]["shared_pool_names"]

        assert usage["boxing_data"]["calls_used"] == 0
        assert usage["boxing_data"]["pct_used"] == 0.0
