"""FIX-REGRESS-D2-DATE-PILL-01 — Date pill sources from fixture kickoff, not generation time.

Regression guards for the three card builders that previously showed blank date
pills when tips were loaded directly (no _bc_kickoff set):

  - _pick_top() (used by build_edge_summary_data)
  - build_edge_picks_data()
  - build_edge_detail_data()

Root cause: kickoff fallback chain read _bc_kickoff / kickoff only.
Tips from _load_tips_from_edge_results / _fetch_hot_tips_from_db carry
commence_time (fixture_mapping.kickoff UTC ISO) but not _bc_kickoff.
Fix: _format_commence_time_sast() added as final fallback in all three paths.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# ── 1. _format_commence_time_sast helper ────────────────────────────────────

class TestFormatCommenceTimeSast:
    def test_utc_z_suffix(self):
        from card_data import _format_commence_time_sast
        result = _format_commence_time_sast("2030-06-15T17:00:00Z")
        assert result, "Should return non-empty string for valid future UTC ISO"
        # Must contain a time component
        import re
        assert re.search(r"\d{1,2}:\d{2}", result), f"No time in result: {result!r}"

    def test_utc_plus00_suffix(self):
        from card_data import _format_commence_time_sast
        result = _format_commence_time_sast("2030-06-15T17:00:00+00:00")
        assert result

    def test_midnight_utc_sentinel_returns_date_only(self):
        """00:00 UTC = 02:00 SAST placeholder must return date without time."""
        from card_data import _format_commence_time_sast
        result = _format_commence_time_sast("2030-06-15T00:00:00Z")
        import re
        # Should NOT contain a time component (02:00 is the sentinel)
        assert not re.search(r"\d{1,2}:\d{2}", result), (
            f"Midnight-UTC sentinel must not include time, got: {result!r}"
        )
        assert result, "Should still return the date part"

    def test_empty_string_returns_empty(self):
        from card_data import _format_commence_time_sast
        assert _format_commence_time_sast("") == ""
        assert _format_commence_time_sast("   ") == ""

    def test_invalid_iso_returns_empty(self):
        from card_data import _format_commence_time_sast
        assert _format_commence_time_sast("not-a-date") == ""


# ── 2. _pick_top / build_edge_summary_data with commence_time only ───────────

def _raw_tip(**kwargs) -> dict:
    """Minimal tip dict with no _bc_kickoff, simulating DB-loaded tips."""
    base = {
        "home_team": "Man City",
        "away_team": "Arsenal",
        "ev": 5.0,
        "odds": 2.10,
        "bookmaker": "Betway",
        "edge_tier": "gold",
        "display_tier": "gold",
        "league": "EPL",
        "match_id": "man_city_vs_arsenal_2030-06-15",
    }
    base.update(kwargs)
    return base


class TestPickTopCommenceTimeFallback:
    """_pick_top must populate date when _bc_kickoff is absent."""

    def test_date_populated_from_commence_time(self):
        from card_data import build_edge_summary_data
        tips = [_raw_tip(commence_time="2030-06-15T17:00:00Z")]
        data = build_edge_summary_data(tips)
        top = data.get("top_pick")
        assert top is not None, "top_pick must be set"
        assert top.get("date"), (
            f"top_pick.date must not be empty when commence_time is set; got: {top!r}"
        )

    def test_time_populated_from_commence_time(self):
        from card_data import build_edge_summary_data
        tips = [_raw_tip(commence_time="2030-06-15T17:00:00Z")]
        data = build_edge_summary_data(tips)
        top = data.get("top_pick")
        assert top is not None
        assert top.get("time"), (
            f"top_pick.time must not be empty for non-sentinel kickoff; got: {top!r}"
        )

    def test_bc_kickoff_takes_priority_over_commence_time(self):
        from card_data import build_edge_summary_data
        tips = [_raw_tip(
            commence_time="2030-06-15T17:00:00Z",
            _bc_kickoff="Tomorrow 20:00",
        )]
        data = build_edge_summary_data(tips)
        top = data.get("top_pick")
        assert top is not None
        assert top.get("date") == "Tomorrow", (
            "_bc_kickoff must take priority over commence_time"
        )
        assert top.get("time") == "20:00"

    def test_blank_when_no_kickoff_fields(self):
        """Without any kickoff fields, date/time should be empty — not crash."""
        from card_data import build_edge_summary_data
        tips = [_raw_tip()]  # no kickoff fields at all
        data = build_edge_summary_data(tips)
        top = data.get("top_pick")
        assert top is not None
        # Should not crash; date/time may be empty
        assert isinstance(top.get("date", ""), str)
        assert isinstance(top.get("time", ""), str)


# ── 3. build_edge_picks_data with commence_time only ────────────────────────

def _all_picks_from_groups(data: dict) -> list:
    """Flatten groups[].picks into a single list."""
    result = []
    for group in data.get("groups", []):
        result.extend(group.get("picks", []))
    return result


class TestEdgePicksDataCommenceTimeFallback:
    def test_date_populated_from_commence_time(self):
        from card_data import build_edge_picks_data
        tips = [_raw_tip(commence_time="2030-06-15T17:00:00Z")]
        data = build_edge_picks_data(tips)
        picks = _all_picks_from_groups(data)
        assert picks, f"Should produce at least one pick; groups={data.get('groups')}"
        p = picks[0]
        assert p.get("date"), (
            f"pick.date must be set from commence_time; got: {p!r}"
        )

    def test_tip_date_field_takes_priority(self):
        from card_data import build_edge_picks_data
        tips = [_raw_tip(
            commence_time="2030-06-15T17:00:00Z",
            date="Thu 12 Jun",
            time="19:30",
        )]
        data = build_edge_picks_data(tips)
        picks = _all_picks_from_groups(data)
        assert picks
        assert picks[0].get("date") == "Thu 12 Jun"


# ── 4. build_edge_detail_data with commence_time only ───────────────────────

class TestEdgeDetailDataCommenceTimeFallback:
    def _minimal_tip(self, **kwargs) -> dict:
        t = _raw_tip(**kwargs)
        # Required fields for build_edge_detail_data
        t.setdefault("outcome", "home")
        t.setdefault("home_wins", 3)
        t.setdefault("draws", 2)
        t.setdefault("away_wins", 1)
        return t

    def test_date_populated_from_commence_time(self):
        from card_data import build_edge_detail_data
        tip = self._minimal_tip(commence_time="2030-06-15T17:00:00Z")
        data = build_edge_detail_data(tip)
        assert data.get("date"), (
            f"date must be set from commence_time; got date={data.get('date')!r}"
        )

    def test_tip_date_field_takes_priority_over_commence_time(self):
        from card_data import build_edge_detail_data
        tip = self._minimal_tip(
            commence_time="2030-06-15T17:00:00Z",
            date="Sat 14 Jun",
            time="15:00",
        )
        data = build_edge_detail_data(tip)
        assert data.get("date") == "Sat 14 Jun"

    def test_bc_kickoff_takes_priority_over_commence_time(self):
        from card_data import build_edge_detail_data
        tip = self._minimal_tip(
            commence_time="2030-06-15T17:00:00Z",
            _bc_kickoff="Tomorrow 20:00",
        )
        data = build_edge_detail_data(tip)
        assert data.get("date") == "Tomorrow"
