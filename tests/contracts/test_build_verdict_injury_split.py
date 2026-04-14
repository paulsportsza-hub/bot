"""BUILD-VERDICT-INJURY-SPLIT-01 — Contract tests.

Verifies:
1. _build_verdict_with_injuries() is removed from card_data.
2. build_edge_detail_data() passes verdict raw (no injury appended).
3. home_injuries / away_injuries are separate template variables.
4. edge_detail.html injury section renders player names only — no status text.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import card_data


# ── 1. _build_verdict_with_injuries is gone ───────────────────────────────────

def test_build_verdict_with_injuries_removed():
    """Function must not exist on card_data module (BUILD-VERDICT-INJURY-SPLIT-01)."""
    assert not hasattr(card_data, "_build_verdict_with_injuries"), (
        "_build_verdict_with_injuries() still exists — must be removed"
    )


# ── 2. Verdict is raw — no injury appending ───────────────────────────────────

def test_verdict_raw_no_injury():
    """Verdict key in return dict must match the raw verdict string exactly."""
    from card_data import build_edge_detail_data

    raw_verdict = "Back Chiefs at 1.95 — strong home record and fresh legs."
    tip = {
        "home": "Kaizer Chiefs",
        "away": "Orlando Pirates",
        "league": "PSL",
        "verdict": raw_verdict,
        "home_injuries": ["Patrick Maswanganyi (knee)", "Edmilson Dove (hamstring)"],
        "away_injuries": ["Tshegofatso Mabasa (thigh)"],
    }
    data = build_edge_detail_data(tip)
    assert data["verdict"] == raw_verdict, (
        f"Expected raw verdict, got: {data['verdict']!r}"
    )
    assert "🏥" not in data["verdict"], "Injury emoji must not appear in verdict"
    assert "Maswanganyi" not in data["verdict"], "Player names must not appear in verdict"


def test_verdict_raw_when_no_injuries():
    """Verdict is unchanged when there are no injuries."""
    from card_data import build_edge_detail_data

    raw_verdict = "Lay the draw — both sides score here."
    tip = {
        "home": "Sundowns",
        "away": "SuperSport",
        "league": "PSL",
        "verdict": raw_verdict,
    }
    data = build_edge_detail_data(tip)
    assert data["verdict"] == raw_verdict


# ── 3. Injuries passed as separate template variables ─────────────────────────

def test_home_away_injuries_are_template_vars():
    """home_injuries and away_injuries must be separate keys in the data dict."""
    from card_data import build_edge_detail_data

    tip = {
        "home": "Kaizer Chiefs",
        "away": "Orlando Pirates",
        "league": "PSL",
        "home_injuries": ["Patrick Maswanganyi (knee)"],
        "away_injuries": ["Tshegofatso Mabasa (thigh)"],
    }
    data = build_edge_detail_data(tip)
    assert "home_injuries" in data
    assert "away_injuries" in data
    assert data["home_injuries"] == ["Patrick Maswanganyi (knee)"]
    assert data["away_injuries"] == ["Tshegofatso Mabasa (thigh)"]


def test_injuries_default_to_empty_lists():
    """Missing injury fields default to empty lists."""
    from card_data import build_edge_detail_data

    tip = {"home": "Chiefs", "away": "Pirates", "league": "PSL"}
    data = build_edge_detail_data(tip)
    assert data["home_injuries"] == []
    assert data["away_injuries"] == []


# ── 4. Template renders injury section with names only ────────────────────────

def _render_template(template_vars: dict) -> str:
    """Render edge_detail.html via Jinja2 (no Playwright required)."""
    from jinja2 import Environment, FileSystemLoader

    template_dir = Path(__file__).parent.parent.parent / "card_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    tmpl = env.get_template("edge_detail.html")
    return tmpl.render(**template_vars)


def _minimal_tip_data(**overrides) -> dict:
    """Minimal data dict for template rendering."""
    base = {
        "tier": "gold",
        "tier_color": "#FFD700",
        "tier_emoji": "🥇",
        "tier_name": "GOLDEN EDGE",
        "ev": 5.2,
        "home": "Kaizer Chiefs",
        "away": "Orlando Pirates",
        "league": "PSL",
        "date": "Sat 14 Apr",
        "time": "15:30",
        "pick": "Home Win",
        "pick_odds": "1.95",
        "bookmaker": "Hollywoodbets",
        "all_odds": [],
        "signals": [],
        "fair_value": 60,
        "confidence": 70,
        "confidence_tier": "high",
        "h2h_total": 0,
        "h2h_home_wins": 0,
        "h2h_draws": 0,
        "h2h_away_wins": 0,
        "home_injuries": [],
        "away_injuries": [],
        "verdict": "Back Chiefs.",
        "top_tipsters": [],
        "header_logo_b64": "",
        "model_badge": None,
        "home_form": [],
        "away_form": [],
        "channel_number": "",
        "channel_is_ss": False,
        "ss_logo_b64": "",
    }
    base.update(overrides)
    return base


def test_template_injury_section_shows_names_only():
    """Injury section renders player names without status text."""
    data = _minimal_tip_data(
        home_injuries=["Patrick Maswanganyi (knee ligament)", "Edmilson Dove (hamstring)"],
        away_injuries=["Tshegofatso Mabasa (thigh)"],
    )
    html = _render_template(data)

    assert "INJURIES" in html, "Injury section header missing"
    assert "Patrick Maswanganyi" in html
    assert "Edmilson Dove" in html
    assert "Mabasa" in html

    # Status text must not appear
    assert "knee ligament" not in html, "Status text 'knee ligament' must not appear"
    assert "hamstring" not in html, "Status text 'hamstring' must not appear"
    assert "thigh" not in html, "Status text 'thigh' must not appear"


def test_template_injury_section_max_two_per_team():
    """Template caps players at 2 per team via Jinja slice."""
    data = _minimal_tip_data(
        home_injuries=[
            "Player One (knee)",
            "Player Two (hamstring)",
            "Player Three (calf)",
        ],
        away_injuries=[],
    )
    html = _render_template(data)
    assert "Player One" in html
    assert "Player Two" in html
    assert "Player Three" not in html, "Third player must be hidden (max 2 per team)"


def test_template_injury_section_hidden_when_no_injuries():
    """Injury section div must not render when both lists are empty."""
    data = _minimal_tip_data(home_injuries=[], away_injuries=[])
    html = _render_template(data)
    assert "INJURIES" not in html, "Injury section must be hidden when no injuries"
    assert 'class="injury-section"' not in html


def test_template_injury_section_hidden_when_vars_absent():
    """Template gracefully omits section when template vars are falsy."""
    data = _minimal_tip_data()
    html = _render_template(data)
    assert "INJURIES" not in html
    assert 'class="injury-section"' not in html
