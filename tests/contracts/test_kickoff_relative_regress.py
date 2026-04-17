"""FIX-KICKOFF-RELATIVE-01 — Contract tests for _split_kickoff timezone-suffix handling.

Verifies that relative date labels (Today/Tomorrow) correctly split when the
kickoff string carries a trailing timezone suffix (e.g. " SAST", " UTC", " CAT").
Root cause: _split_kickoff regex required string to END with HH:MM, but
_format_kickoff_display() appends " SAST" making the regex fail.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from card_data import _split_kickoff


class TestSplitKickoffTimezoneStrip:
    """_split_kickoff must handle trailing SAST/UTC/CAT suffixes."""

    def test_today_sast_splits_correctly(self):
        date, time = _split_kickoff("Today 14:55 SAST")
        assert date == "Today", f"Expected 'Today', got {date!r}"
        assert time == "14:55", f"Expected '14:55', got {time!r}"

    def test_tomorrow_sast_splits_correctly(self):
        date, time = _split_kickoff("Tomorrow 19:30 SAST")
        assert date == "Tomorrow", f"Expected 'Tomorrow', got {date!r}"
        assert time == "19:30", f"Expected '19:30', got {time!r}"

    def test_today_utc_splits_correctly(self):
        date, time = _split_kickoff("Today 16:00 UTC")
        assert date == "Today"
        assert time == "16:00"

    def test_today_cat_splits_correctly(self):
        date, time = _split_kickoff("Today 20:00 CAT")
        assert date == "Today"
        assert time == "20:00"

    def test_absolute_date_sast_splits_correctly(self):
        # "Thu 23 Apr 18:00 SAST" should split even with timezone
        date, time = _split_kickoff("Thu 23 Apr 18:00 SAST")
        assert time == "18:00", f"Expected '18:00', got {time!r}"
        assert "23 Apr" in date

    def test_no_timezone_still_works(self):
        # Existing behaviour preserved: no timezone suffix
        date, time = _split_kickoff("Today 14:55")
        assert date == "Today"
        assert time == "14:55"

    def test_bullet_separator_unaffected(self):
        # Mid-dot separator path must be unaffected by the fix
        date, time = _split_kickoff("Fri 6 Mar \u00b7 15:00")
        assert date == "Fri 6 Mar"
        assert time == "15:00"

    def test_date_only_returns_empty_time(self):
        date, time = _split_kickoff("Tomorrow")
        assert date == "Tomorrow"
        assert time == ""

    def test_empty_string_returns_empty_pair(self):
        date, time = _split_kickoff("")
        assert date == ""
        assert time == ""

    def test_time_preserved_without_sast_suffix_round_trip(self):
        """Time value must NOT include 'SAST' after splitting."""
        _, time = _split_kickoff("Tomorrow 08:30 SAST")
        assert "SAST" not in time
        assert time == "08:30"
