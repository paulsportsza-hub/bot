"""CARD-REBUILD-04-04 contract tests — D-05 time fallback + D-06 channel raw value.

D-05: build_edge_detail_data() returns "TBC" when no kickoff time is available.
D-06: _get_broadcast_details() returns raw channel string (no emoji prefix).
      Template edge_detail.html has exactly ONE 📺 in channel meta item, no "Ch" prefix.
"""
from __future__ import annotations

from pathlib import Path


def test_time_fallback_is_tbc_when_no_kickoff():
    """D-05: time field is 'TBC' when _bc_kickoff is absent or has no time part."""
    from card_data import build_edge_detail_data

    tip = {
        "display_tier": "gold",
        "ev": 8.0,
        "odds": 1.90,
        "home_team": "Everton",
        "away_team": "Liverpool",
        "league": "EPL",
        # No _bc_kickoff, no kickoff, no time — simulates match with unknown KO
        "bookmaker": "Betway",
        "match_id": "everton_vs_liverpool_2026-04-19",
    }
    data = build_edge_detail_data(tip)
    # BUILD-KO-TIME-FIX-01: code returns "" for missing time; template renders "KO time TBC"
    assert data["time"] == "", f"Expected '' when no kickoff (BUILD-KO-TIME-FIX-01), got {data['time']!r}"


def test_time_preserved_when_kickoff_has_time():
    """D-05: valid time extracted from _bc_kickoff is NOT replaced by TBC."""
    from card_data import build_edge_detail_data

    tip = {
        "display_tier": "gold",
        "ev": 8.0,
        "odds": 1.90,
        "home_team": "Arsenal",
        "away_team": "Liverpool",
        "league": "EPL",
        "_bc_kickoff": "Sun 8 Apr \u00b7 16:30",
        "bookmaker": "Betway",
    }
    data = build_edge_detail_data(tip)
    assert data["time"] == "16:30", f"Expected '16:30', got {data['time']!r}"
    assert data["date"] == "Sun 8 Apr", f"Expected 'Sun 8 Apr', got {data['date']!r}"


def test_time_tbc_when_kickoff_date_only():
    """D-05: date-only kickoff string returns TBC for time."""
    from card_data import build_edge_detail_data

    tip = {
        "display_tier": "silver",
        "ev": 4.0,
        "home_team": "Mamelodi Sundowns",
        "away_team": "Kaizer Chiefs",
        "league": "PSL",
        "_bc_kickoff": "Sat 19 Apr",  # date only, no time component
        "bookmaker": "Hollywoodbets",
    }
    data = build_edge_detail_data(tip)
    assert data["date"] == "Sat 19 Apr"
    # BUILD-KO-TIME-FIX-01: code returns "" for missing time; template renders "KO time TBC"
    assert data["time"] == "", f"Expected '' for date-only kickoff (BUILD-KO-TIME-FIX-01), got {data['time']!r}"


def test_channel_meta_item_has_single_emoji_no_ch_prefix():
    """D-06 (CARD-FIX-J): channel meta bar supports SS logo path + 📺 fallback, no 'Ch' prefix."""
    template_path = Path(__file__).parent.parent.parent / "card_templates" / "edge_detail.html"
    content = template_path.read_text(encoding="utf-8")

    # Must have ss_logo_b64 path for SuperSport channels (CARD-FIX-J)
    assert "ss_logo_b64" in content, "Template must have SS logo path for SuperSport channels"
    assert "channel_number" in content, "Template must reference channel_number variable"

    # Must still have 📺 fallback for non-SS channels
    assert "📺" in content, "Template must have 📺 fallback for non-SS channels"

    # Must NOT have 'Ch' prefix
    assert "📺 Ch " not in content, "Template must not have '📺 Ch' prefix"
    assert "Ch {{ channel }}" not in content, "Template must not have 'Ch' before channel variable"
