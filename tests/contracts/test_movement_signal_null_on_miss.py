"""Regression guard: collect_movement_signal() returns signal_strength=None on lookup miss.

FIX-CORE7-CROSS-SPORT-01: Movement signal was returning 0.5 (NEUTRAL) when
match_movement_summary had no row for the match.  A zero-information signal
pollutes the composite score identically to a confirmed neutral signal.

If this test fails:
  - The lookup-miss path has been reverted to returning _NEUTRAL (0.5)
  - Composite scores for soccer/cricket/rugby will be contaminated with
    phantom 0.5 movement scores when no movement data exists.
"""

import sys
import os
import unittest.mock as mock

# Ensure scrapers is importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
for _p in [os.path.join(_ROOT, "scrapers"), _ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_movement_signal_none_on_lookup_miss():
    """When match_movement_summary has no row, signal_strength must be None."""
    from scrapers.edge.signal_collectors import collect_movement_signal

    # Patch get_movement_summary to return None (no DB row)
    with mock.patch(
        "scrapers.movement.movement_helper.get_movement_summary",
        return_value=None,
    ):
        result = collect_movement_signal("some_team_vs_other_team_2026-04-27", "home")

    assert result["signal_strength"] is None, (
        f"Expected signal_strength=None on lookup miss, got {result['signal_strength']}. "
        "A missing movement row must exclude the signal from composite (not score as 0.5 NEUTRAL)."
    )
    assert result.get("available") is False


def test_movement_signal_none_on_empty_dict():
    """Empty dict from get_movement_summary also triggers None path."""
    from scrapers.edge.signal_collectors import collect_movement_signal

    with mock.patch(
        "scrapers.movement.movement_helper.get_movement_summary",
        return_value={},
    ):
        result = collect_movement_signal("some_team_vs_other_team_2026-04-27", "home")

    assert result["signal_strength"] is None, (
        f"Expected signal_strength=None for empty summary, got {result['signal_strength']}."
    )


def test_movement_signal_real_data_not_none():
    """When movement data is present, a real strength value must be returned."""
    from scrapers.edge.signal_collectors import collect_movement_signal

    fake_summary = {
        "steam_detected": 0,
        "biggest_mover": "home",
        "bookmakers_aligned": 2,
        "home_movement": 0.05,
        "draw_movement": 0.0,
        "away_movement": -0.03,
    }

    with mock.patch(
        "scrapers.movement.movement_helper.get_movement_summary",
        return_value=fake_summary,
    ):
        result = collect_movement_signal("some_team_vs_other_team_2026-04-27", "home")

    assert result["signal_strength"] is not None, (
        "With real movement data, signal_strength must not be None."
    )
    assert 0.0 <= result["signal_strength"] <= 1.0, (
        f"signal_strength {result['signal_strength']} must be in [0, 1]."
    )
