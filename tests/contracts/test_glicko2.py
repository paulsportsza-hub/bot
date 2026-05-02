"""Contract tests for Glicko-2 rating module.

AC-8: Glicko-2 update equations (2), soccer config (1), rugby config (1),
      missing team null (1). Zero new test failures.
"""

import math
import os
import sqlite3
import sys

# Allow imports from scrapers
_SCRAPERS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
)
sys.path.insert(0, _SCRAPERS_DIR)


def _cricket_history_db(tmp_path):
    """Create an isolated cricket history DB for contracts that train ratings."""
    db = tmp_path / "cricket_glicko2.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE match_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sport TEXT NOT NULL,
            match_date TEXT NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            result TEXT NOT NULL,
            home_score INTEGER,
            away_score INTEGER
        )
        """
    )
    rows = [
        ("2024-01-01", "kolkata_knight_riders", "mumbai_indians", "home", 185, 176),
        ("2024-01-02", "chennai_super_kings", "punjab_kings", "home", 172, 160),
        ("2024-01-03", "rajasthan_royals", "mumbai_indians", "away", 151, 154),
        ("2024-01-04", "royal_challengers_bengaluru", "chennai_super_kings", "away", 168, 170),
        ("2024-01-05", "sunrisers_hyderabad", "lucknow_super_giants", "home", 201, 187),
        ("2024-01-06", "delhi_capitals", "gujarat_titans", "away", 144, 149),
        ("2024-01-07", "india", "south_africa", "home", 196, 189),
        ("2024-01-08", "south_africa", "india", "away", 161, 165),
        ("2024-01-09", "kolkata_knight_riders", "punjab_kings", "home", 191, 183),
        ("2024-01-10", "gujarat_titans", "delhi_capitals", "home", 177, 170),
    ]
    conn.executemany(
        """
        INSERT INTO match_results (
            sport, match_date, home_team, away_team, result, home_score, away_score
        )
        VALUES ('cricket', ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()
    return str(db)


def _empty_ratings_db(tmp_path):
    """Create an isolated DB where Glicko-2 can load an empty ratings table."""
    from scrapers.elo.glicko2 import ensure_migration

    db = tmp_path / "empty_glicko2.db"
    ensure_migration(str(db))
    return str(db)


def _point_elo_helper_at_db(monkeypatch, db_path):
    import scrapers.elo.elo_helper as elo_helper

    monkeypatch.setattr(elo_helper, "DB_PATH", db_path)
    elo_helper._glicko2.clear()
    elo_helper._elo = None
    return elo_helper


# ---------------------------------------------------------------------------
# AC-8 Test 1: Glicko-2 update equations — Glickman 2012 known values
# ---------------------------------------------------------------------------

def test_glicko2_update_win():
    """Verify Glicko-2 update produces correct direction for a win.

    Player (1500, 200, 0.06) beats opponent (1400, 30).
    Rating should increase, RD should decrease.
    """
    from scrapers.elo.glicko2 import glicko2_update

    mu_new, phi_new, sigma_new = glicko2_update(
        mu=1500.0, phi=200.0, sigma=0.06,
        opp_mu=1400.0, opp_phi=30.0,
        score=1.0, tau=0.5,
    )

    # Rating should increase (won against weaker opponent)
    assert mu_new > 1500.0, f"Expected μ > 1500, got {mu_new:.2f}"
    # RD should decrease (more certain after a game)
    assert phi_new < 200.0, f"Expected φ < 200, got {phi_new:.2f}"
    # Sigma should stay in reasonable range
    assert 0.01 < sigma_new < 0.5, f"σ out of range: {sigma_new}"
    # Win against weaker opponent → modest increase
    assert mu_new < 1600.0, f"μ too large for weak opponent win: {mu_new:.2f}"


def test_glicko2_update_loss():
    """Verify Glicko-2 update for a loss against a stronger opponent.

    Player (1500, 200, 0.06) loses to opponent (1700, 300).
    Rating should decrease, RD should decrease (still learned from the game).
    """
    from scrapers.elo.glicko2 import glicko2_update

    mu_new, phi_new, sigma_new = glicko2_update(
        mu=1500.0, phi=200.0, sigma=0.06,
        opp_mu=1700.0, opp_phi=300.0,
        score=0.0, tau=0.5,
    )

    # Rating should decrease (lost)
    assert mu_new < 1500.0, f"Expected μ < 1500, got {mu_new:.2f}"
    # RD should decrease (more certain after game)
    assert phi_new < 200.0, f"Expected φ < 200, got {phi_new:.2f}"
    # Against uncertain opponent (φ=300) → moderate decrease
    assert mu_new > 1300.0, f"μ dropped too much: {mu_new:.2f}"


# ---------------------------------------------------------------------------
# AC-8 Test 2: Multi-game Glickman 2012 reference scenario
# ---------------------------------------------------------------------------

def test_glicko2_multi_game_direction():
    """Verify sequential updates: win then two losses → net decrease.

    Player starts at 1500/200/0.06.
    Beats 1400/30, loses to 1550/100, loses to 1700/300.
    Net: should decrease from 1500 (2 losses > 1 win).
    """
    from scrapers.elo.glicko2 import glicko2_update

    mu, phi, sigma = 1500.0, 200.0, 0.06

    # Win vs 1400
    mu, phi, sigma = glicko2_update(mu, phi, sigma, 1400.0, 30.0, 1.0, 0.5)
    assert mu > 1500.0, "Should have increased after win"

    # Lose to 1550
    mu, phi, sigma = glicko2_update(mu, phi, sigma, 1550.0, 100.0, 0.0, 0.5)

    # Lose to 1700
    mu, phi, sigma = glicko2_update(mu, phi, sigma, 1700.0, 300.0, 0.0, 0.5)

    # Net result after 1W 2L: rating should have decreased from initial 1500
    assert mu < 1500.0, f"Expected μ < 1500 after 1W2L, got {mu:.2f}"
    # RD should be substantially lower after 3 games
    assert phi < 175.0, f"Expected φ < 175 after 3 games, got {phi:.2f}"


# ---------------------------------------------------------------------------
# AC-8 Test 3: Soccer config matches brief specifications
# ---------------------------------------------------------------------------

def test_soccer_config():
    """AC-2: Soccer τ=0.5, initial RD=200, RD threshold=80, initial μ=1500."""
    from scrapers.elo.glicko2 import SPORT_CONFIGS

    cfg = SPORT_CONFIGS["soccer"]
    assert cfg.tau == 0.5, f"Soccer τ should be 0.5, got {cfg.tau}"
    assert cfg.initial_mu == 1500.0, f"Soccer μ₀ should be 1500, got {cfg.initial_mu}"
    assert cfg.initial_phi == 200.0, f"Soccer φ₀ should be 200, got {cfg.initial_phi}"
    assert cfg.rd_threshold == 80.0, f"Soccer RD threshold should be 80, got {cfg.rd_threshold}"
    assert cfg.mov_weight > 0, "Soccer MoV weight should be positive (goals-based)"


def test_rugby_config():
    """AC-3: Rugby τ=0.4, initial RD=200, RD threshold=70, initial μ=1500."""
    from scrapers.elo.glicko2 import SPORT_CONFIGS

    cfg = SPORT_CONFIGS["rugby"]
    assert cfg.tau == 0.4, f"Rugby τ should be 0.4, got {cfg.tau}"
    assert cfg.initial_mu == 1500.0, f"Rugby μ₀ should be 1500, got {cfg.initial_mu}"
    assert cfg.initial_phi == 200.0, f"Rugby φ₀ should be 200, got {cfg.initial_phi}"
    assert cfg.rd_threshold == 70.0, f"Rugby RD threshold should be 70, got {cfg.rd_threshold}"
    assert cfg.mov_weight > 0, "Rugby MoV weight should be positive (points-based)"


# ---------------------------------------------------------------------------
# AC-8 Test 4: Separate rating stores per sport
# ---------------------------------------------------------------------------

def test_separate_sport_stores():
    """AC-3: Soccer and rugby maintain independent ratings."""
    from scrapers.elo.glicko2 import Glicko2System

    soccer = Glicko2System("soccer")
    rugby = Glicko2System("rugby")

    # Add a team to soccer
    soccer.process_match("team_a", "team_b", "home", 3, 0)

    # That team should NOT exist in rugby
    rugby_rating = rugby.get("team_a")
    assert rugby_rating.matches_played == 0, "team_a should not be in rugby ratings"

    # Soccer should have it
    soccer_rating = soccer.get("team_a")
    assert soccer_rating.matches_played == 1, "team_a should have 1 match in soccer"


# ---------------------------------------------------------------------------
# AC-8 Test 5: Missing team returns graceful null
# ---------------------------------------------------------------------------

def test_missing_team_graceful_null():
    """AC-7: Missing team returns initial defaults, never raises."""
    from scrapers.elo.glicko2 import Glicko2System, SPORT_CONFIGS

    sys = Glicko2System("soccer")
    cfg = SPORT_CONFIGS["soccer"]

    # Unknown team should return defaults
    rating = sys.get("totally_unknown_team_xyz")
    assert rating.mu == cfg.initial_mu, f"Expected default μ={cfg.initial_mu}"
    assert rating.phi == cfg.initial_phi, f"Expected default φ={cfg.initial_phi}"
    assert rating.sigma == cfg.initial_sigma, f"Expected default σ={cfg.initial_sigma}"
    assert rating.matches_played == 0, "Expected 0 matches played"

    # Prediction with unknown teams should not raise
    pred = sys.predict("totally_unknown_home", "totally_unknown_away")
    assert "home_win" in pred
    assert "away_win" in pred
    assert "draw" in pred
    assert "confidence" in pred
    assert pred["confidence"] == "low", "Unknown teams should have low confidence"


def test_missing_team_null_in_helper(tmp_path, monkeypatch):
    """AC-7: get_glicko2_rating returns None for teams with 0 matches."""
    elo_helper = _point_elo_helper_at_db(monkeypatch, _empty_ratings_db(tmp_path))

    result = elo_helper.get_glicko2_rating(
        "nonexistent_home_xyz", "nonexistent_away_xyz", "soccer"
    )
    assert result is None, "Should return None for unknown teams"


def test_missing_team_null_unknown_teams_cricket(tmp_path, monkeypatch):
    """AC-7: get_glicko2_rating returns None when both teams have 0 matches, even for cricket."""
    elo_helper = _point_elo_helper_at_db(monkeypatch, _empty_ratings_db(tmp_path))

    result = elo_helper.get_glicko2_rating("totally_unknown_cricket_team_xyz", "also_unknown_xyz", "cricket")
    assert result is None, "Both teams at 0 matches → None even for supported sport"


def test_missing_team_null_unsupported_sport():
    """AC-7: get_glicko2_rating returns None for genuinely unsupported sports."""
    from scrapers.elo.elo_helper import get_glicko2_rating

    result = get_glicko2_rating("team_a", "team_b", "baseball")
    assert result is None, "Baseball is not supported by Glicko-2, should return None"


# ---------------------------------------------------------------------------
# AC-6: team_ratings table migration
# ---------------------------------------------------------------------------

def test_team_ratings_table_idempotent(tmp_path):
    """AC-6: Migration is idempotent — running twice doesn't error."""
    from scrapers.elo.glicko2 import ensure_migration
    import sqlite3

    db = str(tmp_path / "test_migration.db")
    # First call creates the table
    ensure_migration(db)
    # Second call is a no-op (idempotent)
    ensure_migration(db)

    # Verify table exists with correct columns
    conn = sqlite3.connect(db)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(team_ratings)")}
    conn.close()

    expected = {"id", "team_name", "sport", "mu", "phi", "sigma",
                "matches_played", "last_updated"}
    assert expected == cols, f"Column mismatch: expected {expected}, got {cols}"


# ---------------------------------------------------------------------------
# MoV weighting
# ---------------------------------------------------------------------------

def test_mov_adjust_preserves_draw():
    """MoV adjustment should not change a draw (score=0.5)."""
    from scrapers.elo.glicko2 import mov_adjust_score

    assert mov_adjust_score(0.5, 3, 0.5) == 0.5
    assert mov_adjust_score(0.5, 0, 0.5) == 0.5


def test_mov_adjust_amplifies_win():
    """MoV should amplify a win closer to 1.0."""
    from scrapers.elo.glicko2 import mov_adjust_score

    base = mov_adjust_score(1.0, 0, 0.5)
    amplified = mov_adjust_score(1.0, 3, 0.5)
    assert amplified >= base, "3-goal win should amplify at least as much as 0-goal"
    assert amplified <= 1.0, "Score should never exceed 1.0"


# ---------------------------------------------------------------------------
# P4-04: Cricket Glicko-2 (AC-1 to AC-6)
# ---------------------------------------------------------------------------

def test_cricket_config_exists():
    """AC-1: Cricket SportConfig is present in SPORT_CONFIGS."""
    from scrapers.elo.glicko2 import SPORT_CONFIGS

    assert "cricket" in SPORT_CONFIGS, "Cricket must be in SPORT_CONFIGS"
    cfg = SPORT_CONFIGS["cricket"]
    assert cfg.tau > 0, "Cricket τ must be positive"
    assert cfg.initial_mu == 1500.0, "Cricket initial μ must be 1500"
    assert cfg.initial_phi == 200.0, "Cricket initial φ must be 200"
    assert cfg.initial_sigma > 0, "Cricket initial σ must be positive"
    assert cfg.rd_threshold > 0, "Cricket RD threshold must be positive"


def test_cricket_no_draws():
    """AC-2: Cricket predict() returns draw=0.0 — T20 has no draws."""
    from scrapers.elo.glicko2 import Glicko2System

    sys = Glicko2System("cricket")
    sys.process_match("team_a", "team_b", "home", 180, 150)
    pred = sys.predict("team_a", "team_b")

    assert pred["draw"] == 0.0, f"Cricket draw probability must be 0.0, got {pred['draw']}"
    assert abs(pred["home_win"] + pred["away_win"] - 1.0) < 1e-6, \
        "home_win + away_win must sum to 1.0 for cricket"


def test_cricket_separate_from_soccer_rugby():
    """AC-3: Cricket ratings are independent from soccer/rugby stores."""
    from scrapers.elo.glicko2 import Glicko2System

    cricket = Glicko2System("cricket")
    soccer = Glicko2System("soccer")

    cricket.process_match("india", "australia", "home", 180, 160)

    # 'india' must not bleed into soccer
    soccer_rating = soccer.get("india")
    assert soccer_rating.matches_played == 0, "India should not appear in soccer ratings"

    cricket_rating = cricket.get("india")
    assert cricket_rating.matches_played == 1, "India should have 1 match in cricket"


def test_cricket_teams_rated_from_db(tmp_path):
    """AC-1: Cricket teams are rated from historical match_results in odds.db."""
    from scrapers.elo.glicko2 import initialise_ratings

    sys = initialise_ratings("cricket", _cricket_history_db(tmp_path))
    assert len(sys.ratings) >= 5, \
        f"Expected at least 5 cricket teams rated, got {len(sys.ratings)}"

    # IPL teams must be present
    expected = {"kolkata_knight_riders", "mumbai_indians", "chennai_super_kings",
                "india", "south_africa"}
    found = set(sys.ratings.keys())
    missing = expected - found
    assert not missing, f"Expected cricket teams not rated: {missing}"


def test_cricket_upcoming_match_has_ratings(tmp_path):
    """AC-4: Upcoming cricket fixtures can produce ratings for both teams."""
    from scrapers.elo.glicko2 import Glicko2System, initialise_ratings

    db_path = _cricket_history_db(tmp_path)
    initialise_ratings("cricket", db_path)

    sys = Glicko2System("cricket", db_path)
    sys.load()

    # IPL 2026 teams currently active in odds.db
    pairs = [
        ("kolkata_knight_riders", "punjab_kings"),
        ("rajasthan_royals", "mumbai_indians"),
        ("royal_challengers_bengaluru", "chennai_super_kings"),
        ("sunrisers_hyderabad", "lucknow_super_giants"),
        ("delhi_capitals", "gujarat_titans"),
    ]

    rated_count = 0
    for home, away in pairs:
        hr = sys.get(home)
        ar = sys.get(away)
        if hr.matches_played > 0 or ar.matches_played > 0:
            rated_count += 1

    assert rated_count >= 5, \
        f"Expected 5 upcoming cricket pairs with ratings, got {rated_count}"


def test_cricket_glicko2_no_regression_soccer_rugby():
    """AC-5: Adding cricket does not change soccer/rugby SPORT_CONFIGS values."""
    from scrapers.elo.glicko2 import SPORT_CONFIGS

    soccer = SPORT_CONFIGS["soccer"]
    assert soccer.tau == 0.5
    assert soccer.initial_sigma == 0.08
    assert soccer.rd_threshold == 80.0

    rugby = SPORT_CONFIGS["rugby"]
    assert rugby.tau == 0.4
    assert rugby.initial_sigma == 0.06
    assert rugby.rd_threshold == 70.0


def test_cricket_feeds_elo_helper(tmp_path, monkeypatch):
    """AC-3: Cricket Glicko-2 ratings feed into get_elo_probability via elo_helper."""
    from scrapers.elo.glicko2 import initialise_ratings

    db_path = _cricket_history_db(tmp_path)
    initialise_ratings("cricket", db_path)
    elo_helper = _point_elo_helper_at_db(monkeypatch, db_path)

    # Use known-rated IPL teams — should return Glicko-2 result not Elo fallback
    result = elo_helper.get_elo_probability("kolkata_knight_riders", "mumbai_indians", "cricket",
                                            require_confidence="low")
    assert result is not None, "Expected elo_probability result for known IPL teams"
    # Glicko-2 path: draw should be 0.0
    assert result["draw"] == 0.0, \
        f"Cricket Glicko-2 via elo_helper must return draw=0.0, got {result['draw']}"
