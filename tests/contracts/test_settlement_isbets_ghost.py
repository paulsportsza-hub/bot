"""BUILD-CONTRACT-TESTS-01 — Test 7: Settlement ISBets Ghost Fixture

W81-SETTLE invariants:
  (a) log_edge_recommendation() rejects ISBets-only match keys
  (b) settle_edges() auto-voids ISBets-only edges after _GHOST_FIXTURE_DAYS=3
  (c) _fuzzy_match_result() finds matches at ±5 days
  (d) _TEAM_ALIASES resolves key aliases (e.g. wolves → wolverhampton_wanderers)

Uses isolated in-memory SQLite DB — no live odds.db dependency.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pytest

# Make scrapers importable
_BOT_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _BOT_DIR)
import config
config.ensure_scrapers_importable()

from scrapers.edge.settlement import (
    _GHOST_FIXTURE_DAYS,
    _TEAM_ALIASES,
    _fuzzy_match_result,
    _is_isbets_only_fixture,
    log_edge_recommendation,
)


# ── Shared fixture ─────────────────────────────────────────────────────────────

def _fresh_db() -> sqlite3.Connection:
    """Return an in-memory SQLite connection with the required tables."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS odds_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bookmaker TEXT NOT NULL,
            match_id TEXT NOT NULL,
            home_team TEXT,
            away_team TEXT,
            league TEXT,
            sport TEXT,
            market_type TEXT,
            home_odds REAL,
            draw_odds REAL,
            away_odds REAL,
            over_odds REAL,
            under_odds REAL,
            scraped_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            run_id INTEGER,
            source_url TEXT,
            handicap_line REAL
        );
        CREATE TABLE IF NOT EXISTS match_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_key TEXT UNIQUE,
            sport TEXT NOT NULL,
            league TEXT NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            home_score INTEGER,
            away_score INTEGER,
            result TEXT,
            match_date DATE NOT NULL,
            season TEXT,
            source TEXT DEFAULT 'espn',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    return conn


# ── (a) log_edge_recommendation rejects ISBets-only ───────────────────────────

def test_log_edge_recommendation_rejects_isbets_only(tmp_path):
    """log_edge_recommendation() must return False for ISBets-only match keys."""
    conn = _fresh_db()

    match_key = "arsenal_vs_chelsea_2026-04-30"
    # Insert ISBets-platform bookmakers only
    for bk in ("playabets", "supabets"):
        conn.execute(
            "INSERT INTO odds_snapshots (bookmaker, match_id, league, sport, market_type, scraped_at) "
            "VALUES (?,?,?,?,?,?)",
            (bk, match_key, "epl", "soccer", "1x2", datetime.now(timezone.utc).isoformat()),
        )
    conn.commit()

    edge = {
        "match_key": match_key,
        "tier": "gold",
        "edge_pct": 8.0,
        "best_odds": 1.85,
        "bookmaker": "playabets",
        "composite_score": 72.0,
        "market_type": "1x2",
        "outcome": "home",
        "sport": "soccer",
        "league": "epl",
    }
    result = log_edge_recommendation(edge, conn=conn)
    assert result is False, (
        "log_edge_recommendation() must return False for ISBets-only fixtures "
        "(ghost fixture risk — W81-SETTLE)"
    )
    conn.close()


def test_log_edge_recommendation_allows_multi_bookmaker(tmp_path):
    """log_edge_recommendation() proceeds (not rejected) when non-ISBets bk is present."""
    conn = _fresh_db()
    match_key = "sundowns_vs_pirates_2026-05-01"
    # Include a non-ISBets bookmaker alongside ISBets
    for bk in ("playabets", "hollywoodbets"):
        conn.execute(
            "INSERT INTO odds_snapshots (bookmaker, match_id, league, sport, market_type, scraped_at) "
            "VALUES (?,?,?,?,?,?)",
            (bk, match_key, "psl", "soccer", "1x2", datetime.now(timezone.utc).isoformat()),
        )
    conn.commit()

    edge = {
        "match_key": match_key,
        "tier": "gold",
        "edge_pct": 6.0,
        "best_odds": 1.90,
        "bookmaker": "hollywoodbets",
        "composite_score": 68.0,
        "market_type": "1x2",
        "outcome": "home",
        "sport": "soccer",
        "league": "psl",
    }
    # Should NOT be rejected as ISBets-only; may succeed or fail for other reasons
    # The important thing: it should not return False due to ISBets gate
    _is_isbets = _is_isbets_only_fixture(conn, match_key)
    assert _is_isbets is False, (
        "Match with non-ISBets bookmaker should not be flagged as ISBets-only"
    )
    conn.close()


# ── (b) _GHOST_FIXTURE_DAYS == 3 ──────────────────────────────────────────────

def test_ghost_fixture_days_constant():
    """_GHOST_FIXTURE_DAYS must be 3 (auto-void threshold from W81-SETTLE)."""
    assert _GHOST_FIXTURE_DAYS == 3, (
        f"_GHOST_FIXTURE_DAYS must be 3, got {_GHOST_FIXTURE_DAYS}. "
        "This constant controls when ISBets ghost fixtures are auto-voided."
    )


def test_settle_edges_code_checks_ghost_days():
    """settle_edges() source must reference _GHOST_FIXTURE_DAYS in the auto-void check."""
    scrapers_root = os.path.join(_BOT_DIR, "..", "scrapers")
    settlement_path = os.path.join(scrapers_root, "edge", "settlement.py")
    with open(settlement_path, encoding="utf-8") as f:
        src = f.read()
    assert "_GHOST_FIXTURE_DAYS" in src, "_GHOST_FIXTURE_DAYS not found in settlement.py"
    # Verify the pattern: days_elapsed >= _GHOST_FIXTURE_DAYS AND _is_isbets_only_fixture
    import re
    assert re.search(r"_GHOST_FIXTURE_DAYS.*_is_isbets_only_fixture|_is_isbets_only_fixture.*_GHOST_FIXTURE_DAYS", src), (
        "settle_edges() must combine _GHOST_FIXTURE_DAYS check with _is_isbets_only_fixture()"
    )


# ── (c) _fuzzy_match_result at ±5 days ────────────────────────────────────────

@pytest.mark.parametrize("delta", [-5, -3, -1, 0, 1, 3, 5])
def test_fuzzy_match_finds_result_at_delta(delta: int):
    """_fuzzy_match_result() must find results ±5 days from the match_key date."""
    conn = _fresh_db()
    today = datetime.now(timezone.utc).date()
    real_date = (today + timedelta(days=delta)).strftime("%Y-%m-%d")

    # Insert result at the offset date
    conn.execute("""
        INSERT INTO match_results
            (match_key, sport, league, home_team, away_team,
             home_score, away_score, result, match_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        f"arsenal_vs_chelsea_{real_date}",
        "soccer", "epl",
        "arsenal", "chelsea",
        2, 1, "home",
        real_date,
    ))
    conn.commit()

    # Query with base date (no offset)
    base_date = today.strftime("%Y-%m-%d")
    match_key = f"arsenal_vs_chelsea_{base_date}"
    row = _fuzzy_match_result(conn, match_key, "soccer")

    assert row is not None, (
        f"_fuzzy_match_result() failed to find result at delta={delta:+d} days. "
        "Must support ±5 day tolerance (W81-SETTLE)."
    )
    conn.close()


def test_fuzzy_match_returns_none_beyond_5_days():
    """_fuzzy_match_result() must NOT find results beyond ±5 days."""
    conn = _fresh_db()
    today = datetime.now(timezone.utc).date()
    far_date = (today + timedelta(days=7)).strftime("%Y-%m-%d")

    conn.execute("""
        INSERT INTO match_results
            (match_key, sport, league, home_team, away_team,
             home_score, away_score, result, match_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        f"arsenal_vs_chelsea_{far_date}",
        "soccer", "epl",
        "arsenal", "chelsea",
        1, 0, "home",
        far_date,
    ))
    conn.commit()

    base_date = today.strftime("%Y-%m-%d")
    row = _fuzzy_match_result(conn, f"arsenal_vs_chelsea_{base_date}", "soccer")
    assert row is None, (
        "_fuzzy_match_result() found a result at delta=+7 days — beyond ±5 tolerance."
    )
    conn.close()


# ── (d) _TEAM_ALIASES resolves key aliases ────────────────────────────────────

@pytest.mark.parametrize("alias,canonical", [
    ("wolves", "wolverhampton_wanderers"),
    ("spurs", "tottenham_hotspur"),
    ("man_city", "manchester_city"),
    ("sundowns", "mamelodi_sundowns"),
    ("pirates", "orlando_pirates"),
])
def test_team_aliases_resolve(alias: str, canonical: str):
    """_TEAM_ALIASES must map bookmaker short names to ESPN canonical names."""
    assert alias in _TEAM_ALIASES, f"Alias '{alias}' not in _TEAM_ALIASES"
    assert _TEAM_ALIASES[alias] == canonical, (
        f"_TEAM_ALIASES['{alias}'] = '{_TEAM_ALIASES[alias]}', expected '{canonical}'"
    )


def test_team_aliases_are_bidirectional():
    """_TEAM_ALIASES must have reverse entries so ESPN names also resolve to bookmaker forms."""
    from scrapers.edge.settlement import _expand_team_key
    variants = _expand_team_key("wolves")
    assert "wolverhampton_wanderers" in variants, (
        "_expand_team_key('wolves') must include 'wolverhampton_wanderers'"
    )
    # Reverse: ESPN full name maps back to bookmaker short form
    reverse = _expand_team_key("wolverhampton_wanderers")
    assert "wolves" in reverse, (
        "_expand_team_key('wolverhampton_wanderers') must include 'wolves' for reverse lookup"
    )
