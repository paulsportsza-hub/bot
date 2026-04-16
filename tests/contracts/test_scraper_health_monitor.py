"""
Contract tests for BUILD-MONITOR-SCRAPER-HEALTH-FRESHNESS-01.

These tests validate the scraper health monitor's behaviour without hitting
the live DB. Uses an in-memory SQLite DB seeded with controlled data.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

# Ensure contracts package is importable from tests
sys.path.insert(0, "/home/paulsportsza")
from contracts.monitors import scraper_health as shm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _fresh_conn():
    """Return an in-memory SQLite connection with required tables seeded.

    Runs the monitor migration so that monitor_results and scraper_health_log
    are always present — individual check functions write to these tables.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # Create all required domain tables
    conn.executescript("""
        CREATE TABLE odds_latest (
            bookmaker TEXT, last_seen TEXT, home_odds REAL, draw_odds REAL, away_odds REAL,
            market_type TEXT DEFAULT '1x2'
        );
        CREATE TABLE scrape_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT, finished_at TEXT,
            total_odds INTEGER DEFAULT 0, total_stored INTEGER DEFAULT 0,
            bookmaker_summary TEXT, errors TEXT, duration_seconds REAL
        );
        CREATE TABLE sharp_odds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_key TEXT, market_type TEXT, selection TEXT, bookmaker TEXT,
            back_price REAL, scraped_at TEXT
        );
        CREATE TABLE edge_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edge_id TEXT, match_key TEXT, sport TEXT, league TEXT,
            edge_tier TEXT, composite_score REAL, bet_type TEXT,
            recommended_odds REAL, bookmaker TEXT, predicted_ev REAL,
            result TEXT, match_score TEXT, actual_return REAL,
            recommended_at TEXT, settled_at TEXT, match_date TEXT,
            confirming_signals INTEGER, movement TEXT
        );
        CREATE TABLE fpl_injuries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER, player_name TEXT, team_name TEXT,
            injury_status TEXT, fetched_at TEXT
        );
    """)
    # Run monitor migration so monitor_results + scraper_health_log are present
    shm._migrate(conn)
    return conn


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ago(minutes: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _seed_bookmakers(conn, age_min: float = 10.0):
    """Seed all active bookmakers with given age in odds_latest."""
    ts = _ago(age_min)
    for bk in shm.ACTIVE_BOOKMAKERS:
        conn.execute(
            "INSERT INTO odds_latest (bookmaker, last_seen) VALUES (?, ?)",
            (bk, ts),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Test 1: Module is importable and exposes run_checks
# ---------------------------------------------------------------------------

def test_module_exposes_run_checks():
    assert callable(shm.run_checks)


def test_module_exposes_active_bookmakers():
    assert len(shm.ACTIVE_BOOKMAKERS) == 8
    assert "hollywoodbets" in shm.ACTIVE_BOOKMAKERS
    assert "supersportbet" in shm.ACTIVE_BOOKMAKERS


# ---------------------------------------------------------------------------
# Test 2: bookmaker_odds_freshness
# ---------------------------------------------------------------------------

def test_bookmaker_freshness_pass_when_all_fresh():
    conn = _fresh_conn()
    _seed_bookmakers(conn, age_min=30.0)
    result = shm._check_bookmaker_odds_freshness(conn, _now_utc())
    assert result["status"] == "PASS"
    assert result["severity"] == "P0"


def test_bookmaker_freshness_fail_when_stale():
    conn = _fresh_conn()
    _seed_bookmakers(conn, age_min=30.0)
    # Override one bookmaker with stale data
    conn.execute(
        "UPDATE odds_latest SET last_seen = ? WHERE bookmaker = 'betway'",
        (_ago(150.0),),  # 150 min > 120 min threshold
    )
    conn.commit()
    result = shm._check_bookmaker_odds_freshness(conn, _now_utc())
    assert result["status"] == "FAIL"
    assert "betway" in result["detail"]


def test_bookmaker_freshness_skip_when_empty():
    conn = _fresh_conn()
    result = shm._check_bookmaker_odds_freshness(conn, _now_utc())
    assert result["status"] == "SKIP_NO_DATA"


def test_bookmaker_freshness_fail_when_bookmaker_missing():
    conn = _fresh_conn()
    # Seed all except supersportbet
    ts = _ago(20.0)
    for bk in shm.ACTIVE_BOOKMAKERS:
        if bk != "supersportbet":
            conn.execute("INSERT INTO odds_latest (bookmaker, last_seen) VALUES (?, ?)", (bk, ts))
    conn.commit()
    result = shm._check_bookmaker_odds_freshness(conn, _now_utc())
    assert result["status"] == "FAIL"
    assert "supersportbet" in result["detail"]


# ---------------------------------------------------------------------------
# Test 3: scrape_run_continuity
# ---------------------------------------------------------------------------

def test_scrape_run_continuity_pass_when_recent():
    conn = _fresh_conn()
    conn.execute(
        "INSERT INTO scrape_runs (started_at, finished_at, total_odds) VALUES (?, ?, ?)",
        (_ago(30.0), _ago(28.0), 500),
    )
    conn.commit()
    result = shm._check_scrape_run_continuity(conn, _now_utc())
    assert result["status"] == "PASS"


def test_scrape_run_continuity_fail_when_stale():
    conn = _fresh_conn()
    conn.execute(
        "INSERT INTO scrape_runs (started_at, finished_at, total_odds) VALUES (?, ?, ?)",
        (_ago(120.0), _ago(118.0), 500),  # 120min > 90min threshold
    )
    conn.commit()
    result = shm._check_scrape_run_continuity(conn, _now_utc())
    assert result["status"] == "FAIL"
    assert "STALE" in result["detail"] or "120" in result["detail"] or "threshold" in result["detail"]


def test_scrape_run_continuity_skip_when_empty():
    conn = _fresh_conn()
    result = shm._check_scrape_run_continuity(conn, _now_utc())
    assert result["status"] == "SKIP_NO_DATA"


# ---------------------------------------------------------------------------
# Test 4: scrape_run_errors
# ---------------------------------------------------------------------------

def test_scrape_run_errors_pass_when_clean():
    conn = _fresh_conn()
    for i in range(5):
        conn.execute(
            "INSERT INTO scrape_runs (started_at, errors) VALUES (?, ?)",
            (_ago(i * 10.0), "[]"),
        )
    conn.commit()
    result = shm._check_scrape_run_errors(conn, _now_utc())
    assert result["status"] == "PASS"


def test_scrape_run_errors_fail_when_errors_present():
    conn = _fresh_conn()
    conn.execute(
        "INSERT INTO scrape_runs (started_at, errors) VALUES (?, ?)",
        (_ago(5.0), '["Connection timeout on hollywoodbets"]'),
    )
    conn.commit()
    result = shm._check_scrape_run_errors(conn, _now_utc())
    assert result["status"] == "FAIL"
    assert "1 error" in result["detail"]


def test_scrape_run_errors_severity_is_p1():
    conn = _fresh_conn()
    result = shm._check_scrape_run_errors(conn, _now_utc())
    assert result["severity"] == "P1"


# ---------------------------------------------------------------------------
# Test 5: sharp_odds_freshness
# ---------------------------------------------------------------------------

def test_sharp_odds_freshness_pass_when_recent():
    conn = _fresh_conn()
    conn.execute(
        "INSERT INTO sharp_odds (match_key, market_type, selection, bookmaker, back_price, scraped_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("test_match_2026-04-14", "h2h", "home", "pinnacle", 2.1, _ago(60.0)),
    )
    conn.commit()
    result = shm._check_sharp_odds_freshness(conn, _now_utc())
    assert result["status"] == "PASS"
    assert result["severity"] == "P1"


def test_sharp_odds_freshness_fail_when_stale():
    conn = _fresh_conn()
    conn.execute(
        "INSERT INTO sharp_odds (match_key, market_type, selection, bookmaker, back_price, scraped_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("test_match_2026-04-14", "h2h", "home", "pinnacle", 2.1, _ago(360.0)),  # >5h
    )
    conn.commit()
    result = shm._check_sharp_odds_freshness(conn, _now_utc())
    assert result["status"] == "FAIL"


def test_sharp_odds_freshness_skip_when_empty():
    conn = _fresh_conn()
    result = shm._check_sharp_odds_freshness(conn, _now_utc())
    assert result["status"] == "SKIP_NO_DATA"


# ---------------------------------------------------------------------------
# Test 6: edge_pipeline_freshness
# ---------------------------------------------------------------------------

def test_edge_pipeline_freshness_pass_when_recent():
    conn = _fresh_conn()
    conn.execute(
        "INSERT INTO edge_results "
        "(edge_id, match_key, sport, league, edge_tier, composite_score, bet_type, "
        " recommended_odds, bookmaker, predicted_ev, recommended_at, match_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("e1", "chiefs_vs_pirates_2026-04-14", "soccer", "psl",
         "gold", 72.0, "Home Win", 1.85, "betway", 5.2, _ago(60.0), "2026-04-14"),
    )
    conn.commit()
    result = shm._check_edge_pipeline_freshness(conn, _now_utc())
    assert result["status"] == "PASS"
    assert result["severity"] == "P0"


def test_edge_pipeline_freshness_fail_when_no_recent_edges():
    conn = _fresh_conn()
    # Insert edge older than 25h
    conn.execute(
        "INSERT INTO edge_results "
        "(edge_id, match_key, sport, league, edge_tier, composite_score, bet_type, "
        " recommended_odds, bookmaker, predicted_ev, recommended_at, match_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("e1", "old_match_2026-04-13", "soccer", "psl",
         "gold", 72.0, "Home Win", 1.85, "betway", 5.2, _ago(1600.0), "2026-04-13"),
    )
    conn.commit()
    result = shm._check_edge_pipeline_freshness(conn, _now_utc())
    assert result["status"] == "FAIL"


def test_edge_pipeline_freshness_fail_when_table_empty():
    conn = _fresh_conn()
    result = shm._check_edge_pipeline_freshness(conn, _now_utc())
    assert result["status"] == "FAIL"


# ---------------------------------------------------------------------------
# Test 7: fpl_injuries_freshness
# ---------------------------------------------------------------------------

def test_fpl_injuries_freshness_pass_when_recent():
    conn = _fresh_conn()
    conn.execute(
        "INSERT INTO fpl_injuries (player_id, player_name, team_name, injury_status, fetched_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (1, "Test Player", "Arsenal", "Fit", _ago(20.0)),
    )
    conn.commit()
    result = shm._check_fpl_injuries_freshness(conn, _now_utc())
    assert result["status"] == "PASS"
    assert result["severity"] == "P1"


def test_fpl_injuries_freshness_fail_when_stale():
    conn = _fresh_conn()
    conn.execute(
        "INSERT INTO fpl_injuries (player_id, player_name, team_name, injury_status, fetched_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (1, "Test Player", "Arsenal", "Fit", _ago(120.0)),  # >90min
    )
    conn.commit()
    result = shm._check_fpl_injuries_freshness(conn, _now_utc())
    assert result["status"] == "FAIL"


def test_fpl_injuries_freshness_skip_when_empty():
    conn = _fresh_conn()
    result = shm._check_fpl_injuries_freshness(conn, _now_utc())
    assert result["status"] == "SKIP_NO_DATA"


# ---------------------------------------------------------------------------
# Test 8: overall_status aggregation
# ---------------------------------------------------------------------------

def test_overall_status_pass_all_pass():
    results = [
        {"status": "PASS"}, {"status": "PASS"}, {"status": "PASS"},
    ]
    assert shm._overall_status(results) == "PASS"


def test_overall_status_fail_on_any_fail():
    results = [
        {"status": "PASS"}, {"status": "FAIL"}, {"status": "PASS"},
    ]
    assert shm._overall_status(results) == "FAIL"


def test_overall_status_degraded_when_majority_skip():
    results = [
        {"status": "SKIP_NO_DATA"}, {"status": "SKIP_NO_DATA"},
        {"status": "SKIP_NO_DATA"}, {"status": "PASS"},
    ]
    assert shm._overall_status(results) == "DEGRADED"


def test_overall_status_pass_when_minority_skip():
    results = [
        {"status": "PASS"}, {"status": "PASS"}, {"status": "PASS"},
        {"status": "SKIP_NO_DATA"},
    ]
    assert shm._overall_status(results) == "PASS"


# ---------------------------------------------------------------------------
# Test 9: DB migration creates required tables
# ---------------------------------------------------------------------------

def test_migration_creates_scraper_health_log():
    conn = sqlite3.connect(":memory:")
    shm._migrate(conn)
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='scraper_health_log'"
    ).fetchone()
    assert row is not None


def test_migration_creates_monitor_results():
    conn = sqlite3.connect(":memory:")
    shm._migrate(conn)
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='monitor_results'"
    ).fetchone()
    assert row is not None


def test_migration_creates_daily_summary_view():
    conn = sqlite3.connect(":memory:")
    shm._migrate(conn)
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='view' AND name='monitor_daily_summary'"
    ).fetchone()
    assert row is not None


def test_migration_is_idempotent():
    """Running migration twice must not raise."""
    conn = sqlite3.connect(":memory:")
    shm._migrate(conn)
    shm._migrate(conn)  # Should not raise


# ---------------------------------------------------------------------------
# Test 10: Alert rate limiting
# ---------------------------------------------------------------------------

def test_was_alerted_recently_false_when_no_history():
    conn = sqlite3.connect(":memory:")
    shm._migrate(conn)
    assert shm._was_alerted_recently(conn, "bookmaker_odds_freshness") is False


def test_was_alerted_recently_true_after_recent_fail():
    conn = sqlite3.connect(":memory:")
    shm._migrate(conn)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    conn.execute(
        "INSERT INTO monitor_results (monitor, check_name, severity, status, detail, run_timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("scraper_health", "bookmaker_odds_freshness", "P0", "FAIL", "test", ts),
    )
    conn.commit()
    assert shm._was_alerted_recently(conn, "bookmaker_odds_freshness") is True


def test_was_alerted_recently_false_after_old_fail():
    conn = sqlite3.connect(":memory:")
    shm._migrate(conn)
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    conn.execute(
        "INSERT INTO monitor_results (monitor, check_name, severity, status, detail, run_timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("scraper_health", "bookmaker_odds_freshness", "P0", "FAIL", "old test", old_ts),
    )
    conn.commit()
    assert shm._was_alerted_recently(conn, "bookmaker_odds_freshness") is False


# ---------------------------------------------------------------------------
# Test 11: run_checks returns correct structure
# ---------------------------------------------------------------------------

def test_run_checks_returns_required_keys():
    """run_checks result must contain the 5 required top-level keys."""
    with patch("contracts.monitors.scraper_health.connect_odds_db") as mock_conn_fn:
        conn = _fresh_conn()
        _seed_bookmakers(conn, age_min=30.0)
        # Seed other tables with minimal data
        conn.execute(
            "INSERT INTO scrape_runs (started_at, finished_at, total_odds) VALUES (?, ?, ?)",
            (_ago(20.0), _ago(18.0), 500),
        )
        conn.execute(
            "INSERT INTO sharp_odds (match_key, market_type, selection, bookmaker, back_price, scraped_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("m_2026-04-14", "h2h", "home", "pinnacle", 2.1, _ago(60.0)),
        )
        conn.execute(
            "INSERT INTO edge_results "
            "(edge_id, match_key, sport, league, edge_tier, composite_score, bet_type, "
            " recommended_odds, bookmaker, predicted_ev, recommended_at, match_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("e1", "chiefs_2026-04-14", "soccer", "psl",
             "gold", 72.0, "Home Win", 1.85, "betway", 5.2, _ago(60.0), "2026-04-14"),
        )
        conn.execute(
            "INSERT INTO fpl_injuries (player_id, player_name, team_name, injury_status, fetched_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (1, "Player", "Arsenal", "Fit", _ago(20.0)),
        )
        conn.commit()
        shm._migrate(conn)
        mock_conn_fn.return_value = conn

        result = shm.run_checks(dry_run=True)

    assert "monitor" in result
    assert result["monitor"] == "scraper_health"
    assert "run_timestamp" in result
    assert "overall_status" in result
    assert "checks" in result
    assert "summary" in result
    assert len(result["checks"]) == 6


def test_run_checks_summary_counts_match():
    """summary pass+fail+skip must equal 6 (total checks)."""
    with patch("contracts.monitors.scraper_health.connect_odds_db") as mock_conn_fn:
        conn = _fresh_conn()
        shm._migrate(conn)
        mock_conn_fn.return_value = conn

        result = shm.run_checks(dry_run=True)

    s = result["summary"]
    assert s["pass"] + s["fail"] + s["skip"] == 6
