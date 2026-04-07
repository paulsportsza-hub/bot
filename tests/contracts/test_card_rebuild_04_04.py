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
    assert data["time"] == "TBC", f"Expected 'TBC' when no kickoff, got {data['time']!r}"


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
    assert data["time"] == "TBC", f"Expected 'TBC' for date-only kickoff, got {data['time']!r}"


def test_channel_meta_item_has_single_emoji_no_ch_prefix():
    """D-06: edge_detail.html channel meta item has exactly one 📺 and no 'Ch' prefix."""
    template_path = Path(__file__).parent.parent.parent / "card_templates" / "edge_detail.html"
    content = template_path.read_text(encoding="utf-8")

    # Find the channel meta item line
    channel_lines = [ln for ln in content.splitlines() if "channel" in ln and "meta-item" in ln]
    assert channel_lines, "No channel meta-item line found in template"
    channel_line = channel_lines[0]

    # Must have exactly ONE 📺 emoji
    assert channel_line.count("📺") == 1, (
        f"Expected exactly 1 📺 in channel meta item, got {channel_line.count('📺')}: {channel_line!r}"
    )

    # Must NOT have 'Ch' prefix after the emoji
    assert "📺 Ch " not in channel_line, (
        f"Template still has '📺 Ch' prefix — should be '📺 {{{{ channel }}}}': {channel_line!r}"
    )
    assert "Ch {{ channel }}" not in channel_line, (
        f"Template still has 'Ch' before channel variable: {channel_line!r}"
    )
