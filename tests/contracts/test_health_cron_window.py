"""test_health_cron_window.py — Contract suite for BUILD-HEALTH-CRON-AWARE-01.

Covers the 7 scenarios from INV-HEALTH-MONITOR-CRON-AWARE-01 §5 (Table-A):

  1. Table-A sources green outside their active window
  2. In-window overdue → red
  3. Weekly cron green on Wednesday morning
  4. Multi-window cron honours both windows
  5. Missing cron_schedule falls back to status_from_minutes()
  6. DST/UTC+2 stability (SAST has no DST — fixed offset)
  7. status_from_minutes() untouched when no cron

All times are UTC datetimes; SAST conversion (+2h) is done inside cron_window.
"""

import sys
import os
import pytest
from datetime import datetime, timezone, timedelta

# Add home scripts dir directly (not the bot/scripts package) so cron_window
# and health_checker can be imported without shadowing by bot/scripts/__init__.py
_HOME_SCRIPTS = os.path.join(os.path.expanduser("~"), "scripts")
if _HOME_SCRIPTS not in sys.path:
    sys.path.insert(0, _HOME_SCRIPTS)

import cron_window  # /home/paulsportsza/scripts/cron_window.py
from health_checker import status_from_minutes, compute_status  # health_checker.py


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc(year, month, day, hour, minute=0):
    """Build a UTC-aware datetime."""
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _sast_to_utc(year, month, day, hour, minute=0):
    """Return UTC datetime for a given SAST (UTC+2) wall time."""
    return _utc(year, month, day, hour, minute) - timedelta(hours=2)


def _make_row(cron_schedule, interval):
    """Build a minimal source_row dict for compute_status()."""
    return {
        'source_id': 'test_source',
        'expected_interval_minutes': interval,
        'cron_schedule': cron_schedule,
    }


# ---------------------------------------------------------------------------
# Scenario 1 — Table-A sources: green outside their active window
# ---------------------------------------------------------------------------

class TestTableASourcesGreenOutsideWindow:
    """sharp_closing_capture, fixture_api_football, sharp_clv_backfill etc.
    should show green overnight even with their tight in-window SLAs, because
    the last window close was well within one interval of last_success."""

    def test_sharp_closing_capture_overnight_green(self):
        # sharp_closing_capture: cron 5,20,35,50 12-21 * * *, SLA 30 min
        # Checked at 03:00 SAST → outside window (window hours: 12-21 SAST)
        # last_success was at 21:50 SAST yesterday (within 30 min of window close)
        cron = "5,20,35,50 12-21 * * *"
        interval = 30

        now_utc = _sast_to_utc(2026, 4, 17, 3, 0)    # 03:00 SAST
        last_fire_sast = _sast_to_utc(2026, 4, 16, 21, 50)  # 21:50 SAST yesterday
        minutes_since = int((now_utc - last_fire_sast).total_seconds() / 60)  # ~310 min

        row = _make_row(cron, interval)
        status = compute_status(row, minutes_since, now_utc)
        assert status == 'green', (
            f"Expected green outside window (minutes_since={minutes_since}), got {status!r}"
        )

    def test_fixture_api_football_overnight_green(self):
        # fixture_api_football: cron 8,23,38,53 12-21 * * *, SLA 30 min (workaround: 1440)
        # The 1440 SLA is the current DB value (workaround). We test cron logic with
        # the tight SLA to verify the algorithm: last_success within 30 min of window close.
        cron = "8,23,38,53 12-21 * * *"
        interval = 30

        now_utc = _sast_to_utc(2026, 4, 17, 4, 0)    # 04:00 SAST
        last_fire_sast = _sast_to_utc(2026, 4, 16, 21, 53)  # 21:53 SAST yesterday
        minutes_since = int((now_utc - last_fire_sast).total_seconds() / 60)

        row = _make_row(cron, interval)
        status = compute_status(row, minutes_since, now_utc)
        assert status == 'green'

    def test_sharp_clv_backfill_overnight_green(self):
        # sharp_clv_backfill: cron */30 10-22 * * *, SLA 45 min
        # Checked at 02:00 SAST; last fire was 22:00 SAST yesterday (within 45 min of close)
        cron = "*/30 10-22 * * *"
        interval = 45

        now_utc = _sast_to_utc(2026, 4, 17, 2, 0)
        last_fire_sast = _sast_to_utc(2026, 4, 16, 22, 0)
        minutes_since = int((now_utc - last_fire_sast).total_seconds() / 60)

        row = _make_row(cron, interval)
        status = compute_status(row, minutes_since, now_utc)
        assert status == 'green'

    def test_news_injuries_between_windows_green(self):
        # news_injuries: cron 7 6,12,18 * * *, SLA 30 min
        # Checked at 09:00 SAST; last fire was 06:07 SAST (within 30 min of 06:07 window close)
        cron = "7 6,12,18 * * *"
        interval = 30

        now_utc = _sast_to_utc(2026, 4, 17, 9, 0)
        last_fire_sast = _sast_to_utc(2026, 4, 17, 6, 7)
        minutes_since = int((now_utc - last_fire_sast).total_seconds() / 60)  # ~173 min

        row = _make_row(cron, interval)
        status = compute_status(row, minutes_since, now_utc)
        assert status == 'green'

    def test_sharp_clv_tracker_overnight_green(self):
        # sharp_clv_tracker: cron 6 13-22 * * *, SLA 120 min
        # Checked at 05:00 SAST; last fire was 22:06 SAST yesterday (within 120 min of close)
        cron = "6 13-22 * * *"
        interval = 120

        now_utc = _sast_to_utc(2026, 4, 17, 5, 0)
        last_fire_sast = _sast_to_utc(2026, 4, 16, 22, 6)
        minutes_since = int((now_utc - last_fire_sast).total_seconds() / 60)

        row = _make_row(cron, interval)
        status = compute_status(row, minutes_since, now_utc)
        assert status == 'green'

    def test_edge_settlement_between_even_hour_windows_green(self):
        # edge_settlement: cron 32 1,3,5,7,9,11,13,15,17,19,21,23 * * *, SLA 180 min
        # Checked at 14:00 SAST (even hour — not in odd-hours set)
        # Last fire was 13:32 SAST (28 minutes ago)
        cron = "32 1,3,5,7,9,11,13,15,17,19,21,23 * * *"
        interval = 180

        now_utc = _sast_to_utc(2026, 4, 17, 14, 0)
        last_fire_sast = _sast_to_utc(2026, 4, 17, 13, 32)
        minutes_since = int((now_utc - last_fire_sast).total_seconds() / 60)  # 28 min

        row = _make_row(cron, interval)
        status = compute_status(row, minutes_since, now_utc)
        assert status == 'green'


# ---------------------------------------------------------------------------
# Scenario 2 — In-window overdue → red
# ---------------------------------------------------------------------------

class TestInWindowOverdueRed:
    """When the current time IS inside the cron window and last_success is
    overdue by more than 3× the SLA, status must be red/black."""

    def test_sharp_closing_capture_in_window_overdue_red(self):
        # sharp_closing_capture inside window (15:00 SAST), SLA 30 min
        # last fire was 2 hours ago — clearly overdue
        cron = "5,20,35,50 12-21 * * *"
        interval = 30

        now_utc = _sast_to_utc(2026, 4, 17, 15, 0)   # 15:00 SAST — inside window
        last_fire_sast = _sast_to_utc(2026, 4, 17, 13, 0)  # 120 min ago
        minutes_since = int((now_utc - last_fire_sast).total_seconds() / 60)  # 120 min

        row = _make_row(cron, interval)
        status = compute_status(row, minutes_since, now_utc)
        # 120 min >> 30 min * 3 threshold → should be red or black
        assert status in ('red', 'black'), (
            f"Expected red/black for overdue in-window source, got {status!r}"
        )

    def test_fixture_api_football_in_window_overdue_red(self):
        cron = "8,23,38,53 12-21 * * *"
        interval = 30

        now_utc = _sast_to_utc(2026, 4, 17, 16, 0)   # inside window
        last_fire_sast = _sast_to_utc(2026, 4, 17, 13, 0)  # 180 min ago
        minutes_since = int((now_utc - last_fire_sast).total_seconds() / 60)

        row = _make_row(cron, interval)
        status = compute_status(row, minutes_since, now_utc)
        assert status in ('red', 'black')


# ---------------------------------------------------------------------------
# Scenario 3 — Weekly cron green on Wednesday morning
# ---------------------------------------------------------------------------

class TestWeeklyCronGreenMidWeek:
    """coaches_transfermarkt: cron 0 4 * * 1 (Monday 04:00 SAST), SLA 11520 min (8 days).
    On Wednesday morning the checker runs ~50 hours after Monday's fire — still green
    because 50h < 11520 * 0.85 = 9792 minutes."""

    def test_coaches_transfermarkt_green_wednesday(self):
        # 0 4 * * 1 = every Monday at 04:00 SAST
        cron = "0 4 * * 1"
        interval = 11520  # 8 days in minutes

        # Wednesday 03:00 SAST
        now_utc = _sast_to_utc(2026, 4, 15, 3, 0)  # 2026-04-15 = Wednesday
        # Last fire: Monday 04:00 SAST = 2026-04-13 04:00 SAST
        last_fire_sast = _sast_to_utc(2026, 4, 13, 4, 0)
        minutes_since = int((now_utc - last_fire_sast).total_seconds() / 60)  # ~2820 min

        row = _make_row(cron, interval)
        status = compute_status(row, minutes_since, now_utc)
        assert status == 'green', (
            f"Weekly cron should be green on Wednesday (minutes_since={minutes_since}), got {status!r}"
        )

    def test_coaches_transfermarkt_date_is_wednesday(self):
        """Verify our test date is actually a Wednesday."""
        dt = datetime(2026, 4, 15)
        assert dt.weekday() == 2, "2026-04-15 must be Wednesday for test to be valid"

    def test_weekly_cron_outside_window_returns_green(self):
        """When outside the (narrow) Monday 04:xx window, cron-window logic
        should compute from last_window_close and return green if recently fired."""
        cron = "0 4 * * 1"
        interval = 11520

        # Tuesday 10:00 SAST — outside Monday's window
        now_utc = _sast_to_utc(2026, 4, 14, 10, 0)
        last_fire_sast = _sast_to_utc(2026, 4, 13, 4, 0)  # Monday 04:00
        minutes_since = int((now_utc - last_fire_sast).total_seconds() / 60)

        row = _make_row(cron, interval)
        status = compute_status(row, minutes_since, now_utc)
        assert status == 'green'


# ---------------------------------------------------------------------------
# Scenario 4 — Multi-window cron honours both windows
# ---------------------------------------------------------------------------

class TestMultiWindowCron:
    """Bookmaker scrapers use semicolon-separated multi-window crons.
    The checker should be green in ALL windows, not just the first."""

    BK_CRON = "*/10 12-21 * * *; */20 8-11,22-23 * * *; */30 0-7 * * *"
    BK_INTERVAL = 90

    def test_peak_window_green(self):
        # 14:00 SAST — inside peak window 12-21
        now_utc = _sast_to_utc(2026, 4, 17, 14, 0)
        windows = cron_window.parse_multi(self.BK_CRON)
        assert cron_window.is_in_any_window(windows, now_utc) is True

    def test_shoulder_window_green(self):
        # 09:00 SAST — inside shoulder window 8-11
        now_utc = _sast_to_utc(2026, 4, 17, 9, 0)
        windows = cron_window.parse_multi(self.BK_CRON)
        assert cron_window.is_in_any_window(windows, now_utc) is True

    def test_overnight_window_green(self):
        # 03:00 SAST — inside overnight window 0-7
        now_utc = _sast_to_utc(2026, 4, 17, 3, 0)
        windows = cron_window.parse_multi(self.BK_CRON)
        assert cron_window.is_in_any_window(windows, now_utc) is True

    def test_multi_window_always_in_window(self):
        # Bookmakers cover ALL 24 hours — is_in_any_window should always be True
        for hour in range(24):
            now_utc = _sast_to_utc(2026, 4, 17, hour, 0)
            windows = cron_window.parse_multi(self.BK_CRON)
            assert cron_window.is_in_any_window(windows, now_utc) is True, \
                f"Expected in-window at SAST hour {hour}"

    def test_parse_multi_splits_correctly(self):
        windows = cron_window.parse_multi(self.BK_CRON)
        assert len(windows) == 3
        assert windows[0] == "*/10 12-21 * * *"
        assert windows[1] == "*/20 8-11,22-23 * * *"
        assert windows[2] == "*/30 0-7 * * *"


# ---------------------------------------------------------------------------
# Scenario 5 — Missing cron_schedule falls back to status_from_minutes()
# ---------------------------------------------------------------------------

class TestMissingCronFallback:
    """Sources without a cron_schedule (or with on-demand) must fall back to
    the existing status_from_minutes() logic unchanged."""

    def test_no_cron_falls_back(self):
        row = _make_row('', 1440)
        now_utc = _utc(2026, 4, 17, 12, 0)
        minutes_since = 100
        expected = status_from_minutes(minutes_since, 1440)
        actual = compute_status(row, minutes_since, now_utc)
        assert actual == expected

    def test_on_demand_cron_falls_back(self):
        row = _make_row('on-demand', 0)
        now_utc = _utc(2026, 4, 17, 12, 0)
        # interval=0 → black (handled before compute_status reaches cron logic)
        # Test that compute_status doesn't crash
        assert compute_status(row, 0, now_utc) == 'black'

    def test_none_cron_falls_back(self):
        row = {'source_id': 'x', 'expected_interval_minutes': 480, 'cron_schedule': None}
        now_utc = _utc(2026, 4, 17, 12, 0)
        minutes_since = 300
        expected = status_from_minutes(minutes_since, 480)
        assert compute_status(row, minutes_since, now_utc) == expected

    def test_unparseable_cron_falls_back(self):
        # 3-field cron (invalid) should fall back to status_from_minutes()
        row = _make_row('bad cron string', 60)
        now_utc = _utc(2026, 4, 17, 12, 0)
        minutes_since = 90
        expected = status_from_minutes(minutes_since, 60)
        assert compute_status(row, minutes_since, now_utc) == expected


# ---------------------------------------------------------------------------
# Scenario 6 — DST / UTC+2 stability (SAST has no DST)
# ---------------------------------------------------------------------------

class TestSASTNoDST:
    """SAST is always UTC+2. There is no DST. Assert that the offset is
    consistent across seasons (summer and winter in South Africa)."""

    def test_january_sast_offset(self):
        # January (Southern Hemisphere summer) — UTC+2
        now_utc = _utc(2026, 1, 15, 10, 0)  # 10:00 UTC = 12:00 SAST
        now_sast = cron_window._to_sast(now_utc)
        assert now_sast.hour == 12

    def test_july_sast_offset(self):
        # July (Southern Hemisphere winter) — UTC+2 (no DST change)
        now_utc = _utc(2026, 7, 15, 10, 0)  # 10:00 UTC = 12:00 SAST
        now_sast = cron_window._to_sast(now_utc)
        assert now_sast.hour == 12

    def test_dst_boundary_march_stable(self):
        # European DST changes in March/October — SAST must remain UTC+2
        now_utc = _utc(2026, 3, 29, 0, 0)  # European DST starts ~this date
        now_sast = cron_window._to_sast(now_utc)
        assert now_sast.hour == 2  # 00:00 UTC → 02:00 SAST always

    def test_window_check_utc2_correct(self):
        # Cron 12 0,3,6,9,12,15,18,21 * * * (sharp_odds_api, runs at UTC hours)
        # At 10:00 UTC = 12:00 SAST, hour 10 is NOT in {0,3,6,9,12,15,18,21}
        # But SAST hour 12 IS in that set... wait, this cron is UTC-scheduled.
        # Our cron_window interprets ALL crons as SAST. For a UTC cron at hour 12,
        # that appears at SAST hour 14. Test that the SAST interpretation is used.
        cron = "12 0,3,6,9,12,15,18,21 * * *"
        # 10:00 UTC = 12:00 SAST; SAST hour 12 IS in {0,3,6,9,12,15,18,21} → in window
        now_utc = _utc(2026, 4, 17, 10, 0)
        assert cron_window.is_in_window(cron, now_utc) is True


# ---------------------------------------------------------------------------
# Scenario 7 — status_from_minutes() untouched when no cron string
# ---------------------------------------------------------------------------

class TestStatusFromMinutesUnchanged:
    """status_from_minutes() must retain its exact pre-wave behaviour.
    compute_status() with no cron must produce identical results to calling
    status_from_minutes() directly."""

    @pytest.mark.parametrize("elapsed,interval,expected", [
        (0, 30, 'green'),
        (10, 30, 'green'),
        (15, 30, 'yellow'),   # 15 >= 30*0.5
        (29, 30, 'yellow'),
        (30, 30, 'red'),      # 30 >= 30
        (89, 30, 'red'),      # 89 < 30*3
        (90, 30, 'black'),    # 90 >= 30*3
        (720, 1440, 'green'),      # 720 < 1440*0.85=1224 — daily green band
        (1224, 1440, 'yellow'),
        (1440, 1440, 'red'),
        (4321, 1440, 'black'),
        (0, 0, 'black'),           # on-demand
    ])
    def test_status_from_minutes_parametrized(self, elapsed, interval, expected):
        assert status_from_minutes(elapsed, interval) == expected

    def test_compute_status_no_cron_matches_status_from_minutes(self):
        """compute_status with no cron must equal status_from_minutes directly."""
        now_utc = _utc(2026, 4, 17, 12, 0)
        for elapsed in (0, 15, 30, 90, 720, 1440, 4000):
            for interval in (30, 120, 1440):
                row = _make_row('', interval)
                assert compute_status(row, elapsed, now_utc) == status_from_minutes(elapsed, interval), \
                    f"Mismatch at elapsed={elapsed}, interval={interval}"


# ---------------------------------------------------------------------------
# Additional unit tests for cron_window module functions
# ---------------------------------------------------------------------------

class TestCronWindowFunctions:
    """Direct unit tests for the cron_window module's parsing and fire-time logic."""

    def test_parse_multi_empty(self):
        assert cron_window.parse_multi('') == []

    def test_parse_multi_on_demand(self):
        assert cron_window.parse_multi('on-demand') == []

    def test_parse_multi_single(self):
        result = cron_window.parse_multi("5,20,35,50 12-21 * * *")
        assert result == ["5,20,35,50 12-21 * * *"]

    def test_parse_multi_semicolon(self):
        result = cron_window.parse_multi("*/10 12-21 * * *; */30 0-7 * * *")
        assert len(result) == 2

    def test_is_in_window_true(self):
        # 14:00 SAST = 12:00 UTC — inside 12-21 SAST window
        now_utc = _sast_to_utc(2026, 4, 17, 14, 0)
        assert cron_window.is_in_window("5,20,35,50 12-21 * * *", now_utc) is True

    def test_is_in_window_false(self):
        # 03:00 SAST — outside 12-21 SAST window
        now_utc = _sast_to_utc(2026, 4, 17, 3, 0)
        assert cron_window.is_in_window("5,20,35,50 12-21 * * *", now_utc) is False

    def test_is_in_window_on_demand(self):
        now_utc = _utc(2026, 4, 17, 12, 0)
        assert cron_window.is_in_window("on-demand", now_utc) is False

    def test_previous_fire_finds_last_fire(self):
        # sharp_clv_tracker: 6 13-22 * * *; checked at 22:10 SAST
        cron = "6 13-22 * * *"
        now_utc = _sast_to_utc(2026, 4, 17, 22, 10)
        result = cron_window.previous_fire(cron, now_utc)
        assert result is not None
        result_sast = result + timedelta(hours=2)
        # Previous fire should be 22:06 SAST
        assert result_sast.hour == 22
        assert result_sast.minute == 6

    def test_next_fire_finds_next_fire(self):
        # sharp_clv_tracker: 6 13-22 * * *; checked at 13:00 SAST
        cron = "6 13-22 * * *"
        now_utc = _sast_to_utc(2026, 4, 17, 13, 0)
        result = cron_window.next_fire(cron, now_utc)
        assert result is not None
        result_sast = result + timedelta(hours=2)
        # Next fire should be 13:06 SAST
        assert result_sast.hour == 13
        assert result_sast.minute == 6

    def test_last_window_close_finds_latest_across_windows(self):
        # Multi-window where windows[1] had a more recent fire
        cron1 = "5,20,35,50 12-21 * * *"
        cron2 = "7 6,12,18 * * *"
        now_utc = _sast_to_utc(2026, 4, 17, 9, 30)  # 09:30 SAST, outside both
        windows = [cron1, cron2]
        result = cron_window.last_window_close(windows, now_utc)
        # Most recent prior fire: cron2 fired at 06:07 SAST, cron1 at 21:50 yesterday
        # 06:07 > 21:50(yesterday) → result should be 06:07 SAST today
        assert result is not None
        result_sast = result + timedelta(hours=2)
        assert result_sast.hour == 6
        assert result_sast.minute == 7

    def test_parse_field_star(self):
        from scripts.cron_window import _parse_field
        result = _parse_field('*', 0, 59)
        assert 0 in result and 59 in result and len(result) == 60

    def test_parse_field_step(self):
        from scripts.cron_window import _parse_field
        result = _parse_field('*/30', 0, 59)
        assert result == frozenset({0, 30})

    def test_parse_field_range(self):
        from scripts.cron_window import _parse_field
        result = _parse_field('12-21', 0, 23)
        assert result == frozenset(range(12, 22))

    def test_parse_field_comma_list(self):
        from scripts.cron_window import _parse_field
        result = _parse_field('5,20,35,50', 0, 59)
        assert result == frozenset({5, 20, 35, 50})
