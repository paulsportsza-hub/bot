"""BUG-STATS-SEASON-FILTER-01 — Hard-Fail Season Filter Mismatch

Two contract tests:
  1. Mismatched league → _compute_match_detail_stats returns [] (no fake stats).
  2. Known-good league match → correct current-season W-D-L tiles returned.
"""
import sqlite3
from unittest.mock import patch


def _make_db(rows: list[tuple]) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE match_results (
            home_team TEXT,
            away_team TEXT,
            result    TEXT,
            match_date TEXT,
            season    TEXT,
            league    TEXT,
            home_score INTEGER,
            away_score INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE team_ratings (
            team_name TEXT,
            sport     TEXT,
            mu        REAL
        )
    """)
    if rows:
        conn.executemany(
            "INSERT INTO match_results VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
    conn.commit()
    return conn


def _call(league: str, rows: list[tuple],
          home_key: str = "polokwane_city",
          away_key: str = "kaizer_chiefs") -> list:
    from card_pipeline import _compute_match_detail_stats
    conn = _make_db(rows)
    with patch("card_pipeline._ro_conn", return_value=conn):
        return _compute_match_detail_stats(
            match_key=f"{home_key}_vs_{away_key}_2026-04-17",
            home_key=home_key,
            away_key=away_key,
            sport="soccer",
            league=league,
            verified_ctx={},
        )


class TestSeasonFilterHardFail:
    def test_league_mismatch_returns_empty(self):
        """POL vs KC: league arg doesn't match match_results.league → []."""
        rows = [
            ("polokwane_city", "other_fc", "home", "2026-01-10", "2025-2026",
             "dstv_premiership", 2, 0),
            ("polokwane_city", "other_fc", "home", "2026-02-10", "2025-2026",
             "dstv_premiership", 1, 0),
        ]
        # league arg "premiership_(psl)" ≠ "dstv_premiership" in DB
        result = _call(league="premiership_(psl)", rows=rows)
        assert result == [], (
            f"Expected [] on season_filter_mismatch, got {result}"
        )

    def test_empty_match_results_returns_empty(self):
        """No rows in match_results at all → []."""
        result = _call(league="psl", rows=[])
        assert result == []

    def test_known_good_fixture_returns_records(self):
        """Arsenal vs Newcastle with matching league → correct W-D-L tiles."""
        home = "arsenal"
        away = "newcastle_united"
        lg = "english_premier_league"
        rows = [
            (home, "chelsea",  "home", "2025-12-01", "2025-2026", lg, 2, 0),
            (home, "everton",  "home", "2026-01-15", "2025-2026", lg, 3, 1),
            (home, "brighton", "draw", "2026-02-10", "2025-2026", lg, 1, 1),
            ("liverpool", away, "away", "2025-11-20", "2025-2026", lg, 0, 2),
        ]
        result = _call(league=lg, rows=rows, home_key=home, away_key=away)

        labels = {s["label"]: s["value"] for s in result}
        assert "Home Record" in labels, f"Home Record tile missing. Got: {labels}"
        assert "Away Record" in labels, f"Away Record tile missing. Got: {labels}"
        # Arsenal: 2 wins, 1 draw, 0 losses at home
        assert labels["Home Record"] == "2-1-0", labels["Home Record"]
        # Newcastle: 1 away win, 0 draws, 0 losses
        assert labels["Away Record"] == "1-0-0", labels["Away Record"]
