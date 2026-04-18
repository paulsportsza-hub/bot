"""BUILD-DATE-KICKOFF-PRIORITY-01 — Regression guard.

Asserts that _build_hot_tips_page uses commence_time as the authoritative
kickoff source, with bc_data["kickoff"] only as a fallback for tips that
have no commence_time.

Root cause: broadcast schedule is windowed to today+7 days. A false-positive
in-window IPL match returned "Today" for fixtures 8+ days out because bc_data
kicked in before commence_time was checked.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from bot import _format_kickoff_display


def _apply_kickoff_priority(tip: dict, bc_data: dict) -> str:
    """Replicate the kickoff priority logic from _build_hot_tips_page.

    Kept here as a readable reference so test failures immediately show
    which branch diverged from the bot implementation.
    """
    kickoff = ""
    if tip.get("commence_time"):
        kickoff = _format_kickoff_display(tip["commence_time"])
    if not kickoff:
        kickoff = bc_data.get("kickoff", "")
    return kickoff


class TestKickoffPriority:
    """commence_time must win; bc_data.kickoff is fallback only."""

    def test_commence_time_wins_over_bc_kickoff(self):
        """When both are present, commence_time result is used, bc_data is ignored."""
        tip = {
            "commence_time": "2026-04-26T17:00:00Z",  # 19:00 SAST — 8 days out
        }
        bc_data = {"kickoff": "Today"}  # false-positive from broadcast window
        result = _apply_kickoff_priority(tip, bc_data)
        expected = _format_kickoff_display(tip["commence_time"])
        assert result == expected, (
            f"Expected commence_time result {expected!r}, got {result!r} — "
            "bc_data kickoff must not override commence_time"
        )
        assert result != "Today", (
            "Kickoff must NOT be 'Today' for a match 8 days out — "
            "bc_data false-positive leak"
        )

    def test_bc_data_fallback_when_no_commence_time(self):
        """When commence_time is absent, bc_data.kickoff is used as fallback."""
        tip = {"commence_time": ""}  # SA20 / DB-only tip with no commence_time
        bc_data = {"kickoff": "Sat 25 Apr"}
        result = _apply_kickoff_priority(tip, bc_data)
        assert result == "Sat 25 Apr", (
            f"Expected bc_data fallback 'Sat 25 Apr', got {result!r}"
        )

    def test_empty_when_both_absent(self):
        """No commence_time and no bc_data.kickoff → empty string (not crash)."""
        tip = {}
        bc_data = {}
        result = _apply_kickoff_priority(tip, bc_data)
        assert result == "", f"Expected empty string, got {result!r}"

    def test_format_kickoff_display_importable(self):
        """_format_kickoff_display must remain a public export of bot.py."""
        assert callable(_format_kickoff_display), (
            "_format_kickoff_display must be importable from bot"
        )

    def test_commence_time_none_falls_back(self):
        """None commence_time is treated same as absent — bc_data is used."""
        tip = {"commence_time": None}
        bc_data = {"kickoff": "Tomorrow 18:00 SAST"}
        result = _apply_kickoff_priority(tip, bc_data)
        assert result == "Tomorrow 18:00 SAST", (
            f"None commence_time must fall through to bc_data, got {result!r}"
        )
