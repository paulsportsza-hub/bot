"""CARD-REBUILD-04-04 contract tests — D-05 time fallback + D-06 channel raw value.

D-05: build_edge_detail_data() returns "" when no kickoff time is available.
      Template edge_detail.html never renders "KO time TBC" — unknown time shows nothing.
D-06: _get_broadcast_details() returns raw channel string (no emoji prefix).
      Template edge_detail.html has exactly ONE 📺 in channel meta item, no "Ch" prefix.
"""
from __future__ import annotations

from pathlib import Path


def test_time_fallback_is_empty_when_no_kickoff():
    """D-05: time field is '' when _bc_kickoff is absent or has no time part.

    BUILD-KOTIME-FINAL-01: Python must never return 'TBC' for missing time.
    """
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
    assert data["time"] == "", f"Expected '' when no kickoff (BUILD-KOTIME-FINAL-01), got {data['time']!r}"
    assert data["time"] != "TBC", "TBC must never be returned by build_edge_detail_data for missing time"


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


def test_time_empty_when_kickoff_date_only():
    """D-05: date-only kickoff string returns '' for time (not 'TBC').

    BUILD-KOTIME-FINAL-01: date-only fixtures must show nothing for time.
    """
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
    assert data["time"] == "", f"Expected '' for date-only kickoff (BUILD-KOTIME-FINAL-01), got {data['time']!r}"
    assert data["time"] != "TBC", "TBC must never be returned for date-only kickoff"


def test_ko_time_never_shows_tbc():
    """BUILD-KOTIME-FINAL-01: 'TBC' must never appear in the edge_detail template output.

    Regression guard — this bug has been fixed 3+ times. This test ensures it cannot regress:
    1. Python side: build_edge_detail_data() returns time="" (not "TBC") when time is unknown.
    2. Template side: edge_detail.html has no 'KO time TBC' fallback clause.
    """
    from card_data import build_edge_detail_data
    from jinja2 import Environment, FileSystemLoader

    # Build data with NO kickoff time available
    tip = {
        "display_tier": "bronze",
        "ev": 2.0,
        "odds": 2.10,
        "home_team": "Orlando Pirates",
        "away_team": "Kaizer Chiefs",
        "league": "PSL",
        "bookmaker": "GBets",
        "match_id": "orlando_pirates_vs_kaizer_chiefs_2026-04-20",
        # No _bc_kickoff — unknown kickoff time
    }
    data = build_edge_detail_data(tip)

    # 1. Data contract: Python must never put "TBC" into the time field
    assert "TBC" not in str(data.get("time", "")), (
        f"build_edge_detail_data must not return TBC for time, got {data.get('time')!r}"
    )
    assert data.get("time") != "TBC", "time field must not be 'TBC'"

    # 2. Template contract: rendered HTML must never contain 'KO time TBC'
    template_dir = Path(__file__).parent.parent.parent / "card_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    template = env.get_template("edge_detail.html")
    rendered = template.render(**data)

    # Check the specific user-visible regression phrase. Note: base64-encoded image data
    # in the template may contain random character sequences like "TBC", so we must
    # check for the exact phrase not isolated letter sequences.
    assert "KO time TBC" not in rendered, (
        "Template must not render 'KO time TBC' — when time is unknown, show nothing. "
        "Fix: remove the {% else %} · KO time TBC clause from edge_detail.html meta bar."
    )


def test_channel_meta_item_has_single_emoji_no_ch_prefix():
    """FIX-DSTV-CHANNEL-PERM-01: channel rendering permanently removed from edge_detail.html.

    Supersedes D-06 (CARD-FIX-J). The entire channel/broadcast block (ss_logo_b64,
    channel_number, 📺 DStv) was removed permanently. This test now asserts absence.
    """
    template_path = Path(__file__).parent.parent.parent / "card_templates" / "edge_detail.html"
    content = template_path.read_text(encoding="utf-8")

    # FIX-DSTV-CHANNEL-PERM-01: these must NOT appear (channel rendering permanently off)
    assert "ss_logo_b64" not in content, \
        "ss_logo_b64 must NOT be in edge_detail.html (FIX-DSTV-CHANNEL-PERM-01 removed it)"
    assert "channel_number" not in content, \
        "channel_number must NOT be in edge_detail.html (FIX-DSTV-CHANNEL-PERM-01 removed it)"

    # Must NOT have active 📺 channel rendering (Jinja expressions with channel)
    import re
    active_channel = re.search(r'📺.*?\{\{|\{\{.*?channel.*?\}\}', content)
    assert active_channel is None, \
        "edge_detail.html must not have active 📺/channel Jinja rendering (FIX-DSTV-CHANNEL-PERM-01)"

    # Removal comment must be present
    assert "FIX-DSTV-CHANNEL-PERM-01" in content, \
        "edge_detail.html must carry the FIX-DSTV-CHANNEL-PERM-01 removal comment"


def test_template_has_no_ko_time_tbc_fallback():
    """BUILD-KOTIME-FINAL-01: Template source must not contain 'KO time TBC' as a fallback string.

    This is a source-level guard. If the template ever gets this phrase re-introduced
    (e.g. by restoring a backup), this test will catch it immediately without needing Playwright.
    """
    template_path = Path(__file__).parent.parent.parent / "card_templates" / "edge_detail.html"
    content = template_path.read_text(encoding="utf-8")

    assert "KO time TBC" not in content, (
        "edge_detail.html must not contain 'KO time TBC' as a fallback. "
        "When time is unknown, the template must render nothing (no else clause)."
    )
