"""Contract tests for BUILD-MY-MATCHES-02 — Key Stats wiring.

AC5: _compute_match_detail_stats returns [] or list of {label, value, context} dicts.
AC2: Returns [] gracefully when no DB connection.
AC4: Fair Value falls back to team_ratings Glicko-2 formula.
"""
import sqlite3
import sys
import os
import unittest.mock as mock

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)


# ---------------------------------------------------------------------------
# AC5: Schema — each element must have {label: str, value: str, context: str}
# ---------------------------------------------------------------------------

def test_stats_schema_contract():
    """AC5: Every returned dict has label, value, context as strings."""
    from card_pipeline import _compute_match_detail_stats

    # Build an in-memory SQLite DB with the required tables
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE match_results (
            id INTEGER PRIMARY KEY,
            match_key TEXT, sport TEXT, league TEXT,
            home_team TEXT, away_team TEXT,
            home_score INTEGER, away_score INTEGER,
            result TEXT, match_date TEXT, season TEXT,
            source TEXT, created_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE team_ratings (
            team_name TEXT, sport TEXT,
            mu REAL, phi REAL, sigma REAL,
            matches_played INTEGER, last_updated TEXT
        )"""
    )
    # Insert home record data for 'arsenal' at home
    season = "2025-2026"
    for i, (home, away, hs, as_, res) in enumerate([
        ("arsenal", "chelsea", 2, 0, "home"),
        ("arsenal", "liverpool", 1, 1, "draw"),
        ("arsenal", "man_city", 0, 1, "away"),
        ("arsenal", "tottenham", 3, 0, "home"),
        ("arsenal", "everton", 2, 1, "home"),
    ]):
        conn.execute(
            "INSERT INTO match_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (i+1, f"mk_{i}", "soccer", "epl", home, away, hs, as_, res,
             f"2025-10-{10+i:02d}", season, "espn", "2025-10-11"),
        )
    # Insert away record data for 'afc_bournemouth' on road
    for i, (home, away, hs, as_, res) in enumerate([
        ("chelsea", "afc_bournemouth", 2, 1, "home"),
        ("liverpool", "afc_bournemouth", 1, 2, "away"),
        ("man_city", "afc_bournemouth", 0, 0, "draw"),
    ]):
        conn.execute(
            "INSERT INTO match_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (i+10, f"mkb_{i}", "soccer", "epl", home, away, hs, as_, res,
             f"2025-11-{10+i:02d}", season, "espn", "2025-11-11"),
        )
    # H2H data
    conn.execute(
        "INSERT INTO match_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (20, "h2h_1", "soccer", "epl", "arsenal", "afc_bournemouth", 3, 0, "home",
         "2024-05-04", "2023-2024", "espn", "2024-05-05"),
    )
    conn.execute(
        "INSERT INTO match_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (21, "h2h_2", "soccer", "epl", "afc_bournemouth", "arsenal", 2, 3, "away",
         "2026-01-03", "2025-2026", "espn", "2026-01-04"),
    )
    # team_ratings
    conn.execute(
        "INSERT INTO team_ratings VALUES (?,?,?,?,?,?,?)",
        ("arsenal", "soccer", 1835.9, 77.0, 0.06, 142, "2026-04-01"),
    )
    conn.execute(
        "INSERT INTO team_ratings VALUES (?,?,?,?,?,?,?)",
        ("afc_bournemouth", "soccer", 1558.4, 71.8, 0.06, 90, "2026-04-01"),
    )
    conn.commit()

    with mock.patch("card_pipeline._ro_conn", return_value=conn):
        result = _compute_match_detail_stats(
            "arsenal_vs_afc_bournemouth_2026-04-12",
            "arsenal", "afc_bournemouth", "soccer", "epl", {}
        )

    # AC5: schema check
    assert isinstance(result, list), "Result must be a list"
    assert len(result) > 0, "Expected at least one stat with valid DB data"
    assert len(result) <= 4, "At most 4 stats returned"
    for item in result:
        assert isinstance(item, dict), f"Each stat must be a dict, got {type(item)}"
        assert "label" in item, f"Missing 'label' key in {item}"
        assert "value" in item, f"Missing 'value' key in {item}"
        assert "context" in item, f"Missing 'context' key in {item}"
        assert isinstance(item["label"], str), "'label' must be str"
        assert isinstance(item["value"], str), "'value' must be str"
        assert isinstance(item["context"], str), "'context' must be str"


# ---------------------------------------------------------------------------
# AC2: Graceful empty return when no DB connection
# ---------------------------------------------------------------------------

def test_stats_returns_empty_on_no_db():
    """AC2: Returns [] gracefully when match_results has no data."""
    from card_pipeline import _compute_match_detail_stats

    with mock.patch("card_pipeline._ro_conn", return_value=None):
        result = _compute_match_detail_stats(
            "unknown_vs_unknown_2026-04-12",
            "unknown_team", "another_team", "soccer", "epl", {}
        )
    assert result == [], f"Expected [], got {result}"


def test_stats_returns_empty_on_missing_keys():
    """AC2: Returns [] when home_key or away_key is empty string."""
    from card_pipeline import _compute_match_detail_stats

    result = _compute_match_detail_stats("mk", "", "arsenal", "soccer", "epl", {})
    assert result == [], "Empty home_key should return []"

    result = _compute_match_detail_stats("mk", "arsenal", "", "soccer", "epl", {})
    assert result == [], "Empty away_key should return []"


# ---------------------------------------------------------------------------
# AC4: Fair Value falls back to Glicko-2 when verified.prob absent
# ---------------------------------------------------------------------------

def test_fair_value_glicko2_fallback():
    """AC4: Fair Value derived from team_ratings.mu using Glicko-2 when prob not in verified."""
    from card_pipeline import _compute_match_detail_stats

    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE match_results (
            id INTEGER PRIMARY KEY, match_key TEXT, sport TEXT, league TEXT,
            home_team TEXT, away_team TEXT, home_score INTEGER, away_score INTEGER,
            result TEXT, match_date TEXT, season TEXT, source TEXT, created_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE team_ratings (
            team_name TEXT, sport TEXT, mu REAL, phi REAL, sigma REAL,
            matches_played INTEGER, last_updated TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO team_ratings VALUES (?,?,?,?,?,?,?)",
        ("team_a", "soccer", 1800.0, 70.0, 0.06, 50, "2026-04-01"),
    )
    conn.execute(
        "INSERT INTO team_ratings VALUES (?,?,?,?,?,?,?)",
        ("team_b", "soccer", 1600.0, 70.0, 0.06, 50, "2026-04-01"),
    )
    conn.commit()

    with mock.patch("card_pipeline._ro_conn", return_value=conn):
        result = _compute_match_detail_stats(
            "team_a_vs_team_b_2026-04-12",
            "team_a", "team_b", "soccer", "", {}  # no league, no verified.prob
        )

    fair_value = next((s for s in result if s["label"] == "Fair Value"), None)
    assert fair_value is not None, "Fair Value stat should be present with valid team_ratings"
    assert fair_value["context"] == "home win prob"
    # team_a mu=1800, team_b mu=1600 → P = 1/(1+10^(-200/400)) ≈ 78%
    val = int(fair_value["value"].rstrip("%"))
    assert 70 <= val <= 85, f"Expected ~78% home win prob, got {fair_value['value']}"


def test_fair_value_uses_verified_prob_first():
    """AC4: verified_ctx.prob takes priority over team_ratings lookup."""
    from card_pipeline import _compute_match_detail_stats

    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE match_results (
            id INTEGER PRIMARY KEY, match_key TEXT, sport TEXT, league TEXT,
            home_team TEXT, away_team TEXT, home_score INTEGER, away_score INTEGER,
            result TEXT, match_date TEXT, season TEXT, source TEXT, created_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE team_ratings (
            team_name TEXT, sport TEXT, mu REAL, phi REAL, sigma REAL,
            matches_played INTEGER, last_updated TEXT
        )"""
    )
    conn.commit()

    verified_ctx = {"prob": 0.55}  # 55% as fraction
    with mock.patch("card_pipeline._ro_conn", return_value=conn):
        result = _compute_match_detail_stats(
            "team_a_vs_team_b_2026-04-12",
            "team_a", "team_b", "soccer", "", verified_ctx
        )

    fair_value = next((s for s in result if s["label"] == "Fair Value"), None)
    assert fair_value is not None, "Fair Value should be computed from verified.prob"
    assert fair_value["value"] == "55%", f"Expected 55%, got {fair_value['value']}"
