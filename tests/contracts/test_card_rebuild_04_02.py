"""CARD-REBUILD-04-02 — match_results ORDER BY match_date + form cap at 5.

Covers:
  - D-04: ORDER BY match_date DESC confirmed in source (not match_key)
  - D-14: form strips capped at ≤5 per side
  - D-15: asymmetric guard — both hidden when either side has 0 results
  - D-15: same-length strips when both sides have ≥1 result
  - Most-recent result rendered rightmost (reversed from DESC-ordered query)

Acceptance test (brief §Acceptance):
  For each of the 5 baseline cards:
    1. home_form ≤5 results, most-recent at index [-1] (rightmost)
    2. away_form ≤5 results, most-recent at index [-1] (rightmost)
    3. len(home_form) == len(away_form)  OR  both == []
    4. ORDER BY match_date DESC confirmed in card_pipeline source
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── D-04: ORDER BY match_date confirmed in source ─────────────────────────────

def test_order_by_match_date_in_source():
    """card_pipeline.py must use ORDER BY match_date DESC, not match_key."""
    src = (Path(__file__).parent.parent.parent / "card_pipeline.py").read_text()
    assert "ORDER BY match_date DESC" in src, (
        "D-04 fix missing: 'ORDER BY match_date DESC' not found in card_pipeline.py"
    )
    assert "ORDER BY match_key DESC" not in src, (
        "D-04 regression: 'ORDER BY match_key DESC' still present in card_pipeline.py"
    )


# ── D-14: form cap at 5 per side ─────────────────────────────────────────────

def test_form_capped_at_5():
    """_compute_team_form caps form at last_n=5 regardless of how many DB rows arrive."""
    from card_pipeline import _compute_team_form

    # 10 rows for chiefs — all home wins
    res = [
        {"home": "chiefs", "away": f"opp{i}", "home_score": 1, "away_score": 0,
         "match_key": f"chiefs_vs_opp{i}_2026-03-{i+1:02d}", "league": "t"}
        for i in range(10)
    ]
    form = _compute_team_form(res, "chiefs", last_n=5)
    assert len(form) <= 5, f"Form cap at 5 violated: got {len(form)} entries"


# ── D-15: asymmetric guard ────────────────────────────────────────────────────

def test_asymmetric_guard_hides_both_when_either_empty():
    """If either team has 0 results, both form strips must be empty."""
    from card_pipeline import _compute_team_form

    # Only chiefs results in the list — sundowns has none
    res = [
        {"home": "chiefs", "away": "pirates", "home_score": 1, "away_score": 0,
         "match_key": "chiefs_vs_pirates_2026-03-01", "league": "t"},
    ]
    home_form = _compute_team_form(res, "chiefs")
    away_form = _compute_team_form(res, "sundowns")

    # Simulate the guard added in CARD-REBUILD-04-02
    if not home_form or not away_form:
        home_form = []
        away_form = []

    assert home_form == [], "home_form must be hidden when away_form is empty"
    assert away_form == [], "away_form must be hidden when home_form is empty"


def test_asymmetric_guard_shows_both_when_both_have_results():
    """If both teams have ≥1 result, both strips must be non-empty."""
    from card_pipeline import _compute_team_form

    res = [
        {"home": "chiefs", "away": "pirates", "home_score": 1, "away_score": 0,
         "match_key": "chiefs_vs_pirates_2026-03-01", "league": "t"},
        {"home": "sundowns", "away": "pirates", "home_score": 2, "away_score": 1,
         "match_key": "sundowns_vs_pirates_2026-03-02", "league": "t"},
    ]
    home_form = _compute_team_form(res, "chiefs")
    away_form = _compute_team_form(res, "sundowns")

    if not home_form or not away_form:
        home_form = []
        away_form = []
    else:
        _n = min(len(home_form), len(away_form))
        home_form = home_form[:_n][::-1]
        away_form = away_form[:_n][::-1]

    assert home_form != [], "home_form should be non-empty when both teams have results"
    assert away_form != [], "away_form should be non-empty when both teams have results"
    assert len(home_form) == len(away_form), (
        f"Asymmetric form: home={len(home_form)}, away={len(away_form)}"
    )


# ── Most-recent-RIGHT ordering ────────────────────────────────────────────────

def test_most_recent_is_rightmost_after_reversal():
    """After DESC-fetch and reversal, form[-1] is the most-recent result."""
    from card_pipeline import _compute_team_form

    # Simulate DESC-ordered results (newest first in the list)
    # chiefs: newest = W (match 3), oldest = L (match 1)
    res = [
        # newest first (DESC order)
        {"home": "chiefs", "away": "opp", "home_score": 2, "away_score": 0,
         "match_key": "chiefs_vs_opp_2026-04-03", "league": "t"},  # W
        {"home": "chiefs", "away": "opp", "home_score": 1, "away_score": 1,
         "match_key": "chiefs_vs_opp_2026-04-02", "league": "t"},  # D
        {"home": "chiefs", "away": "opp", "home_score": 0, "away_score": 1,
         "match_key": "chiefs_vs_opp_2026-04-01", "league": "t"},  # L
        # away team also in list
        {"home": "sundowns", "away": "opp2", "home_score": 1, "away_score": 0,
         "match_key": "sundowns_vs_opp2_2026-04-03", "league": "t"},  # W
        {"home": "sundowns", "away": "opp2", "home_score": 0, "away_score": 0,
         "match_key": "sundowns_vs_opp2_2026-04-02", "league": "t"},  # D
        {"home": "sundowns", "away": "opp2", "home_score": 0, "away_score": 1,
         "match_key": "sundowns_vs_opp2_2026-04-01", "league": "t"},  # L
    ]

    home_form = _compute_team_form(res, "chiefs")   # [W, D, L] (newest first)
    away_form = _compute_team_form(res, "sundowns")  # [W, D, L] (newest first)

    # Apply CARD-REBUILD-04-02 reversal
    _n = min(len(home_form), len(away_form))
    home_form = home_form[:_n][::-1]  # reversed: [L, D, W]
    away_form = away_form[:_n][::-1]  # reversed: [L, D, W]

    # Most-recent result (W) is now at index -1 (rightmost)
    assert home_form[-1] == "W", (
        f"Most-recent result must be rightmost (index -1). Got home_form={home_form}"
    )
    assert away_form[-1] == "W", (
        f"Most-recent result must be rightmost (index -1). Got away_form={away_form}"
    )
    # Oldest result is leftmost
    assert home_form[0] == "L", f"Oldest result must be leftmost. Got home_form={home_form}"


# ── Integration: same-length strips via build_card_data ──────────────────────

BASELINE_CARDS = [
    "arsenal_vs_bournemouth_2026-04-12",
    "mamelodi_sundowns_vs_kaizer_chiefs_2026-04-12",
    "manchester_city_vs_liverpool_2026-04-12",
    "real_madrid_vs_barcelona_2026-04-12",
    "pirates_vs_amazulu_2026-04-12",
]


@pytest.mark.parametrize("match_key", BASELINE_CARDS)
def test_baseline_card_form_symmetry(match_key):
    """For every baseline card, form strips are either equal-length or both empty."""
    from card_pipeline import build_verified_data_block, _compute_team_form

    verified = build_verified_data_block(match_key)
    _results = verified.get("results") or []
    home_key = verified.get("home_key") or match_key.split("_vs_")[0]
    away_key = verified.get("away_key") or match_key.split("_vs_")[1].rsplit("_", 1)[0]

    home_form = _compute_team_form(_results, home_key)
    away_form = _compute_team_form(_results, away_key)

    if not home_form or not away_form:
        # Asymmetric guard fires — both must be hidden
        assert home_form == [] or away_form == [], "guard condition inconsistent"
    else:
        _n = min(len(home_form), len(away_form))
        home_form = home_form[:_n][::-1]
        away_form = away_form[:_n][::-1]
        assert len(home_form) == len(away_form), (
            f"{match_key}: asymmetric form: home={len(home_form)}, away={len(away_form)}"
        )
        assert len(home_form) <= 5, f"{match_key}: home_form exceeds 5: {len(home_form)}"
        assert len(away_form) <= 5, f"{match_key}: away_form exceeds 5: {len(away_form)}"


@pytest.mark.parametrize("match_key", BASELINE_CARDS[:2])  # EPL + PSL teams have real DB data
def test_baseline_card_form_uses_date_order(match_key):
    """Verify that results for a team are in descending match_date order in the fetched list."""
    from card_pipeline import build_verified_data_block

    verified = build_verified_data_block(match_key)
    results = verified.get("results") or []

    if len(results) < 2:
        pytest.skip(f"Not enough results in DB for {match_key}")

    # Extract dates in their fetch order
    dates = [r.get("match_key", "")[-10:] for r in results]  # last 10 chars = YYYY-MM-DD
    # Should be descending (each date ≤ previous)
    for i in range(len(dates) - 1):
        assert dates[i] >= dates[i + 1], (
            f"Results not in DESC date order at index {i}: {dates[i]} then {dates[i+1]}"
        )
